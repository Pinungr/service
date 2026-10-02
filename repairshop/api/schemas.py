"""Shared request and response shapes. Money is always whole paise (int)."""
from typing import Any
import uuid
from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Response models list exactly what the browser receives; other columns are dropped."""
    model_config = ConfigDict(extra='ignore', from_attributes=True)


class Command(BaseModel):
    """A state-changing request on a versioned record."""
    expected_version: int | None = Field(None, description='The version the client last read; 409 if it has changed.')
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=80,
                              description='Idempotency key: retrying with the same key never repeats the effect.')
    payload: dict[str, Any] = Field(default_factory=dict)


class Ok(BaseModel):
    ok: bool = True
    id: int | None = None


class Option(Model):
    value: Any
    label: str


class Page(BaseModel):
    items: list[Any]
    offset: int = 0
    limit: int = 50
    has_more: bool = False


def page(rows, offset, limit, model=None):
    """Callers fetch limit+1 rows so `has_more` needs no second count query."""
    items = [model.model_validate(r) if model else r for r in rows[:limit]]
    return Page(items=items, offset=offset, limit=limit, has_more=len(rows) > limit)
