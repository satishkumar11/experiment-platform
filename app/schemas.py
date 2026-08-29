from typing import List, Optional

from pydantic import BaseModel, field_validator


class VariantIn(BaseModel):
    key: str
    weight: int
    is_ai_generated: bool = False
    prompt: Optional[str] = None
    content: Optional[str] = None
    fallback_content: Optional[str] = None


class ExperimentCreate(BaseModel):
    name: str
    variants: List[VariantIn]

    @field_validator("variants")
    @classmethod
    def validate_variants(cls, v: List[VariantIn]) -> List[VariantIn]:
        if len(v) < 2:
            raise ValueError("an experiment needs at least 2 variants")
        if sum(variant.weight for variant in v) != 100:
            raise ValueError("variant weights must sum to 100")
        return v


class VariantOut(BaseModel):
    id: str
    key: str
    weight: int
    is_ai_generated: bool
    content: Optional[str]

    model_config = {"from_attributes": True}


class ExperimentOut(BaseModel):
    id: str
    name: str
    is_active: bool
    variants: List[VariantOut]

    model_config = {"from_attributes": True}


class AssignOut(BaseModel):
    experiment_id: str
    variant_id: str
    variant_key: str
    content: Optional[str]


class ExposeIn(BaseModel):
    visitor_id: str
    experiment_id: str
    variant_id: str


class ConvertIn(BaseModel):
    visitor_id: str
    experiment_id: str
    goal: str = "default"


class VariantResult(BaseModel):
    variant_key: str
    exposures: int
    conversions: int
    conversion_rate: float


class ExperimentResults(BaseModel):
    experiment_id: str
    experiment_name: str
    results: List[VariantResult]
