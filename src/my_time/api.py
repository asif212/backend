import json
from decimal import Decimal
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db
from .auth import authenticated, current_user, manager, admin, verify, ph, issue_session, digest
from .models.core import User, Team, Task, TaskEvent, Attendance, LeaveRequest, WorkLocation, Holiday, AuditLog, Notification, RateLimitState, Session as LoginSession
from .models.hr import EmployeeProfile, LocationHoliday
from . import schemas as s
from .services.location import validate_location

router = APIRouter(prefix="/api/v1")
USER_FIELDS = ("id", "team_id", "username", "name", "role", "active", "must_change_password")


def public(row, fields=None):
    # Preserve money/allocation precision in JSON instead of coercing Decimals
    # to binary floats. The web client displays these decimal strings directly.
    result = {key: getattr(row, key) for key in (fields or row.__table__.columns.keys())}
    return {key: format(value,"f") if isinstance(value,Decimal) else value for key,value in result.items()}


def save(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record already exists or conflicts with related data")


def audit(db, user, action, row):
    db.add(AuditLog(team_id=user.team_id, actor_id=user.id, action=action,
                    target_type=row.__tablename__, target_id=getattr(row, "id", None)))


def scoped(db, model, identifier, user):
    row = db.query(model).filter(model.id == identifier, model.team_id == user.team_id).first()
    if not row:
        raise HTTPException(404, "Record not found")
    return row


def team_user(user):
    if user.team_id is None:
        raise HTTPException(403, "Use a team account for this operation")


def member(user):
    if user.role != "member":
        raise HTTPException(403, "Member account required")


def notify(db, user, kind, row_id):
    db.add(Notification(team_id=user.team_id, user_id=user.id, type=kind, payload_json=json.dumps({"id": row_id})))


@router.post("/auth/login")
def login(data: s.Login, request: Request, db: Session = Depends(get_db)):
    # Persist rate limits so restarts do not clear the window. Serialize at the proxy in production.
    now = datetime.utcnow()
    key = "login:" + (request.client.host if request.client else "unknown")
    limit = db.get(RateLimitState, key)
    if limit and limit.window_start > now - timedelta(minutes=1) and limit.count >= 10:
        raise HTTPException(429, "Too many login attempts", headers={"Retry-After": "60"})
    if not limit:
        limit = RateLimitState(key=key, window_start=now, count=0)
        db.add(limit)
    elif limit.window_start <= now - timedelta(minutes=1):
        limit.window_start, limit.count = now, 0
    limit.count += 1
    save(db)
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify(user.password_hash, data.password) or not user.active:
        raise HTTPException(401, "Invalid credentials")
    if user.team_id is not None and db.get(Team, user.team_id).status != "active":
        raise HTTPException(403, "Team suspended")
    token = issue_session(db, user)
    audit(db, user, "login", user)
    save(db)
    return {"access_token": token, "token_type": "bearer", "user": public(user, USER_FIELDS)}


@router.get("/auth/me")
def me(user: User = Depends(authenticated)):
    return public(user, USER_FIELDS)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(authenticated)):
    token = request.headers["authorization"].split()[1]
    db.query(LoginSession).filter(LoginSession.id_hash == digest(token)).delete()
    save(db)


@router.post("/auth/password", status_code=204)
def password(data: s.PasswordChange, db: Session = Depends(get_db), user: User = Depends(authenticated)):
    if not verify(user.password_hash, data.current_password):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = ph.hash(data.new_password)
    user.must_change_password = False
    db.query(LoginSession).filter(LoginSession.user_id == user.id).delete()
    audit(db, user, "password_changed", user)
    save(db)


@router.get("/teams")
def teams(db: Session = Depends(get_db), user: User = Depends(admin)):
    return [public(t) for t in db.query(Team).order_by(Team.id).limit(200)]


@router.post("/teams", status_code=201)
def create_team(data: s.TeamInput, db: Session = Depends(get_db), user: User = Depends(admin)):
    try:
        ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Unknown timezone")
    row = Team(**data.model_dump())
    db.add(row)
    db.flush()
    audit(db, user, "team_created", row)
    save(db)
    return public(row)


@router.post("/teams/{team_id}/status")
def team_state(team_id:int,data:s.TeamState,db:Session=Depends(get_db),user:User=Depends(admin)):
    row=db.get(Team,team_id)
    if not row:
        raise HTTPException(404,"Team not found")
    row.status=data.status
    if data.status=="suspended":
        users=[u.id for u in db.query(User).filter_by(team_id=team_id)]
        db.query(LoginSession).filter(LoginSession.user_id.in_(users)).delete(synchronize_session=False)
    audit(db,user,"team_"+data.status,row);save(db)
    return public(row)


def add_employee(data, team_id, db, actor):
    if data.location_id:
        location = db.get(WorkLocation, data.location_id)
        if not location or location.team_id != team_id or not location.active:
            raise HTTPException(422, "Invalid employee location")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(409, "Username already exists")
    row = User(team_id=team_id, username=data.username, name=data.name, role=data.role,
               password_hash=ph.hash(data.password), must_change_password=True)
    db.add(row)
    db.flush()
    db.add(EmployeeProfile(user_id=row.id, team_id=team_id, location_id=data.location_id,
                          department=data.department, job_title=data.job_title, joined_on=data.joined_on))
    audit(db, actor, "employee_created", row)
    save(db)
    return public(row, USER_FIELDS)


@router.post("/teams/{team_id}/leads", status_code=201)
def create_lead(team_id: int, data: s.EmployeeInput, db: Session = Depends(get_db), user: User = Depends(admin)):
    if not db.get(Team, team_id):
        raise HTTPException(404, "Team not found")
    if data.role != "lead":
        raise HTTPException(422, "Role must be lead")
    return add_employee(data, team_id, db, user)


@router.get("/employees")
def employees(db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    rows = db.query(User).filter(User.team_id == user.team_id).order_by(User.id).limit(200).all()
    return [public(row, USER_FIELDS) for row in rows]


@router.post("/employees", status_code=201)
def create_employee(data: s.EmployeeInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    if data.role != "member":
        raise HTTPException(403, "Leads can create members only")
    return add_employee(data, user.team_id, db, user)


@router.get("/tasks")
def tasks(offset: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    query = db.query(Task).filter(Task.team_id == user.team_id)
    if user.role == "member":
        query = query.filter(Task.assignee_id == user.id)
    from .models.work import IssueDetail
    result=[]
    for task in query.order_by(Task.id.desc()).offset(max(offset,0)).limit(200):
        detail=db.get(IssueDetail,task.id)
        result.append({**public(task),"issue_key":detail.issue_key if detail else None})
    return result


@router.post("/tasks", status_code=201)
def create_task(data: s.TaskInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    assignee = scoped(db, User, data.assignee_id, user)
    if assignee.role != "member" or not assignee.active:
        raise HTTPException(422, "Assignee must be an active team member")
    row = Task(**data.model_dump(), team_id=user.team_id, created_by=user.id, status="assigned")
    db.add(row)
    db.flush()
    db.add(TaskEvent(team_id=user.team_id, task_id=row.id, actor_id=user.id, to_status="assigned"))
    notify(db, assignee, "task_assigned", row.id)
    audit(db, user, "task_created", row)
    save(db)
    return public(row)


@router.patch("/tasks/{task_id}/status")
def transition(task_id: int, data: s.Transition, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = scoped(db, Task, task_id, user)
    from .models.work import IssueDetail, Project, IssueLink
    detail=db.get(IssueDetail,task_id)
    if detail:
        db.query(Project).filter_by(id=detail.project_id).with_for_update().first()
    db.query(Task).filter_by(id=task_id).with_for_update().first()
    db.refresh(row)
    if user.role != "lead" and row.assignee_id != user.id:
        raise HTTPException(403, "Only assignee or lead may update task")
    allowed = {"assigned": {"in_progress", "blocked"}, "in_progress": {"blocked", "done"},
               "blocked": {"in_progress", "assigned"}, "done": {"assigned"}}
    if data.status not in allowed.get(row.status, set()) or (data.status == "blocked" and not data.note):
        raise HTTPException(422, "Invalid transition or missing blocking reason")
    if data.status == "done":
        for link in db.query(IssueLink).filter_by(target_id=task_id,kind="blocks",team_id=user.team_id):
            if db.get(Task,link.source_id).status != "done":
                raise HTTPException(409,"Complete blocking dependencies first")
        for child in db.query(IssueDetail).filter_by(parent_id=task_id,team_id=user.team_id):
            if db.get(Task,child.task_id).status != "done":
                raise HTTPException(409,"Complete child issues first")
    db.add(TaskEvent(team_id=user.team_id, task_id=row.id, actor_id=user.id, from_status=row.status,
                     to_status=data.status, note=data.note))
    row.status = data.status
    if data.status == "blocked":
        for lead in db.query(User).filter_by(team_id=user.team_id, role="lead", active=True):
            notify(db, lead, "task_blocked", row.id)
    audit(db, user, "task_status_changed", row)
    save(db)
    return public(row)


@router.get("/locations")
def locations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    return [public(row) for row in db.query(WorkLocation).filter_by(team_id=user.team_id, active=True).limit(200)]


@router.post("/locations", status_code=201)
def create_location(data: s.LocationInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = WorkLocation(team_id=user.team_id, created_by=user.id, **data.model_dump(exclude={"accuracy"}))
    db.add(row)
    db.flush()
    audit(db, user, "location_created", row)
    save(db)
    return public(row)


@router.get("/holidays")
def holidays(db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    query = db.query(LocationHoliday).filter_by(team_id=user.team_id)
    if user.role == "member":
        profile = db.get(EmployeeProfile, user.id)
        query = query.filter(LocationHoliday.location_id == (profile.location_id if profile else -1))
    return [public(row) for row in query.order_by(LocationHoliday.date).limit(200)]


@router.post("/holidays", status_code=201)
def create_holiday(data: s.HolidayInput, db: Session = Depends(get_db), user: User = Depends(manager)):
    scoped(db, WorkLocation, data.location_id, user)
    row = LocationHoliday(team_id=user.team_id, **data.model_dump())
    db.add(row)
    save(db)
    audit(db, user, "holiday_created", row)
    save(db)
    return public(row)


@router.get("/attendance")
def attendance(db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    query = db.query(Attendance).filter_by(team_id=user.team_id)
    if user.role == "member":
        query = query.filter_by(user_id=user.id)
    from .services.attendance import effective_times
    return [{**public(row),**effective_times(db,row)} for row in query.order_by(Attendance.work_date.desc()).limit(200)]


@router.post("/attendance/{action}")
def clock(action: str, data: s.Coordinates, db: Session = Depends(get_db), user: User = Depends(current_user)):
    member(user)
    if action not in {"check-in", "check-out"}:
        raise HTTPException(404, "Unknown attendance action")
    location, distance = validate_location(db, user.team_id, data.lat, data.lng, data.accuracy)
    now = datetime.utcnow()
    team = db.get(Team, user.team_id)
    today = datetime.now(ZoneInfo(team.timezone)).date()
    if action == "check-in":
        if db.query(Attendance).filter_by(user_id=user.id, work_date=today).first():
            raise HTTPException(409, "Already checked in on this work date")
        if db.query(Attendance).filter_by(user_id=user.id, check_out_at=None).first():
            raise HTTPException(409, "Close your previous attendance first")
        row = Attendance(team_id=user.team_id, user_id=user.id, work_date=today, check_in_at=now,
                         check_in_lat=data.lat, check_in_lng=data.lng, check_in_accuracy_m=data.accuracy,
                         check_in_location_id=location, check_in_distance_m=distance)
        db.add(row)
        db.flush()
    else:
        row = db.query(Attendance).filter_by(user_id=user.id, team_id=user.team_id, check_out_at=None).with_for_update().first()
        if not row:
            raise HTTPException(409, "No open check-in")
        row.check_out_at = now
        row.check_out_lat, row.check_out_lng = data.lat, data.lng
        row.check_out_accuracy_m = data.accuracy
        row.check_out_location_id, row.check_out_distance_m = location, distance
    audit(db, user, action, row)
    save(db)
    return public(row)


@router.get("/leave")
def leaves(db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    query = db.query(LeaveRequest).filter_by(team_id=user.team_id)
    if user.role == "member":
        query = query.filter_by(user_id=user.id)
    from .models.leave import LeaveCharge, LeaveApproval, LeaveAccount, LeavePolicy
    result=[]
    for row in query.order_by(LeaveRequest.id.desc()).limit(200):
        charge=db.get(LeaveCharge,row.id)
        result.append({**public(row),"chargeable_days":charge.days if charge else None,
                       "approval_count":db.query(LeaveApproval).filter_by(leave_id=row.id).count()})
    return result


@router.post("/leave", status_code=201)
def request_leave(data: s.LeaveInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    member(user)
    # Lock the employee to serialize concurrent submissions on PostgreSQL.
    db.query(User).filter_by(id=user.id).with_for_update().first()
    overlap = db.query(LeaveRequest).filter(LeaveRequest.user_id == user.id,
        LeaveRequest.status.in_(["pending", "approved"]), LeaveRequest.start_date <= data.end_date,
        LeaveRequest.end_date >= data.start_date).first()
    if overlap:
        raise HTTPException(409, "Leave overlaps an existing request")
    from .models.leave import LeavePolicy
    if data.policy_id is None and db.query(LeavePolicy).filter_by(team_id=user.team_id, active=True).first():
        raise HTTPException(422, "Choose a leave policy")
    if data.duration == "half" and data.policy_id is None:
        raise HTTPException(422,"Half-day leave requires a policy")
    row = LeaveRequest(team_id=user.team_id, user_id=user.id, **data.model_dump(exclude={"policy_id", "duration"}))
    db.add(row)
    db.flush()
    if data.policy_id is not None:
        from .services.leave import reserve
        reserve(db, user, row, data.policy_id, data.duration)
    for lead in db.query(User).filter_by(team_id=user.team_id, role="lead", active=True):
        notify(db, lead, "leave_requested", row.id)
    audit(db, user, "leave_requested", row)
    save(db)
    return public(row)


@router.post("/leave/{leave_id}/decision")
def decide_leave(leave_id: int, data: s.Decision, db: Session = Depends(get_db), user: User = Depends(manager)):
    row = db.query(LeaveRequest).filter_by(id=leave_id, team_id=user.team_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Leave not found")
    if row.user_id == user.id:
        raise HTTPException(403, "Cannot approve your own leave")
    if row.status != "pending":
        raise HTTPException(409, "Leave already decided")
    from .models.leave import LeaveCharge, LeaveAccount, LeavePolicy, LeaveApproval
    if data.status == "approved":
        if db.query(LeaveApproval).filter_by(leave_id=row.id,actor_id=user.id).first():
            raise HTTPException(409,"You have already approved this request")
        db.add(LeaveApproval(team_id=user.team_id,leave_id=row.id,actor_id=user.id,note=data.note))
        db.flush()
        charge=db.get(LeaveCharge,row.id)
        required=1
        if charge:
            required=db.get(LeavePolicy,db.get(LeaveAccount,charge.account_id).policy_id).approval_steps
        count=db.query(LeaveApproval).filter_by(leave_id=row.id).count()
        if count < required:
            audit(db,user,"leave_approval_step",row); save(db)
            return {**public(row),"approval_count":count,"required_approvals":required}
    row.status, row.decision_note = data.status, data.note
    row.decided_by, row.decided_at = user.id, datetime.utcnow()
    if data.status == "rejected":
        from .services.leave import refund
        refund(db, row)
    notify(db, db.get(User, row.user_id), "leave_decided", row.id)
    audit(db, user, "leave_decided", row)
    save(db)
    return public(row)


@router.get("/calendar")
def calendar(start: date, end: date, user_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    team_user(user)
    target = user.id if user_id is None else user_id
    if user.role != "lead" and target != user.id:
        raise HTTPException(403, "Cannot view another employee's calendar")
    scoped(db, User, target, user)
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Calendar range must be ordered and at most 367 days")
    team = db.get(Team, user.team_id)
    profile = db.get(EmployeeProfile, target)
    holiday_dates = {h.date for h in db.query(Holiday).filter_by(team_id=user.team_id)}
    if profile and profile.location_id:
        holiday_dates |= {h.date for h in db.query(LocationHoliday).filter_by(team_id=user.team_id, location_id=profile.location_id)}
    present = {a.work_date for a in db.query(Attendance).filter(Attendance.user_id == target, Attendance.work_date.between(start, end))}
    approved = db.query(LeaveRequest).filter_by(user_id=target, status="approved").all()
    result = []
    day = start
    today = datetime.now(ZoneInfo(team.timezone)).date()
    while day <= end:
        state = "absent" if day <= today else "scheduled"
        if str(day.isoweekday()) not in team.work_days.split(","):
            state = "weekly_off"
        if day in holiday_dates:
            state = "holiday"
        if any(l.start_date <= day <= l.end_date for l in approved):
            state = "leave"
        if day in present:
            state = "present"
        result.append({"date": day, "status": state})
        day += timedelta(days=1)
    return result


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [public(row) for row in db.query(Notification).filter_by(team_id=user.team_id, user_id=user.id).order_by(Notification.id.desc()).limit(100)]
