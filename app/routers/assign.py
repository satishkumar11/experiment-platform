from fastapi import APIRouter, HTTPException, Query

from ..assignment import get_bucket, pick_variant
from ..cache import cache
from ..schemas import AssignOut

router = APIRouter(tags=["assign"])


@router.get("/assign", response_model=AssignOut)
def assign(visitor_id: str = Query(...), experiment_id: str = Query(...)):
    experiment = cache.get(experiment_id)
    if experiment is None:
        # Fail-safe: unknown, paused, or (briefly) not-yet-cached experiments
        # never 500 the page — callers are expected to treat a 404 here as
        # "show default content" rather than blocking render.
        raise HTTPException(status_code=404, detail="experiment not found or inactive")

    bucket = get_bucket(visitor_id, experiment_id, experiment["salt"])
    variant = pick_variant(bucket, experiment["variants"])

    return AssignOut(
        experiment_id=experiment_id,
        variant_id=variant["id"],
        variant_key=variant["key"],
        content=variant["content"],
    )
