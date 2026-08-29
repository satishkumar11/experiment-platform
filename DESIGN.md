# Design Document

## Architecture

There are four things this service does: let someone define an experiment, decide which variant a visitor sees, record what happened, and report on it. Under the hood that's one Postgres database and four endpoints — `POST /experiments` for config, `GET /assign` for the hot path, `POST /expose` and `POST /convert` for tracking, and `GET /experiments/{id}/results` for reporting.

The main decision I made was to treat reads and writes as two different problems, because they actually have different requirements. `/assign` runs on every page load, so it has to be fast and it can't go down — it never touches Postgres directly. Instead, experiment configs (variants and their weights) sit in an in-memory cache that refreshes every 30 seconds, and assignment itself is just a hash function with no I/O at all. Tracking is the opposite: it happens after the page has already rendered, so it's fine for it to be a normal synchronous write to Postgres, and it's even fine if it occasionally fails — you lose a bit of reporting accuracy, not a customer's page.

That split — assignment as pure computation, tracking as durable writes, and nothing in the fast path depending on the slow one — is really the whole idea the rest of this doc explains.

## Determinism

Assignment works like this: `bucket = sha256(salt + experiment_id + visitor_id) % 10000`, and then that bucket number gets mapped onto cumulative weight ranges. A 50/50 split is just "buckets 0–4999 are A, 5000–9999 are B."

The nice thing about this is that it's sticky without needing memory. The same three inputs always hash to the same number, so I don't need a database row anywhere saying "visitor X is in variant B" — the function itself is the answer, every time, on every server, even after a restart. SHA-256 also spreads values close to uniformly, so even with only a couple thousand visitors the actual split tracks the configured weights pretty closely (I tested this locally: 2,000 simulated visitors on a 50/50 split came out 986/1014).

Two smaller details mattered more than I expected. First, each experiment gets its own random salt, so a visitor's bucket in one experiment has nothing to do with their bucket in another — otherwise someone could end up "always in the top 10%" across every test on the site. Second, the variants have to be iterated in a fixed order for the cumulative-weight math to be consistent, and I originally almost let that fall out of the database's default row order, which is not guaranteed to be stable. I added an explicit `position` field instead — a subtle bug like that would have made bucket boundaries quietly shift after something as unrelated as a driver upgrade.

## Scale

The two paths scale very differently, which is really the point of splitting them. `/assign` is just CPU and a cache read, so it scales horizontally — add more instances, done, since there's nothing shared to coordinate except a cheap periodic config refresh. Tracking writes are where real load actually lands, and that's the first thing I'd change if this needed to handle serious traffic: instead of writing to Postgres synchronously from the request, push the event onto a queue and batch-insert from a consumer. That way the database absorbs bursts instead of rejecting them, and a slow write never becomes a slow HTTP response.

I'd also expect the results endpoint to become a bottleneck before assignment does, since it currently runs `COUNT()` over raw event tables. That's fine now; at real scale I'd move to a rollup table refreshed every minute or so — results don't need to be accurate to the second.

Worth noting the actual traffic shape here: assignment calls vastly outnumber tracking calls, and tracking calls vastly outnumber config changes. The architecture leans into that — the busiest path is also the cheapest one.

## Reliability and failure modes

This is probably the part I thought about the most, since the brief is explicit that this sits on the page-render critical path.

If Postgres gets slow or goes down, the config cache just keeps serving whatever it last had. The refresh failure gets logged, not raised, so a visitor might get a slightly stale config but still a correct, sticky assignment — not an error. If the cache has genuinely never been populated (say, the database was down since the service started), `/assign` returns a 404 for that experiment, and the expectation is that the calling website treats a 404 as "just show the default content," never as something that should block the page. That handoff — what the client does with a failed assignment call — is really the actual fail-safe boundary, so it's worth stating outright rather than assuming.

Tracking failures are lower stakes: if `/expose` or `/convert` fails, that's a 5xx to a call the browser is making after the page already rendered, so it costs you some reporting completeness, not the visitor's experience. Duplicate calls (a retry, a double-fire) are handled with a uniqueness constraint on `(visitor_id, experiment_id)` for exposures, so a repeat is just a no-op instead of a double count.

If I had to compress the whole philosophy into one line: when something goes wrong, the assignment path should fail toward "no experiment," never toward an error page.

## Correctness

The determinism argument above covers assignment correctness — it's a pure function, so it can't disagree with itself. Counting correctness is a slightly different problem: when `/convert` fires, it credits the variant the visitor was actually exposed to (by looking up their existing exposure row), not whatever `/assign` would return right now. That matters because experiment configs can change mid-flight, and an exposure is a historical fact that shouldn't retroactively change. If someone calls `/convert` for a visitor who was never exposed, it just gets dropped rather than guessed at — attributing it to something would quietly corrupt the numbers.

Where I'll be honest about a real gap: the results endpoint reports a raw conversion rate with no confidence interval, no minimum sample size, nothing about repeated peeking. With small numbers, "B is winning" can easily just be noise. As it stands, this dashboard should be read as descriptive, not as a significance test. The cheapest fix would be a minimum-exposures gate before calling a winner, plus a basic two-proportion z-test next to the raw number — I just didn't get to it.

## The LLM decision

The brief is pretty direct about this: the assignment path is latency-sensitive, and LLM calls are slow, costly, and can fail — so the one rule I held to was that the LLM can never sit inside `/assign`.

Instead, the call happens exactly once, synchronously, when an experiment is created and a variant is flagged as AI-generated. Whatever comes back gets stored in the same `content` field a normal static variant would use, so by the time `/assign` runs, it has no idea (and doesn't care) whether that string was written by a person or generated — it's just reading a value out of the cache.

If there's no API key, or the call throws, or it comes back empty, the system falls back to a caller-supplied fallback string rather than failing the whole experiment creation. An LLM having a bad moment shouldn't stop someone from launching a test.

What I didn't build: any notion of refreshing that content later, or generating different copy per segment. Both are reasonable extensions, but they'd need to be background jobs, not something that happens inline.

## Trade-offs and next steps

Things I left out on purpose, and why I think that's a reasonable call for a 24-hour core:

Auth — every endpoint is open right now, which is fine for a single-tenant demo but obviously not for anything real; a real version needs API keys scoped per site. An event queue for tracking writes — I write straight to Postgres, which is correct at the scale a single instance can handle but is the first thing I'd swap out under real load. Statistical significance testing — already covered above, this is the part I'm least happy leaving out. Adaptive allocation — traffic splits are fixed once an experiment starts; shifting traffic toward a winning variant over time (something like Thompson sampling) is a natural next step, though it does complicate "sticky and deterministic," since the split itself would then be changing. Cross-experiment learning — nothing here carries insight from one experiment into another (e.g. "headlines with numbers tend to win"), which is a genuinely interesting problem but a much bigger system than this one. An admin UI, since the brief said it was optional. And results caching — fine now, would need a rollup table once the event tables get big.

If I had another day, in order: I'd add a minimum-sample-size check to results first, since shipping a number with no confidence framing is the weakest part of what's here; then move tracking writes off the request path onto a queue; then add auth; then look at adaptive allocation.
