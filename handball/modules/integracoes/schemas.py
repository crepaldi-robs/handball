from __future__ import annotations

from pydantic import BaseModel, Field


class GoogleTeamInput(BaseModel):
    team_id: int | None = Field(default=None, gt=0)


class GoogleCalendarSettingsInput(GoogleTeamInput):
    publish_trainings: bool = True
    publish_games: bool = True
    publish_championships: bool = True


class GoogleDisconnectInput(GoogleTeamInput):
    make_calendar_private: bool = True
    connection_version: int = Field(gt=0)
