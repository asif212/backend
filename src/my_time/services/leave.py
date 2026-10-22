from datetime import timedelta, date
from decimal import Decimal, ROUND_DOWN
from fastapi import HTTPException
from sqlalchemy import func
from ..models.core import Team, Holiday
from ..models.hr import EmployeeProfile, LocationHoliday
from ..models.leave import LeavePolicy, LeaveAccount, LeaveLedger, LeaveCharge


def available(db,account_id):
    return Decimal(db.query(func.coalesce(func.sum(LeaveLedger.amount),0)).filter_by(account_id=account_id).scalar())


def eligible(db,policy,user_id):
    profile=db.get(EmployeeProfile,user_id)
    if not policy.active or (policy.location_id is not None and (not profile or profile.location_id!=policy.location_id)):
        raise HTTPException(422,"Leave policy does not apply to this employee's office")


def accrue(db,account,today):
    policy=db.get(LeavePolicy,account.policy_id)
    if not policy.active or account.year!=today.year:
        return
    profile=db.get(EmployeeProfile,account.user_id)
    if policy.location_id is not None and (not profile or profile.location_id != policy.location_id):
        return
    if profile and profile.joined_on and profile.joined_on>today:
        return
    # Serialize accrual with reservations/refunds using the account lock.
    db.query(LeaveAccount).filter_by(id=account.id).with_for_update().first()
    carry_key=f"carry:{account.id}"
    previous=db.query(LeaveAccount).filter_by(user_id=account.user_id,policy_id=account.policy_id,year=account.year-1).first()
    if previous and policy.carry_forward_days>0 and not db.query(LeaveLedger).filter_by(entry_key=carry_key).first():
        db.query(LeaveAccount).filter_by(id=previous.id).with_for_update().first()
        amount=min(max(available(db,previous.id),Decimal('0')),policy.carry_forward_days)
        db.add(LeaveLedger(team_id=account.team_id,account_id=previous.id,amount=-amount,kind="carry_transfer",entry_key=f"carry_out:{account.id}"))
        db.add(LeaveLedger(team_id=account.team_id,account_id=account.id,amount=amount,kind="carry_forward",entry_key=carry_key))
        db.flush()
    periods=[0] if policy.accrual=="annual" else list(range(1,today.month+1))
    for period in periods:
        if policy.prorate_joiners and profile and profile.joined_on and profile.joined_on.year==account.year and period and period<profile.joined_on.month:
            continue
        key=f"accrual:{account.id}:{period}"
        if db.query(LeaveLedger).filter_by(entry_key=key).first():
            continue
        amount=policy.annual_days
        if policy.prorate_joiners and policy.accrual=="annual" and profile and profile.joined_on and profile.joined_on.year==account.year:
            year_days=Decimal((date(account.year+1,1,1)-date(account.year,1,1)).days)
            remaining=Decimal((date(account.year+1,1,1)-profile.joined_on).days)
            amount=(amount*remaining/year_days).quantize(Decimal('0.01'),rounding=ROUND_DOWN)
        if policy.accrual=="monthly":
            regular=(policy.annual_days/12).quantize(Decimal("0.01"),rounding=ROUND_DOWN)
            amount=regular if period<12 else policy.annual_days-regular*11
        db.add(LeaveLedger(team_id=account.team_id,account_id=account.id,amount=amount,kind="accrual",entry_key=key))
        db.flush()


def working_days(db,user,start,end):
    team=db.get(Team,user.team_id)
    profile=db.get(EmployeeProfile,user.id)
    holidays={row.date for row in db.query(Holiday).filter_by(team_id=user.team_id)}
    if profile and profile.location_id:
        holidays|={row.date for row in db.query(LocationHoliday).filter_by(team_id=user.team_id,location_id=profile.location_id)}
    day=start; days=0
    while day<=end:
        if str(day.isoweekday()) in team.work_days.split(",") and day not in holidays:
            days+=1
        day+=timedelta(days=1)
    return Decimal(days)


def reserve(db,user,leave,policy_id,duration="full"):
    policy=db.get(LeavePolicy,policy_id)
    if not policy or policy.team_id!=user.team_id:
        raise HTTPException(404,"Leave policy not found")
    eligible(db,policy,user.id)
    profile=db.get(EmployeeProfile,user.id)
    if profile and profile.joined_on and leave.start_date<profile.joined_on+timedelta(days=policy.waiting_days):
        raise HTTPException(422,"Leave starts before the policy eligibility date")
    if policy.waiting_days and (not profile or not profile.joined_on):
        raise HTTPException(422,"Set the employee joining date before using this policy")
    if duration=="half" and not policy.allow_half_day:
        raise HTTPException(422,"This policy does not allow half-day leave")
    if leave.start_date.year!=leave.end_date.year:
        raise HTTPException(422,"Split leave spanning calendar years into separate requests")
    account=db.query(LeaveAccount).filter_by(user_id=user.id,policy_id=policy_id,year=leave.start_date.year).with_for_update().first()
    if not account:
        raise HTTPException(422,"Ask your lead to enroll you in this policy/year")
    days=working_days(db,user,leave.start_date,leave.end_date)
    if days<=0:
        raise HTTPException(422,"Leave has no chargeable working days")
    if duration=="half":
        days=Decimal('0.5')
    if available(db,account.id)<days:
        raise HTTPException(409,"Insufficient leave balance")
    db.add(LeaveCharge(leave_id=leave.id,account_id=account.id,days=days))
    db.add(LeaveLedger(team_id=user.team_id,account_id=account.id,leave_id=leave.id,amount=-days,kind="reservation",entry_key=f"reserve:{leave.id}"))


def refund(db,leave):
    charge=db.get(LeaveCharge,leave.id)
    if charge:
        db.query(LeaveAccount).filter_by(id=charge.account_id).with_for_update().first()
        key=f"refund:{leave.id}"
        if not db.query(LeaveLedger).filter_by(entry_key=key).first():
            db.add(LeaveLedger(team_id=leave.team_id,account_id=charge.account_id,leave_id=leave.id,amount=charge.days,kind="refund",entry_key=key))


def rollover_team(db,team_id,today):
    from ..models.core import User
    for previous in db.query(LeaveAccount).filter_by(team_id=team_id,year=today.year-1).order_by(LeaveAccount.id):
        user=db.query(User).filter_by(id=previous.user_id,active=True).with_for_update().first()
        policy=db.get(LeavePolicy,previous.policy_id)
        if not user or not policy.active:
            continue
        profile=db.get(EmployeeProfile,user.id)
        if policy.location_id is not None and (not profile or profile.location_id!=policy.location_id):
            continue
        if not db.query(LeaveAccount).filter_by(user_id=user.id,policy_id=policy.id,year=today.year).first():
            db.add(LeaveAccount(team_id=team_id,user_id=user.id,policy_id=policy.id,year=today.year))
            db.flush()
