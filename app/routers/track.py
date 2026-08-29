from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversion, Exposure
from ..schemas import ConvertIn, ExposeIn

router = APIRouter(tags=["track"])


@router.post("/expose", status_code=202)
def expose(payload: ExposeIn, db: Session = Depends(get_db)):
    db.add(
        Exposure(
            visitor_id=payload.visitor_id,
            experiment_id=payload.experiment_id,
            variant_id=payload.variant_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # duplicate exposure for this visitor+experiment: already recorded, no-op
        db.rollback()
    return {"status": "ok"}


@router.post("/convert", status_code=202)
def convert(payload: ConvertIn, db: Session = Depends(get_db)):
    exposure = (
        db.query(Exposure)
        .filter(
            Exposure.visitor_id == payload.visitor_id,
            Exposure.experiment_id == payload.experiment_id,
        )
        .first()
    )
    if not exposure:
        # Can't credit a conversion to a variant the visitor was never exposed to.
        return {"status": "ignored", "reason": "no prior exposure for this visitor+experiment"}

    db.add(
        Conversion(
            visitor_id=payload.visitor_id,
            experiment_id=payload.experiment_id,
            variant_id=exposure.variant_id,
            goal=payload.goal,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"status": "ok"}
