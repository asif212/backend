from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class TeamInput(Input):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Asia/Kolkata"


class TeamState(Input):
    status: Literal["active", "suspended"]


class EmployeeInput(Login):
    password: str = Field(min_length=12, max_length=256)
    name: str = Field(min_length=1, max_length=120)
    role: Literal["lead", "member"] = "member"
    location_id: int | None = None
    department: str = Field(default="", max_length=120)
    job_title: str = Field(default="", max_length=120)
    joined_on: date | None = None


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    assignee_id: int
    estimate_minutes: int = Field(gt=0, le=1000000)
    due_date: date | None = None


class Transition(Input):
    status: Literal["assigned", "in_progress", "blocked", "done"]
    note: str = Field(default="", max_length=2000)


class Coordinates(Input):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(ge=0, le=10000, allow_inf_nan=False)


class LocationInput(Coordinates):
    name: str = Field(min_length=1, max_length=120)


class HolidayInput(Input):
    location_id: int
    date: date
    name: str = Field(min_length=1, max_length=200)


class LeaveInput(Input):
    policy_id: int | None = None
    duration: Literal["full", "half"] = "full"
    start_date: date
    end_date: date
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 365:
            raise ValueError("Leave must be an ordered date range of at most 366 days")
        if self.duration == "half" and self.start_date != self.end_date:
            raise ValueError("Half-day leave must be a single date")
        return self


class Decision(Input):
    status: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=2000)
