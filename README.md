# Experiment Platform

A small backend service that answers, on every page load: **"which variant should this visitor see?"** — and later reports which variant is winning.

Built for a take-home assignment. See [DESIGN.md](DESIGN.md) for the architecture and reasoning — that document is the primary deliverable.

## What's built

- **Assignment** — `GET /assign` — deterministic, sticky, hash-based variant assignment honoring traffic-allocation weights. No database read is required to compute the answer.
- **Tracking** — `POST /expose`, `POST /convert` — durable, duplicate-safe event recording.
- **Results** — `GET /experiments/{id}/results` — exposures, conversions, and conversion rate per variant.
- **Configuration** — `POST /experiments`, `GET /experiments`, `GET /experiments/{id}` — define an experiment's variants and traffic split.
- **AI-generated variant content** — a variant can be flagged `is_ai_generated`; its copy is generated once, at experiment-creation time, and cached — never on the assignment hot path.
- **Demo page** — a single static HTML page (`/`) that creates an experiment, simulates a visitor, and shows live results.

## What's deliberately not built

See "Trade-offs and next steps" in [DESIGN.md](DESIGN.md) — auth, adaptive/bandit allocation, a real event queue, and statistical-significance testing were left out on purpose, in favor of a small, correct core.

## Project structure

```
app/
  main.py          FastAPI app, router wiring, static file mount
  database.py      SQLAlchemy engine/session
  models.py        Experiment, Variant, Exposure, Conversion
  schemas.py       Pydantic request/response models
  assignment.py    the hash-bucket assignment function (the core of the system)
  cache.py         in-memory experiment config cache, stale-on-failure
  llm.py           LLM call for AI-generated variant content, with fallback
  routers/
    experiments.py /experiments (config)
    assign.py      /assign
    track.py       /expose, /convert
    results.py     /experiments/{id}/results
static/
  index.html       demo page
DESIGN.md
```

## Setup (local)

Requires Python 3.11+ and a Postgres database (local, Docker, or free-tier hosted).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set DATABASE_URL to your Postgres instance,
# and ANTHROPIC_API_KEY if you want real AI-generated content
# (without it, AI variants fall back to their static fallback_content)

uvicorn app.main:app --reload
```

Open `http://localhost:8000/` for the demo page, or `http://localhost:8000/docs` for interactive API docs.

## API reference

### `POST /experiments`
Create an experiment. Variant weights must sum to 100.

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

### `GET /assign?visitor_id={id}&experiment_id={id}`
Returns the variant this visitor should see. Same `visitor_id` + `experiment_id` always returns the same variant. 404 if the experiment is unknown or inactive — callers should treat that as "show default content," not as an error to surface to the visitor.

### `POST /expose`
`{ "visitor_id": "...", "experiment_id": "...", "variant_id": "..." }` — record that a visitor saw a variant. Safe to call more than once for the same visitor+experiment.

### `POST /convert`
`{ "visitor_id": "...", "experiment_id": "...", "goal": "default" }` — record a conversion, credited to whatever variant that visitor was exposed to.

### `GET /experiments/{id}/results`
Per-variant exposures, conversions, and conversion rate.

## Deployment

Deployed on [Render](https://render.com) (or Railway) as a single web service, with a managed Postgres instance (e.g. [Neon](https://neon.tech)).

1. Push this repo to GitHub.
2. Create a Postgres database (Neon/Supabase/Render Postgres) and copy its connection string.
3. Create a new Render Web Service from the repo:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Environment variables: `DATABASE_URL`, `ANTHROPIC_API_KEY`
4. Tables are created automatically on startup (`Base.metadata.create_all`).

**Live URL:** <https://experiment-platform-x18h.onrender.com>

**Demo page:** <https://experiment-platform-x18h.onrender.com/> — creates an experiment, simulates a visitor (assign → expose → convert), and shows live results.

Hosted on Render's free tier, so the instance spins down after ~15 minutes of inactivity — the first request after a period of idleness can take 50+ seconds to wake it up. Subsequent requests are fast. No credentials are required to exercise the API; all endpoints are open.
