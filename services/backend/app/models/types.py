from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator


def _validate_json_numbers(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON values cannot contain NaN or Infinity")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_numbers(item)


class StrictJSON(TypeDecorator[Any]):
    """Portable JSON that rejects non-standard floating-point values."""

    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: Any,
        dialect: Dialect,
    ) -> Any:
        _validate_json_numbers(value)
        return value


class UTCDateTime(TypeDecorator[datetime]):
    """Persist aware datetimes as UTC and restore awareness on SQLite."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must include a timezone")
        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = ["StrictJSON", "UTCDateTime"]
