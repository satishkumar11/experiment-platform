from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..cache import cache
from ..database import get_db
from ..llm import generate_variant_content
from ..models import Experiment, Variant
from ..schemas import ExperimentCreate, ExperimentOut

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post("", response_model=ExperimentOut)
def create_experiment(payload: ExperimentCreate, db: Session = Depends(get_db)):
    experiment = Experiment(name=payload.name)
    db.add(experiment)
    db.flush()

    for position, v in enumerate(payload.variants):
        content = v.content
        if v.is_ai_generated:
            content = generate_variant_content(
                prompt=v.prompt or f"Write a short, compelling headline for: {payload.name}",
                fallback=v.fallback_content or v.content or "Welcome!",
            )
        db.add(
            Variant(
                experiment_id=experiment.id,
                key=v.key,
                weight=v.weight,
                position=position,
                is_ai_generated=v.is_ai_generated,
                prompt=v.prompt,
                content=content,
                fallback_content=v.fallback_content,
            )
        )

    db.commit()
    db.refresh(experiment)
    cache.invalidate()
    return experiment


@router.get("", response_model=list[ExperimentOut])
def list_experiments(db: Session = Depends(get_db)):
    return db.query(Experiment).order_by(Experiment.created_at.desc()).all()


@router.get("/{experiment_id}", response_model=ExperimentOut)
def get_experiment(experiment_id: str, db: Session = Depends(get_db)):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise HTTPException(status_code=404, detail="experiment not found")
    return experiment
