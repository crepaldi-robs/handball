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
    team_id: int | None = None


class TeamCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    slug: str = Field(min_length=1, max_length=60)
    display_name: str = Field(min_length=1, max_length=120)
    season_label: str | None = Field(default=None, max_length=20)


class TeamActiveUpdate(BaseModel):
    active: bool


class PlayerAccountCreate(BaseModel):
    team_id: int
    team_member_id: int
    username: str = Field(min_length=1, max_length=80)
    temporary_password: str = Field(min_length=1, max_length=1024)


class RoleUpdate(BaseModel):
    roles: list[str] = Field(min_length=1)


class PermissionGrantUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class TemporaryPasswordReset(BaseModel):
    temporary_password: str = Field(min_length=1, max_length=1024)


class OwnPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)
