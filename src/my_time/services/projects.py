from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from ..models.core import User, Team
from ..models.work import ProjectMember


def validate_owner(db, owner_id, team_id):
    if owner_id is None:
        return
    owner = db.get(User, owner_id)
    if not owner or owner.team_id != team_id or not owner.active:
        raise HTTPException(422, "Project owner must be an active user in this team")


def validate_assignee(db, assignee, project_id, planned_date=None):
    if not assignee.active or assignee.role != "member":
        raise HTTPException(422, "Choose an active team member")
    allocation = db.query(ProjectMember).filter_by(project_id=project_id, user_id=assignee.id,
                                                  team_id=assignee.team_id, active=True).first()
    if not allocation:
        raise HTTPException(422, "Add the assignee to this project before assigning work")
    team = db.get(Team, assignee.team_id)
    when = planned_date or datetime.now(ZoneInfo(team.timezone)).date()
    if (allocation.start_date and when < allocation.start_date) or (allocation.end_date and when > allocation.end_date):
        raise HTTPException(422, "Planned work date falls outside the assignee's project allocation")


def validate_capacity(db, team_id, data, existing_id=None):
    if not data.active:
        return
    # Member writes lock the employee first, serializing concurrent allocation
    # changes on PostgreSQL. Sweep inclusive date intervals so disjoint bookings
    # are not incorrectly added together.
    start, end = data.start_date or date.min, data.end_date or date.max
    events = {start.toordinal(): data.allocation_percent, end.toordinal()+1: -data.allocation_percent}
    for row in db.query(ProjectMember).filter_by(team_id=team_id, user_id=data.user_id, active=True):
        if row.id == existing_id:
            continue
        left, right = max(start, row.start_date or date.min), min(end, row.end_date or date.max)
        if left <= right:
            events[left.toordinal()] = events.get(left.toordinal(), Decimal(0)) + row.allocation_percent
            events[right.toordinal()+1] = events.get(right.toordinal()+1, Decimal(0)) - row.allocation_percent
    total = Decimal(0)
    for day in sorted(events):
        total += events[day]
        if total > 100:
            raise HTTPException(409, "Employee allocation exceeds 100% across overlapping projects")
