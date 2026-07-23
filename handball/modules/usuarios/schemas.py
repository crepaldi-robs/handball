from __future__ import annotations

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    temporary_password: str = Field(min_length=1, max_length=1024)
    roles: list[str] = Field(min_length=1)
    person_id: int | None = None
    full_name: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)
    linked_player_id: int | None = None


class RoleUpdate(BaseModel):
    roles: list[str] = Field(min_length=1)


class TemporaryPasswordReset(BaseModel):
    temporary_password: str = Field(min_length=1, max_length=1024)


class OwnPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)
