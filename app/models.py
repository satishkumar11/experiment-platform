import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    # Per-experiment salt mixed into the assignment hash so bucket assignment
    # can't be predicted across experiments even if the hashing scheme is known.
    salt = Column(String, nullable=False, default=gen_uuid)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    variants = relationship(
        "Variant",
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="Variant.position",
    )


class Variant(Base):
    __tablename__ = "variants"

    id = Column(String, primary_key=True, default=gen_uuid)
    experiment_id = Column(String, ForeignKey("experiments.id"), nullable=False)
    key = Column(String, nullable=False)
    weight = Column(Integer, nullable=False)  # 0-100, must sum to 100 per experiment
    # Stable ordering for cumulative-weight bucket mapping — must not depend on
    # UUID primary key order, which is not deterministic across reloads.
    position = Column(Integer, nullable=False, default=0)
    is_ai_generated = Column(Boolean, nullable=False, default=False)
    prompt = Column(Text, nullable=True)
    content = Column(Text, nullable=True)  # static text, or cached LLM output
    fallback_content = Column(Text, nullable=True)  # used if LLM generation fails

    experiment = relationship("Experiment", back_populates="variants")


class Exposure(Base):
    __tablename__ = "exposures"
    __table_args__ = (
        UniqueConstraint("visitor_id", "experiment_id", name="uq_exposure_visitor_experiment"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    visitor_id = Column(String, nullable=False, index=True)
    experiment_id = Column(String, ForeignKey("experiments.id"), nullable=False, index=True)
    variant_id = Column(String, ForeignKey("variants.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversion(Base):
    __tablename__ = "conversions"
    __table_args__ = (
        UniqueConstraint(
            "visitor_id", "experiment_id", "goal", name="uq_conversion_visitor_experiment_goal"
        ),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    visitor_id = Column(String, nullable=False, index=True)
    experiment_id = Column(String, ForeignKey("experiments.id"), nullable=False, index=True)
    variant_id = Column(String, ForeignKey("variants.id"), nullable=False)
    goal = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=datetime.utcnow)
