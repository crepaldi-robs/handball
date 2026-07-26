from __future__ import annotations

from pydantic import BaseModel, Field


class SqlQueryInput(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=200)
