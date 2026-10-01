"""Validated API contracts; dates stay ISO-8601 in SQLite."""

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Status(str, Enum):
    saved = "saved"
    applied = "applied"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"


class ApplicationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=160)
    location: str = Field(default="", max_length=120)
    status: Status = Status.saved
    job_url: HttpUrl | None = None
    applied_on: date | None = None
    follow_up_on: date | None = None
    notes: str = Field(default="", max_length=5000)

    @field_validator("job_url")
    @classmethod
    def no_url_credentials(cls, value):
        if value and (value.username or value.password):
            raise ValueError("URLs must not contain credentials")
        return value


class Application(ApplicationInput):
    id: int
    archived: bool
    created_at: str
    updated_at: str


class ArchiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: bool


class HistoryEntry(BaseModel):
    id: int
    previous_status: Status | None
    status: Status
    changed_at: str
