import asyncio
import logging
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models.core import Attendance, Task, TaskEvent, Team
from ..config import settings

logger = logging.getLogger(__name__)

async def run_scheduler():
    logger.info("Scheduler started.")
    while True:
        try:
            await asyncio.sleep(60)
            db = SessionLocal()
            try:
                check_overruns(db)
                auto_checkout(db)
                accrue_leave(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Scheduler task cancelled.")
            break
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

def check_overruns(db: Session):
    now = datetime.utcnow()
    # 1. Fetch active tasks
    active_tasks = db.query(Task).filter(Task.status == 'in_progress').all()
    
    for task in active_tasks:
        if task.overrun_notified_at:
            continue
            
        # Get the day's attendance for the assignee
        # Note: assuming tasks span mostly the current day, or we iterate through all their attendances
        # For full accuracy, we fetch all attendances for the user and all in_progress events for the task
        attendances = db.query(Attendance).filter(Attendance.user_id == task.assignee_id).all()
        events = db.query(TaskEvent).filter(TaskEvent.task_id == task.id).order_by(TaskEvent.created_at.asc()).all()
        
        # Build task in-progress intervals
        task_intervals = []
        current_start = None
        for ev in events:
            if ev.to_status == 'in_progress':
                current_start = ev.created_at
            elif ev.from_status == 'in_progress' and current_start:
                task_intervals.append((current_start, ev.created_at))
                current_start = None
        if current_start:
            task_intervals.append((current_start, now))
            
        # Build attendance intervals
        att_intervals = []
        for att in attendances:
            from ..services.attendance import effective_times
            effective = effective_times(db,att)
            if effective["effective_check_in_at"]:
                end = effective["effective_check_out_at"] or now
                att_intervals.append((effective["effective_check_in_at"], end))
                
        # Calculate overlap
        worked_seconds = 0
        for t_start, t_end in task_intervals:
            for a_start, a_end in att_intervals:
                # Intersection of [t_start, t_end] and [a_start, a_end]
                latest_start = max(t_start, a_start)
                earliest_end = min(t_end, a_end)
                delta = (earliest_end - latest_start).total_seconds()
                if delta > 0:
                    worked_seconds += delta
                    
        # Check if overdue
        if task.estimate_minutes and worked_seconds > task.estimate_minutes * 60:
            # We would create a Notification here
            task.overrun_notified_at = now
            from ..models.core import Notification, User
            import json
            recipients = {task.assignee_id} | {u.id for u in db.query(User).filter_by(team_id=task.team_id, role="lead", active=True)}
            for user_id in recipients:
                if user_id:
                    db.add(Notification(team_id=task.team_id, user_id=user_id, type="task_overrun", payload_json=json.dumps({"id": task.id})))
            
    db.commit()


def accrue_leave(db: Session):
    from zoneinfo import ZoneInfo
    from ..models.leave import LeaveAccount
    from ..services.leave import accrue, rollover_team
    for team in db.query(Team).filter_by(status="active").order_by(Team.id):
        today = datetime.now(ZoneInfo(team.timezone)).date()
        rollover_team(db,team.id,today)
        for account in db.query(LeaveAccount).filter_by(team_id=team.id, year=today.year).order_by(LeaveAccount.id):
            accrue(db, account, today)
    db.commit()

def auto_checkout(db: Session, now=None):
    from datetime import timezone
    from zoneinfo import ZoneInfo
    from ..models.core import AuditLog
    now = now or datetime.utcnow()
    for att in db.query(Attendance).filter(Attendance.check_out_at.is_(None)).with_for_update().all():
        team = db.get(Team, att.team_id)
        if not team or not team.work_end or not att.check_in_at:
            continue
        zone = ZoneInfo(team.timezone)
        end_day = att.work_date
        if team.work_start and team.work_end <= team.work_start:
            end_day += timedelta(days=1)
        end_local = datetime.combine(end_day, team.work_end, tzinfo=zone)
        cutoff = end_local.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=settings.AUTO_CHECKOUT_GRACE_MINUTES)
        if att.check_in_at >= cutoff:
            cutoff = att.check_in_at + timedelta(minutes=settings.AUTO_CHECKOUT_GRACE_MINUTES)
        if now >= cutoff:
            att.check_out_at = now
            att.auto_closed = True
            db.add(AuditLog(team_id=att.team_id, action="attendance_auto_closed", target_type="attendance", target_id=att.id))
    db.commit()
