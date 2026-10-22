from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, Date, DateTime, JSON, UniqueConstraint, CheckConstraint, LargeBinary, Index, text, Numeric, Boolean
from ..db import Base


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    key = Column(String(12), nullable=False)
    name = Column(String(160), nullable=False)
    description = Column(String(10000), nullable=False, default="")
    next_number = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="active")
    owner_id = Column(Integer, ForeignKey("users.id", name="fk_projects_owner_id"), nullable=True)
    cost = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="INR", server_default="INR")
    estimate_minutes = Column(Integer, nullable=True)
    planned_date = Column(Date, nullable=True)
    release_date = Column(Date, nullable=True)
    __table_args__ = (UniqueConstraint("team_id", "key", name="uq_project_team_key"),)


class Sprint(Base):
    __tablename__ = "sprints"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(160), nullable=False)
    goal = Column(String(2000), nullable=False, default="")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="planned")
    completed_at = Column(DateTime, nullable=True)
    snapshot = Column(JSON, nullable=True)
    __table_args__ = (Index("uq_active_sprint_project", "project_id", unique=True,
                           sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),)


class IssueDetail(Base):
    __tablename__ = "issue_details"
    task_id = Column(Integer, ForeignKey("tasks.id"), primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    number = Column(Integer, nullable=False)
    issue_key = Column(String(32), nullable=False)
    sprint_id = Column(Integer, ForeignKey("sprints.id"), nullable=True)
    parent_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    kind = Column(String(20), nullable=False, default="task")
    priority = Column(String(20), nullable=False, default="medium")
    story_points = Column(Integer, nullable=False, default=0)
    labels = Column(JSON, nullable=False, default=list)
    cost = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="INR", server_default="INR")
    planned_date = Column(Date, nullable=True)
    release_date = Column(Date, nullable=True)
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_issue_project_number"),)


class Comment(Base):
    __tablename__ = "issue_comments"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(String(10000), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkLog(Base):
    __tablename__ = "work_logs"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    work_date = Column(Date, nullable=False)
    minutes = Column(Integer, nullable=False)
    note = Column(String(2000), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (CheckConstraint("minutes > 0 AND minutes <= 1440", name="ck_worklog_minutes"),)


class Watcher(Base):
    __tablename__="issue_watchers"
    task_id=Column(Integer,ForeignKey("tasks.id"),primary_key=True)
    user_id=Column(Integer,ForeignKey("users.id"),primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)


class IssueLink(Base):
    __tablename__="issue_links"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    source_id=Column(Integer,ForeignKey("tasks.id"),nullable=False)
    target_id=Column(Integer,ForeignKey("tasks.id"),nullable=False)
    kind=Column(String(20),nullable=False)
    __table_args__=(UniqueConstraint("source_id","target_id","kind",name="uq_issue_link"),CheckConstraint("source_id != target_id",name="ck_no_self_link"))


class Attachment(Base):
    __tablename__="issue_attachments"
    id=Column(Integer,primary_key=True)
    team_id=Column(Integer,ForeignKey("teams.id"),nullable=False,index=True)
    task_id=Column(Integer,ForeignKey("tasks.id"),nullable=False)
    author_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    filename=Column(String(200),nullable=False)
    size=Column(Integer,nullable=False)
    content=Column(LargeBinary,nullable=False)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)


class ProjectMember(Base):
    __tablename__ = "project_members"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    allocation_percent = Column(Numeric(5, 2), nullable=False, default=100)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        CheckConstraint("allocation_percent > 0 AND allocation_percent <= 100", name="ck_project_allocation"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_project_member_dates"),
    )
