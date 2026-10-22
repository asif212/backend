import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, JSON, Time, Date, UniqueConstraint
from sqlalchemy.orm import relationship
from ..db import Base

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    timezone = Column(String, default="UTC")
    work_days = Column(String, default="1,2,3,4,5") # 1=Mon, 7=Sun
    work_start = Column(Time)
    work_end = Column(Time)
    status = Column(String, default="active") # active | suspended
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    date = Column(Date)
    name = Column(String)

class WorkLocation(Base):
    __tablename__ = "work_locations"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    name = Column(String)
    lat = Column(Float)
    lng = Column(Float)
    active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True) # NULL only for super_admin
    username = Column(String, unique=True, index=True)
    name = Column(String)
    password_hash = Column(String)
    role = Column(String) # super_admin | lead | member
    active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Session(Base):
    __tablename__ = "sessions"
    id_hash = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime)
    ip = Column(String)
    user_agent_hash = Column(String)

class Attendance(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    work_date = Column(Date)
    
    check_in_at = Column(DateTime)
    check_in_lat = Column(Float, nullable=True)
    check_in_lng = Column(Float, nullable=True)
    check_in_accuracy_m = Column(Float, nullable=True)
    check_in_location_id = Column(Integer, ForeignKey("work_locations.id"), nullable=True)
    check_in_distance_m = Column(Float, nullable=True)
    
    check_out_at = Column(DateTime, nullable=True)
    check_out_lat = Column(Float, nullable=True)
    check_out_lng = Column(Float, nullable=True)
    check_out_accuracy_m = Column(Float, nullable=True)
    check_out_location_id = Column(Integer, ForeignKey("work_locations.id"), nullable=True)
    check_out_distance_m = Column(Float, nullable=True)
    
    auto_closed = Column(Boolean, default=False)
    flags = Column(String, nullable=True)
    
    __table_args__ = (UniqueConstraint('user_id', 'work_date', name='uq_attendance_user_date'),)

class AttendanceAdjustment(Base):
    __tablename__ = "attendance_adjustments"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    attendance_id = Column(Integer, ForeignKey("attendance.id"))
    adjusted_by = Column(Integer, ForeignKey("users.id"))
    field = Column(String)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    start_date = Column(Date)
    end_date = Column(Date)
    reason = Column(String)
    status = Column(String, default="pending") # pending | approved | rejected
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(String, nullable=True)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    title = Column(String)
    description = Column(String, nullable=True)
    assignee_id = Column(Integer, ForeignKey("users.id"))
    created_by = Column(Integer, ForeignKey("users.id"))
    due_date = Column(Date, nullable=True)
    estimate_minutes = Column(Integer)
    status = Column(String, default="assigned") # assigned | in_progress | blocked | done
    overrun_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class TaskEvent(Base):
    __tablename__ = "task_events"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    task_id = Column(Integer, ForeignKey("tasks.id"))
    from_status = Column(String, nullable=True)
    to_status = Column(String)
    note = Column(String, nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    type = Column(String)
    payload_json = Column(String) # Storing JSON string for simplicity
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String)
    target_type = Column(String)
    target_id = Column(Integer, nullable=True)
    ip = Column(String, nullable=True)
    detail_json = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class RateLimitState(Base):
    __tablename__ = "rate_limit_state"
    key = Column(String, primary_key=True, index=True)
    window_start = Column(DateTime)
    count = Column(Integer)
    locked_until = Column(DateTime, nullable=True)

