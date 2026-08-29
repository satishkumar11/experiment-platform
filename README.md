# Experiment Platform

A small backend for running A/B tests. It answers one question on every page load — "which variant should this visitor see?" — and later reports which variant is winning.

This was built for a take-home assignment. [DESIGN.md](DESIGN.md) has the actual reasoning behind the decisions here, and it's the part that matters most — this README is just setup and reference.

## What's here

- **Assignment** (`GET /assign`) — sticky, deterministic, hash-based. No database read needed to compute the answer.
- **Tracking** (`POST /expose`, `POST /convert`) — records what happened, safely handles duplicates.
- **Results** (`GET /experiments/{id}/results`) — exposures, conversions, and conversion rate per variant.
- **Config** (`POST /experiments`) — define an experiment's variants and traffic split.
- **AI-generated variant content** — flag a variant as `is_ai_generated` and its copy gets written by an LLM once, when the experiment is created — never during assignment.
- **A demo page** at `/` that walks through the whole flow: create an experiment, simulate a visitor, see results.

What I left out on purpose (auth, adaptive allocation, a real event queue, proper statistical significance) is explained in the design doc, not silently missing.

## Running it locally

You'll need Python 3.11+ and a Postgres database somewhere (Neon's free tier works fine).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in DATABASE_URL, and ANTHROPIC_API_KEY if you want real AI-generated
# content — without it, AI variants just use their fallback text

uvicorn app.main:app --reload
```

Then open `http://localhost:8000/` for the demo page, or `http://localhost:8000/docs` for interactive API docs.

## API, briefly

**`POST /experiments`** — create an experiment. Weights must add up to 100.

```json
{
  "name": "homepage-headline",
  "variants": [
    { "key": "control", "weight": 50, "content": "Welcome to our site!" },
    {
      "key": "ai_variant",
      "weight": 50,
      "is_ai_generated": true,
      "prompt": "Write a short, punchy homepage headline for a productivity app.",
      "fallback_content": "Get more done, every day."
    }
  ]
}
```

**`GET /assign?visitor_id=...&experiment_id=...`** — same visitor, same experiment, always the same variant back. If the experiment doesn't exist or is paused, this returns 404 — the intended behavior on the caller's side is "just show default content," not "show an error."

**`POST /expose`** — `{ visitor_id, experiment_id, variant_id }`, records that a visitor saw a variant. Safe to call more than once.

**`POST /convert`** — `{ visitor_id, experiment_id, goal }`, records a conversion against whatever variant that visitor actually saw.

**`GET /experiments/{id}/results`** — per-variant exposures, conversions, conversion rate.

## Where the code lives

```text
app/
  main.py          FastAPI app, wiring everything together
  database.py      SQLAlchemy engine/session
  models.py        Experiment, Variant, Exposure, Conversion
  schemas.py       request/response models
  assignment.py    the hash-bucket function — the actual core of the system
  cache.py         in-memory experiment config cache, stays stale rather than fails
  llm.py           the one place the LLM gets called, with a fallback
  routers/         one file per group of endpoints
static/
  index.html       the demo page
DESIGN.md
```

## Live version

**Service:** <https://experiment-platform-x18h.onrender.com>
**Demo:** same URL, at `/` — creates an experiment, simulates a visitor, shows results.

No login or API key needed to try it. It's on Render's free tier, so if it's been sitting idle for a while the first request can take 30–50 seconds to wake back up — that's normal, not broken.

## Deploying your own copy

1. Push this repo to GitHub.
2. Spin up a Postgres database (Neon, Supabase, whatever) and grab its connection string.
3. Create a Render web service pointed at the repo:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Env vars: `DATABASE_URL`, `ANTHROPIC_API_KEY`
4. That's it — tables get created automatically the first time it starts up.
