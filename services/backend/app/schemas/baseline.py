from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import Field

from app.schemas.persistence import PersistenceSchema

DEFAULT_BASELINE_WINDOW_DAYS = 14
MAXIMUM_BASELINE_WINDOW_DAYS = 28


class BaselineCreate(PersistenceSchema):
    as_of_date: date
    window_days: Annotated[
        int,
        Field(
            ge=DEFAULT_BASELINE_WINDOW_DAYS,
            le=MAXIMUM_BASELINE_WINDOW_DAYS,
        ),
    ] = DEFAULT_BASELINE_WINDOW_DAYS


__all__ = [
    "BaselineCreate",
    "DEFAULT_BASELINE_WINDOW_DAYS",
    "MAXIMUM_BASELINE_WINDOW_DAYS",
]
