"""In-memory experiment config cache with stale-on-failure fallback.

This is the fail-safe core of the assignment path: /assign never queries the
database directly. It reads from this cache, which refreshes from Postgres on
a TTL. If a refresh fails (DB slow/down), we log it and keep serving the last
known-good config instead of raising — a database outage degrades to "slightly
stale experiment configs," never to a broken page.
"""

from __future__ import annotations

import logging
import time

from .database import SessionLocal
from .models import Experiment

logger = logging.getLogger(__name__)

TTL_SECONDS = 30


class ExperimentCache:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._last_refresh: float = 0

    def get(self, experiment_id: str) -> dict | None:
        self._maybe_refresh()
        return self._data.get(experiment_id)

    def invalidate(self) -> None:
        """Force the next get() to refresh immediately (called after config writes)."""
        self._last_refresh = 0

    def _maybe_refresh(self) -> None:
        if time.time() - self._last_refresh < TTL_SECONDS:
            return
        try:
            self._refresh()
        except Exception:
            logger.exception("experiment cache refresh failed, serving stale cache")

    def _refresh(self) -> None:
        db = SessionLocal()
        try:
            experiments = db.query(Experiment).filter(Experiment.is_active.is_(True)).all()
            fresh = {}
            for exp in experiments:
                fresh[exp.id] = {
                    "id": exp.id,
                    "salt": exp.salt,
                    "variants": [
                        {
                            "id": v.id,
                            "key": v.key,
                            "weight": v.weight,
                            "content": v.content,
                        }
                        for v in exp.variants
                    ],
                }
            self._data = fresh
            self._last_refresh = time.time()
        finally:
            db.close()


cache = ExperimentCache()
