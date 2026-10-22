from datetime import date, datetime, time, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from my_time.main import app
from my_time.db import Base, get_db
from my_time.auth import ph, digest
from my_time.models.core import User, Team, Task, Attendance, Session as LoginSession, AuditLog
from my_time.models.hr import EmployeeProfile, LocationHoliday
from my_time.jobs.scheduler import auto_checkout


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    with factory() as db:
        db.add_all([Team(id=1, name="A", timezone="Asia/Kolkata", work_start=time(9), work_end=time(18)), Team(id=2, name="B")])
        for id, username, role, team in [(1,"lead","lead",1),(2,"member","member",1),(3,"other","member",2),(4,"admin","super_admin",None)]:
            db.add(User(id=id, username=username, name=username, role=role, team_id=team,
                        password_hash=ph.hash("test-password-123"), must_change_password=False))
        db.commit()
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def auth(client, username):
    response = client.post("/api/v1/auth/login", json={"username":username,"password":"test-password-123"})
    assert response.status_code == 200, response.text
    return {"Authorization":"Bearer " + response.json()["access_token"]}


def test_auth_hash_logout_and_suspension(env):
    client, factory = env
    headers = auth(client, "member")
    token = headers["Authorization"].split()[1]
    with factory() as db:
        assert db.get(LoginSession, token) is None
        assert db.get(LoginSession, digest(token)) is not None
        db.get(Team, 1).status = "suspended"
        db.commit()
    assert client.get("/api/v1/tasks", headers=headers).status_code == 403
    with factory() as db:
        db.get(Team, 1).status = "active"
        db.commit()
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_task_isolation_and_history(env):
    client, factory = env
    lead, member, other = auth(client,"lead"), auth(client,"member"), auth(client,"other")
    data = {"title":"A task","assignee_id":3,"estimate_minutes":60}
    assert client.post("/api/v1/tasks", headers=lead, json=data).status_code == 404
    data["assignee_id"] = 2
    response = client.post("/api/v1/tasks", headers=lead, json=data)
    assert response.status_code == 201
    id = response.json()["id"]
    assert client.get("/api/v1/tasks", headers=other).json() == []
    url = f"/api/v1/tasks/{id}/status"
    assert client.patch(url, headers=other, json={"status":"in_progress"}).status_code == 404
    assert client.patch(url, headers=member, json={"status":"done"}).status_code == 422
    assert client.patch(url, headers=member, json={"status":"blocked"}).status_code == 422
    assert client.patch(url, headers=member, json={"status":"in_progress"}).status_code == 200
    assert client.patch(url, headers=member, json={"status":"done"}).status_code == 200
    assert client.post("/api/v1/tasks", headers=member, json=data).status_code == 403


def test_leave_validation_approval_and_notifications(env):
    client, _ = env
    lead, member, other = auth(client,"lead"), auth(client,"member"), auth(client,"other")
    data = {"start_date":"2026-10-20","end_date":"2026-10-22","reason":"Family"}
    assert client.post("/api/v1/leave", headers=member, json={**data,"end_date":"2026-10-19"}).status_code == 422
    response = client.post("/api/v1/leave", headers=member, json=data)
    assert response.status_code == 201
    id = response.json()["id"]
    assert client.post("/api/v1/leave", headers=member, json=data).status_code == 409
    assert client.get("/api/v1/leave", headers=other).json() == []
    url = f"/api/v1/leave/{id}/decision"
    assert client.post(url, headers=member, json={"status":"approved"}).status_code == 403
    assert client.post(url, headers=lead, json={"status":"anything"}).status_code == 422
    assert client.post(url, headers=lead, json={"status":"approved"}).status_code == 200
    assert client.post(url, headers=lead, json={"status":"rejected"}).status_code == 409
    assert client.get("/api/v1/notifications", headers=other).json() == []
    assert client.get("/api/v1/notifications", headers=member).json()[0]["type"] == "leave_decided"


def test_attendance_geofence_and_location_holiday(env):
    client, factory = env
    lead, member = auth(client,"lead"), auth(client,"member")
    coords = {"lat":12.9716,"lng":77.5946,"accuracy":10}
    assert client.post("/api/v1/attendance/check-in", headers=member, json=coords).status_code == 400
    response = client.post("/api/v1/locations", headers=lead, json={**coords,"name":"Bengaluru"})
    assert response.status_code == 201
    location = response.json()["id"]
    with factory() as db:
        db.add(EmployeeProfile(user_id=2, team_id=1, location_id=location))
        db.commit()
    assert client.post("/api/v1/holidays", headers=lead, json={"location_id":location,"name":"Office holiday","date":"2026-10-22"}).status_code == 201
    assert len(client.get("/api/v1/holidays", headers=member).json()) == 1
    assert client.get("/api/v1/calendar?start=2026-10-22&end=2026-10-22", headers=member).json()[0]["status"] == "holiday"
    assert client.post("/api/v1/attendance/check-in", headers=member, json={**coords,"lat":0}).status_code == 400
    assert client.post("/api/v1/attendance/check-in", headers=member, json={**coords,"accuracy":-1}).status_code == 422
    assert client.post("/api/v1/attendance/check-in", headers=member, json=coords).status_code == 200
    assert client.post("/api/v1/attendance/check-in", headers=member, json=coords).status_code == 409
    assert client.post("/api/v1/attendance/check-out", headers=member, json=coords).status_code == 200
    assert client.post("/api/v1/attendance/check-out", headers=member, json=coords).status_code == 409


def test_forced_password_change_and_revocation(env):
    client, factory = env
    with factory() as db:
        db.get(User,2).must_change_password = True
        db.commit()
    headers = auth(client,"member")
    assert client.get("/api/v1/tasks", headers=headers).status_code == 403
    assert client.post("/api/v1/auth/password", headers=headers, json={"current_password":"test-password-123","new_password":"new-password-123"}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_auto_checkout_timezone_overnight_and_idempotency(env):
    _, factory = env
    with factory() as db:
        row = Attendance(team_id=1,user_id=2,work_date=date(2026,10,22),check_in_at=datetime(2026,10,22,4))
        db.add(row); db.commit()
        auto_checkout(db,datetime(2026,10,22,14,29))
        assert row.check_out_at is None
        auto_checkout(db,datetime(2026,10,22,14,30))
        assert row.auto_closed and row.check_out_at == datetime(2026,10,22,14,30)
        auto_checkout(db,datetime(2026,10,22,15))
        assert db.query(AuditLog).filter_by(action="attendance_auto_closed").count() == 1
        team = db.get(Team,1); team.work_start=time(22); team.work_end=time(6)
        row2 = Attendance(team_id=1,user_id=2,work_date=date(2026,10,23),check_in_at=datetime(2026,10,23,16,30))
        db.add(row2); db.commit()
        auto_checkout(db,datetime(2026,10,24,2,29))
        assert row2.check_out_at is None
        auto_checkout(db,datetime(2026,10,24,2,30))
        assert row2.auto_closed


def test_admin_cannot_read_team_data(env):
    client, _ = env
    headers = auth(client,"admin")
    assert client.get("/api/v1/tasks",headers=headers).status_code == 403
    assert client.get("/api/v1/teams",headers=headers).status_code == 200
    assert client.get("/api/v1/tasks").status_code == 401
