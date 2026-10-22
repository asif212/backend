from datetime import datetime, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from .db import get_db
from .auth import current_user, manager, admin
from .api import public, scoped, save, audit, team_user, member, notify
from .models.core import User, Team, Attendance, AttendanceAdjustment, LeaveRequest, Notification, AuditLog, Session as LoginSession, Task, WorkLocation
from .models.hr import EmployeeProfile, LocationHoliday
from .models.leave import LeavePolicy, LeaveAccount, LeaveLedger, CorrectionRequest
from .services.leave import accrue, available, eligible, refund, rollover_team
from .schemas import Decision
from . import hr_schemas as s

router=APIRouter(prefix="/api/v1",tags=["people and operations"])


@router.get("/leave-policies")
def policies(db:Session=Depends(get_db),user:User=Depends(current_user)):
    team_user(user)
    query=db.query(LeavePolicy).filter_by(team_id=user.team_id,active=True)
    if user.role=="member":
        profile=db.get(EmployeeProfile,user.id)
        query=query.filter((LeavePolicy.location_id.is_(None)) | (LeavePolicy.location_id==(profile.location_id if profile else -1)))
    return [public(row) for row in query.order_by(LeavePolicy.id).limit(200)]


@router.post("/leave-policies",status_code=201)
def create_policy(data:s.PolicyInput,db:Session=Depends(get_db),user:User=Depends(manager)):
    if data.location_id:
        scoped(db, WorkLocation,data.location_id,user)
    if db.query(LeavePolicy).filter_by(team_id=user.team_id,name=data.name).first():
        raise HTTPException(409,"Policy name already exists")
    row=LeavePolicy(team_id=user.team_id,**data.model_dump())
    db.add(row); db.flush(); audit(db,user,"leave_policy_created",row); save(db)
    return public(row)


@router.post("/leave-accounts",status_code=201)
def enroll(data:s.Enrollment,db:Session=Depends(get_db),user:User=Depends(manager)):
    employee=scoped(db,User,data.user_id,user)
    if employee.role!="member" or not employee.active:
        raise HTTPException(422,"Enroll active members only")
    policy=scoped(db,LeavePolicy,data.policy_id,user)
    eligible(db,policy,employee.id)
    if db.query(LeaveAccount).filter_by(user_id=employee.id,policy_id=policy.id,year=data.year).first():
        raise HTTPException(409,"Employee already enrolled for this year")
    row=LeaveAccount(team_id=user.team_id,**data.model_dump())
    db.add(row); db.flush()
    today=datetime.now(ZoneInfo(db.get(Team,user.team_id).timezone)).date()
    accrue(db,row,today)
    audit(db,user,"leave_enrolled",row); save(db)
    return {**public(row),"available_days":available(db,row.id)}


@router.get("/leave-accounts")
def accounts(db:Session=Depends(get_db),user:User=Depends(current_user)):
    team_user(user)
    query=db.query(LeaveAccount).filter_by(team_id=user.team_id)
    if user.role=="member":
        query=query.filter_by(user_id=user.id)
    return [{**public(row),"policy_name":db.get(LeavePolicy,row.policy_id).name,"available_days":available(db,row.id)} for row in query.order_by(LeaveAccount.id).limit(200)]


@router.get("/leave-accounts/{account_id}/ledger")
def ledger(account_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=scoped(db,LeaveAccount,account_id,user)
    if user.role!="lead" and row.user_id!=user.id:
        raise HTTPException(404,"Account not found")
    return [public(entry) for entry in db.query(LeaveLedger).filter_by(account_id=row.id).order_by(LeaveLedger.id).limit(500)]


@router.post("/leave-accruals/run")
def run_accruals(db:Session=Depends(get_db),user:User=Depends(manager)):
    today=datetime.now(ZoneInfo(db.get(Team,user.team_id).timezone)).date()
    rollover_team(db,user.team_id,today)
    for account in db.query(LeaveAccount).filter_by(team_id=user.team_id,year=today.year).order_by(LeaveAccount.id):
        accrue(db,account,today)
    audit(db,user,"leave_accrual_run",db.get(Team,user.team_id)); save(db)
    return {"status":"completed","through":today}


@router.post("/leave/{leave_id}/cancel")
def cancel_leave(leave_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=db.query(LeaveRequest).filter_by(id=leave_id,team_id=user.team_id).with_for_update().first()
    if not row or (user.role!="lead" and row.user_id!=user.id):
        raise HTTPException(404,"Leave not found")
    if row.status not in {"pending","approved"}:
        raise HTTPException(409,"Leave cannot be cancelled")
    today=datetime.now(ZoneInfo(db.get(Team,user.team_id).timezone)).date()
    if row.status=="approved" and row.start_date<=today:
        raise HTTPException(409,"Approved leave can only be cancelled before it starts")
    refund(db,row)
    row.status="cancelled"
    audit(db,user,"leave_cancelled",row); save(db)
    return public(row)


@router.get("/employees/{employee_id}/profile")
def profile(employee_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    employee=scoped(db,User,employee_id,user)
    if user.role!="lead" and user.id!=employee_id:
        raise HTTPException(403,"Private profile access denied")
    row=db.get(EmployeeProfile,employee_id)
    return {"user_id":employee_id,"name":employee.name,"active":employee.active,**(public(row) if row else {})}


@router.patch("/employees/{employee_id}/profile")
def edit_profile(employee_id:int,data:s.ProfileInput,db:Session=Depends(get_db),user:User=Depends(manager)):
    from .models.core import WorkLocation
    employee=scoped(db,User,employee_id,user)
    if employee.role!="member":
        raise HTTPException(403,"Only member profiles may be managed here")
    if data.location_id:
        scoped(db,WorkLocation,data.location_id,user)
    employee.name,employee.active=data.name,data.active
    row=db.get(EmployeeProfile,employee.id)
    if not row:
        row=EmployeeProfile(user_id=employee.id,team_id=user.team_id)
        db.add(row)
    for name in ("department","job_title","joined_on","location_id"):
        setattr(row,name,getattr(data,name))
    if not data.active:
        db.query(LoginSession).filter_by(user_id=employee.id).delete()
    audit(db,user,"employee_profile_updated",employee); save(db)
    return {"name":employee.name,"active":employee.active,**public(row)}


@router.get("/corrections")
def corrections(db:Session=Depends(get_db),user:User=Depends(current_user)):
    team_user(user)
    query=db.query(CorrectionRequest).filter_by(team_id=user.team_id)
    if user.role!="lead":
        query=query.filter_by(user_id=user.id)
    return [public(row) for row in query.order_by(CorrectionRequest.id.desc()).limit(200)]


@router.post("/corrections",status_code=201)
def request_correction(data:s.CorrectionInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    member(user)
    attendance=scoped(db,Attendance,data.attendance_id,user)
    if attendance.user_id!=user.id:
        raise HTTPException(404,"Attendance not found")
    if not attendance.check_out_at:
        raise HTTPException(409,"Check out before requesting correction")
    if db.query(CorrectionRequest).filter_by(attendance_id=attendance.id,status="pending").first():
        raise HTTPException(409,"Correction already pending")
    zone=ZoneInfo(db.get(Team,user.team_id).timezone)
    from datetime import timezone
    if data.check_in_at.replace(tzinfo=timezone.utc).astimezone(zone).date()!=attendance.work_date:
        raise HTTPException(422,"Corrected check-in must fall on the attendance work date")
    if data.check_out_at>datetime.utcnow():
        raise HTTPException(422,"Corrected times cannot be in the future")
    row=CorrectionRequest(team_id=user.team_id,user_id=user.id,**data.model_dump())
    db.add(row); db.flush(); audit(db,user,"attendance_correction_requested",row)
    for lead in db.query(User).filter_by(team_id=user.team_id,role="lead",active=True):
        notify(db,lead,"attendance_correction_requested",row.id)
    save(db)
    return public(row)


@router.post("/corrections/{correction_id}/decision")
def decide_correction(correction_id:int,data:Decision,db:Session=Depends(get_db),user:User=Depends(manager)):
    row=db.query(CorrectionRequest).filter_by(id=correction_id,team_id=user.team_id).with_for_update().first()
    if not row:
        raise HTTPException(404,"Correction not found")
    if row.status!="pending":
        raise HTTPException(409,"Correction already decided")
    attendance=scoped(db,Attendance,row.attendance_id,user)
    row.status=data.status; row.decided_by=user.id; row.decided_at=datetime.utcnow()
    if data.status=="approved":
        # Original attendance remains untouched. Append a correction overlay.
        for name in ("check_in_at","check_out_at"):
            db.add(AttendanceAdjustment(team_id=user.team_id,attendance_id=attendance.id,adjusted_by=user.id,
                field=name,old_value=str(getattr(attendance,name)),new_value=str(getattr(row,name)),reason=row.reason))
    audit(db,user,"attendance_correction_"+data.status,row)
    notify(db,db.get(User,row.user_id),"attendance_correction_decided",row.id); save(db)
    return public(row)


@router.get("/settings")
def settings(db:Session=Depends(get_db),user:User=Depends(manager)):
    return public(db.get(Team,user.team_id))


@router.patch("/settings")
def edit_settings(data:s.TeamSettings,db:Session=Depends(get_db),user:User=Depends(manager)):
    try:
        ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422,"Unknown timezone")
    team=db.get(Team,user.team_id)
    for key,value in data.model_dump().items():
        setattr(team,key,value)
    audit(db,user,"team_settings_changed",team); save(db)
    return public(team)


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=db.query(Notification).filter_by(id=notification_id,user_id=user.id,team_id=user.team_id).first()
    if not row:
        raise HTTPException(404,"Notification not found")
    row.read_at=row.read_at or datetime.utcnow(); save(db)
    return public(row)


@router.get("/audit")
def audit_entries(offset:int=Query(default=0,ge=0),db:Session=Depends(get_db),user:User=Depends(manager)):
    return [public(row) for row in db.query(AuditLog).filter_by(team_id=user.team_id).order_by(AuditLog.id.desc()).offset(offset).limit(200)]


@router.get("/reports")
def reports(start:date,end:date,db:Session=Depends(get_db),user:User=Depends(manager)):
    if end<start or (end-start).days>366:
        raise HTTPException(422,"Choose an ordered date range of at most 367 days")
    tasks=db.query(Task).filter_by(team_id=user.team_id).all()
    rows=db.query(Attendance).filter(Attendance.team_id==user.team_id,Attendance.work_date.between(start,end)).all()
    corrections={row.attendance_id:row for row in db.query(CorrectionRequest).filter_by(team_id=user.team_id,status="approved").order_by(CorrectionRequest.id)}
    attendance=[]
    for row in rows:
        corrected=corrections.get(row.id)
        begin=corrected.check_in_at if corrected else row.check_in_at
        finish=corrected.check_out_at if corrected else row.check_out_at
        attendance.append({"user_id":row.user_id,"work_date":row.work_date,"minutes":max(0,int((finish-begin).total_seconds()/60)) if begin and finish else None,"corrected":corrected is not None})
    return {"start":start,"end":end,"tasks_by_status":{state:sum(t.status==state for t in tasks) for state in ("assigned","in_progress","blocked","done")},
            "overdue_tasks":sum(t.status!="done" and t.due_date is not None and t.due_date<end for t in tasks),"attendance":attendance}
