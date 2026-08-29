"""Deterministic visitor -> variant assignment.

The whole trick: bucket = hash(salt + experiment_id + visitor_id) % BUCKET_SIZE.
This is a pure function — the same three inputs always produce the same bucket,
so a visitor gets the same variant every time, on every server, forever, without
ever reading or writing a database. Storage is only needed for reporting
(exposures/conversions), never to determine the answer itself.
"""

from __future__ import annotations

import hashlib
from typing import TypedDict


BUCKET_SIZE = 10_000


class VariantConfig(TypedDict):
    id: str
    key: str
    weight: int
    content: str | None


def get_bucket(visitor_id: str, experiment_id: str, salt: str) -> int:
    key = f"{salt}:{experiment_id}:{visitor_id}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest, 16) % BUCKET_SIZE


def pick_variant(bucket: int, variants: list[VariantConfig]) -> VariantConfig:
    """variants must be in a stable order and have weights summing to 100."""
    cumulative = 0
    for variant in variants:
        cumulative += variant["weight"] * (BUCKET_SIZE // 100)
        if bucket < cumulative:
            return variant
    return variants[-1]  # rounding safety net, should not normally trigger
