from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversion, Experiment, Exposure
from ..schemas import ExperimentResults, VariantResult

router = APIRouter(tags=["results"])


@router.get("/experiments/{experiment_id}/results", response_model=ExperimentResults)
def get_results(experiment_id: str, db: Session = Depends(get_db)):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise HTTPException(status_code=404, detail="experiment not found")

    results = []
    for variant in experiment.variants:
        exposures = (
            db.query(func.count(Exposure.id)).filter(Exposure.variant_id == variant.id).scalar()
        )
        conversions = (
            db.query(func.count(Conversion.id)).filter(Conversion.variant_id == variant.id).scalar()
        )
        rate = (conversions / exposures) if exposures else 0.0
        results.append(
            VariantResult(
                variant_key=variant.key,
                exposures=exposures,
                conversions=conversions,
                conversion_rate=round(rate, 4),
            )
        )

    return ExperimentResults(
        experiment_id=experiment.id,
        experiment_name=experiment.name,
        results=results,
    )
