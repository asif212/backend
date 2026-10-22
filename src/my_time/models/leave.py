from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, DateTime, UniqueConstraint, Boolean, Index, text
from ..db import Base


class LeavePolicy(Base):
    __tablename__="leave_policies"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    name=Column(String(120),nullable=False)
    annual_days=Column(Numeric(7,2),nullable=False)
    accrual=Column(String(20),nullable=False,default="annual")
    location_id=Column(Integer,ForeignKey("work_locations.id"),nullable=True)
    active=Column(Boolean,nullable=False,default=True)
    approval_steps=Column(Integer,nullable=False,default=1,server_default="1")
    carry_forward_days=Column(Numeric(7,2),nullable=False,default=0,server_default="0")
    waiting_days=Column(Integer,nullable=False,default=0,server_default="0")
    prorate_joiners=Column(Boolean,nullable=False,default=False,server_default=text("false"))
    allow_half_day=Column(Boolean,nullable=False,default=True,server_default=text("true"))
    __table_args__=(UniqueConstraint("team_id","name",name="uq_leave_policy_team_name"),)


class LeaveAccount(Base):
    __tablename__="leave_accounts"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    policy_id=Column(Integer,ForeignKey("leave_policies.id"),nullable=False)
    user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    year=Column(Integer,nullable=False)
    __table_args__=(UniqueConstraint("policy_id","user_id","year",name="uq_leave_account_year"),)


class LeaveLedger(Base):
    __tablename__="leave_ledger"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    account_id=Column(Integer,ForeignKey("leave_accounts.id"),nullable=False)
    leave_id=Column(Integer,ForeignKey("leave_requests.id"),nullable=True)
    amount=Column(Numeric(7,2),nullable=False)
    kind=Column(String(20),nullable=False)
    entry_key=Column(String(120),nullable=False,unique=True)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)


class LeaveCharge(Base):
    __tablename__="leave_charges"
    leave_id=Column(Integer,ForeignKey("leave_requests.id"),primary_key=True)
    account_id=Column(Integer,ForeignKey("leave_accounts.id"),nullable=False)
    days=Column(Numeric(7,2),nullable=False)


class CorrectionRequest(Base):
    __tablename__="attendance_corrections"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    attendance_id=Column(Integer,ForeignKey("attendance.id"),nullable=False)
    check_in_at=Column(DateTime,nullable=False)
    check_out_at=Column(DateTime,nullable=False)
    reason=Column(String(2000),nullable=False)
    status=Column(String(20),nullable=False,default="pending")
    decided_by=Column(Integer,ForeignKey("users.id"),nullable=True)
    decided_at=Column(DateTime,nullable=True)
    __table_args__=(Index("uq_pending_correction_attendance","attendance_id",unique=True,sqlite_where=text("status = 'pending'"),postgresql_where=text("status = 'pending'")),)


class LeaveApproval(Base):
    __tablename__="leave_approvals"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    leave_id=Column(Integer,ForeignKey("leave_requests.id"),nullable=False)
    actor_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    note=Column(String(2000),nullable=False,default="")
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
    __table_args__=(UniqueConstraint("leave_id","actor_id",name="uq_leave_approval_actor"),)
