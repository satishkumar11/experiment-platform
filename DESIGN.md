# Design Document

## Architecture

The service has four surfaces on top of one Postgres database:

- `POST /experiments` — configuration
- `GET /assign` — the hot path
- `POST /expose`, `POST /convert` — tracking
- `GET /experiments/{id}/results` — reporting

The key architectural decision is splitting the system into two paths with very different requirements, and making sure they don't share a failure mode:

**The read path (`/assign`)** must be fast and must not go down, because it's on every page render. It never touches Postgres directly. Experiment configuration (variants + weights) is loaded into an in-memory cache (`app/cache.py`) on a 30-second TTL, and `/assign` reads only from that cache. Assignment itself is a pure hash function (`app/assignment.py`) — no I/O, no lock, no database round trip.

**The write path (`/expose`, `/convert`)** is not latency-sensitive in the same way — it fires after the page has already rendered — so it can afford to be a straightforward synchronous write to Postgres with a uniqueness constraint for dedup. It's fine for it to be slower, and even fine for it to occasionally fail, since a lost tracking event degrades reporting accuracy, not the visitor's page.

This split — compute-only reads, durable writes, and no dependency from the former on the latter — is the single idea the rest of the design hangs off.

## Determinism

Assignment is `bucket = sha256(salt + ":" + experiment_id + ":" + visitor_id) % 10000`, then the bucket is mapped into cumulative weight ranges (e.g., a 50/50 split is buckets `[0, 5000)` and `[5000, 10000)`).

Why this works:

- **Sticky by construction, not by memory.** The same three inputs always hash to the same bucket. We don't need to store "visitor X got variant B" anywhere for assignment to be sticky — the function *is* the source of truth. That also means it's correct across server restarts and across horizontally scaled instances with zero coordination between them.
- **Well-distributed.** SHA-256 output is uniformly distributed, so for any real visitor population the buckets fill close to uniformly; at even a few thousand visitors per experiment, observed splits track the configured weights closely (verified locally: 2,000 simulated visitors on a 50/50 split landed at 986/1014).
- **Per-experiment salt.** Each experiment stores its own random salt, so a visitor's bucket in one experiment is uncorrelated with their bucket in another — a visitor isn't systematically "always in the top decile" across every experiment on the site.
- **Stable variant ordering.** Cumulative-weight mapping depends on iterating variants in a fixed order. Variants have an explicit `position` column set at creation time — not the UUID primary key, whose ordering isn't guaranteed to be stable across queries. Getting this wrong silently would have been a real bug: relying on default row order would make bucket boundaries non-deterministic across a schema/driver change.
- **No storage needed for correctness, storage kept anyway for auditability.** We do store the assignment implicitly the first time a client calls `/expose` (see Correctness below), but that's for reporting, not for computing the answer next time.

## Scale

At millions of calls a day, the two paths scale very differently:

- **`/assign` is pure CPU** (one hash, one loop over a handful of variants) plus a cache lookup. It has no database dependency in the steady state, so it horizontally scales linearly with instance count — add more stateless replicas behind a load balancer, done. The only shared state is the config cache refresh, which is a cheap periodic query (`SELECT * FROM experiments WHERE is_active`), not per-request.
- **Tracking (`/expose`, `/convert`) is where write load actually lands.** This is the bottleneck at scale, not assignment. At high volume, the next step (explicitly not built here — see Trade-offs) is to stop writing synchronously from the request handler and instead push events onto a queue (SQS/Kafka/Kinesis) and batch-insert from a consumer. That decouples "did the write succeed" from "did the HTTP call return quickly," and lets the database absorb bursts instead of rejecting them.
- **What I'd cache further:** the experiment config cache already removes the DB from the assignment path; the next lever is caching *results* aggregates (they don't need to be real-time to the second) rather than running `COUNT()` queries against raw event tables once those tables are large — either a periodic rollup table or a materialized view refreshed every minute.
- **Read/write ratio:** assignment calls vastly outnumber tracking calls (every page view triggers `/assign`; only a fraction of those convert), and tracking in turn outnumbers config changes (`/experiments`) by orders of magnitude. The architecture is built for exactly that shape: the highest-volume path is the cheapest one.

## Reliability and failure modes

This is the part the task weights most heavily, so to be explicit about each failure mode:

| Failure | Behavior |
|---|---|
| Postgres is slow or unreachable, config cache refresh fails | `/assign` keeps serving the last known-good cached config. The failure is logged, not raised. A visitor gets a slightly stale (but still correct and sticky) assignment, not an error. |
| Postgres is down and the cache has never been populated (cold start during an outage) | `/assign` returns 404 for that experiment. The client-side integration contract is: a 404/error from `/assign` means "render default content," never "block the page." This is a contract the calling website's snippet must honor — worth stating explicitly since it's the actual fail-safe boundary. |
| An unknown or paused `experiment_id` is requested | 404, same "fall back to default content" contract. |
| A tracking write (`/expose`, `/convert`) fails | Returns a 5xx to the caller; since these calls happen after render (typically fire-and-forget from the page), this affects reporting completeness, not the visitor's experience. Worth pairing with `sendBeacon`/`keepalive` on the client so the browser doesn't drop the request on page unload. |
| Duplicate `/expose` calls (double-fire, retry, etc.) | A unique constraint on `(visitor_id, experiment_id)` means the second insert is a no-op, not a double count. Same pattern for `/convert` on `(visitor_id, experiment_id, goal)`. |

The overarching default-behavior principle: **when in doubt, the assignment path fails toward "no experiment" rather than toward an error.** A customer's page should never break because our service is unhappy.

## Correctness

- **Assignment correctness** is the determinism argument above: it's a pure function, so it can't drift or disagree with itself.
- **Counting correctness** relies on crediting a conversion to whatever variant the visitor was actually exposed to, not to whatever `/assign` would return *now* — `/convert` looks up the visitor's existing exposure row and copies its `variant_id`, rather than re-deriving it. This matters if an experiment's config changes mid-flight (e.g., someone tweaks a variant's weight); a stored exposure is a fact about what already happened, and shouldn't retroactively change.
- **A conversion with no prior exposure is dropped, not guessed.** If `/convert` is called for a visitor+experiment pair that has no exposure row, it's recorded as `ignored` rather than attributed to a variant — attributing it would silently corrupt the numbers.
- **Statistical validity — the honest gap.** The results endpoint reports raw conversion rate with no confidence interval, no minimum sample size gate, and no correction for repeated peeking. That's a real limitation: with small sample counts, an apparent "B is winning" can easily be noise. In its current form, this dashboard should be read as descriptive, not as a significance test. The cheapest real fix (see Trade-offs) is a minimum-exposures threshold before a variant is allowed to be called a "winner," plus a basic two-proportion z-test alongside the raw rate.

## The LLM decision

The requirement is explicit that the assignment path is latency-sensitive and LLM calls are slow, costly, and can fail — so the constraint was: **the LLM must never be in the request path of `/assign`.**

The call happens exactly once, synchronously, at experiment-creation time (`POST /experiments`, in `app/llm.py`), when a variant is flagged `is_ai_generated`. The generated text is stored in the same `content` column a static variant would use, so `/assign` doesn't know or care whether a variant's copy was written by a person or generated — it just reads a string out of the cache.

Failure handling: if there's no API key configured, or the call raises, or the response is empty, we fall back to a caller-supplied `fallback_content` string (or the plain `content` field, or a hardcoded default) rather than failing experiment creation. An experiment should never fail to be created because an LLM had a bad moment.

What this deliberately doesn't cover: regenerating content later (e.g., periodically refreshing AI copy, or generating per-segment variants), which would need an async job rather than an inline call — noted below as a next step.

## Trade-offs and next steps

**Deliberately not built**, and why each is a reasonable thing to leave out of a 24-hour core:

- **Auth / multi-tenancy** — every endpoint is open. Fine for a single-tenant demo; a real system needs API keys scoped per site.
- **Event queue for tracking writes** — `/expose`/`/convert` write synchronously to Postgres. Correct at the scale a single Postgres instance can take, but the first thing to change under real load (see Scale).
- **Statistical significance testing** — covered honestly above; raw conversion rate only.
- **Adaptive allocation (bandits)** — traffic split is fixed at experiment creation. A logical next step: shift traffic toward a winning variant over time (Thompson sampling or similar), trading a bit of assignment-path complexity for faster experiments — but it also complicates "deterministic and sticky," since the split itself would now be changing over time, which needs its own care.
- **Cross-experiment / cross-site learning** — nothing here uses outcomes from one experiment to inform another. That's a genuinely hard, valuable extension (e.g., "headlines with numbers tend to win on this type of page") but is a different, much larger system.
- **Admin UI** — config is API-only; a minimal UI was explicitly optional in the brief.
- **Results caching / rollups** — results are computed live via `COUNT()`; fine at current scale, would need a rollup table under real load.

Given more time, in priority order: (1) a minimum-sample-size / basic significance check on results, since shipping a number without any confidence framing is the weakest part of the current system; (2) moving tracking writes off the request path onto a queue; (3) API auth; (4) adaptive allocation.
