from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import Field, model_validator
from .schemas import Input, TaskInput


class PlanningInput(Input):
    cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    planned_date: date | None = None
    release_date: date | None = None

    @model_validator(mode="after")
    def planning_ordered(self):
        if self.planned_date and self.release_date and self.release_date < self.planned_date:
            raise ValueError("Release date must be on or after planned date")
        return self


class ProjectInput(PlanningInput):
    key: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,11}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=10000)
    owner_id: int | None = None
    estimate_minutes: int | None = Field(default=None, ge=0, le=100000000)


class ProjectEdit(PlanningInput):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10000)
    owner_id: int | None = None
    estimate_minutes: int | None = Field(default=None, ge=0, le=100000000)


class MemberInput(Input):
    user_id: int
    allocation_percent: Decimal = Field(default=Decimal("100"), gt=0, le=100, max_digits=5, decimal_places=2)
    start_date: date | None = None
    end_date: date | None = None
    active: bool = True

    @model_validator(mode="after")
    def ordered(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Allocation end date must be on or after start date")
        return self


class SprintInput(Input):
    project_id: int
    name: str = Field(min_length=1, max_length=160)
    goal: str = Field(default="", max_length=2000)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def ordered(self):
        if self.end_date < self.start_date:
            raise ValueError("Sprint end must be on or after start")
        return self


class SprintTransition(Input):
    status: Literal["active", "completed"]


class IssueInput(TaskInput, PlanningInput):
    project_id: int
    sprint_id: int | None = None
    parent_id: int | None = None
    kind: Literal["epic", "feature", "story", "task", "bug", "subtask"] = "task"
    priority: Literal["lowest", "low", "medium", "high", "highest"] = "medium"
    story_points: int = Field(default=0, ge=0, le=1000)
    labels: list[str] = Field(default_factory=list, max_length=20)


class IssueEdit(PlanningInput):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    assignee_id: int
    due_date: date | None = None
    sprint_id: int | None = None
    priority: Literal["lowest", "low", "medium", "high", "highest"] = "medium"
    story_points: int = Field(default=0, ge=0, le=1000)
    labels: list[str] = Field(default_factory=list, max_length=20)
    estimate_minutes: int | None = Field(default=None, gt=0, le=1000000)
    kind: Literal["epic", "feature", "story", "task", "bug", "subtask"] | None = None


class CommentInput(Input):
    body: str = Field(min_length=1, max_length=10000)


class WorkLogInput(Input):
    work_date: date
    minutes: int = Field(gt=0, le=1440)
    note: str = Field(default="", max_length=2000)


class LinkInput(Input):
    target_id:int
    kind:Literal["blocks","relates","duplicates"]="relates"


class WatchInput(Input):
    watching:bool
