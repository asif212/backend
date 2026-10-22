from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from my_time.config import settings


def test_empty_database_full_upgrade_and_downgrade(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    config=Config('alembic.ini')
    command.upgrade(config,'head')
    engine=create_engine(url)
    assert {'issue_details','leave_ledger','leave_approvals','attendance_corrections'}.issubset(inspect(engine).get_table_names())
    command.check(config)
    command.downgrade(config,'base')
    assert set(inspect(engine).get_table_names())=={'alembic_version'}
    engine.dispose()


def test_policy_migration_preserves_existing_rows_and_boolean_defaults(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path / 'existing.db'}"
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    config=Config('alembic.ini')
    command.upgrade(config,'cc6e713e7f2c')
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO teams (id,name) VALUES (1,'Original')"))
        conn.execute(text("INSERT INTO leave_policies (id,team_id,name,annual_days,accrual,active) VALUES (1,1,'Annual',12,'annual',1)"))
    command.upgrade(config,'head')
    with engine.connect() as conn:
        row=conn.execute(text('SELECT name,annual_days,approval_steps,prorate_joiners,allow_half_day FROM leave_policies')).one()
        assert row==('Annual',12,1,0,1)
    command.check(config)
    engine.dispose()


def test_project_planning_upgrade_backfills_existing_assignees_and_preserves_references(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path / 'planning.db'}"
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    config=Config('alembic.ini')
    command.upgrade(config,'0ec8ef2dd776')
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO teams (id,name) VALUES (1,'Team')"))
        conn.execute(text("INSERT INTO users (id,team_id,username,name,role,active) VALUES (2,1,'member','Member','member',1)"))
        for pid in (1,2):
            conn.execute(text("INSERT INTO projects (id,team_id,key,name,description,next_number,status) VALUES (:id,1,:key,'Original','',2,'active')"),{'id':pid,'key':f'PR{pid}'})
            conn.execute(text("INSERT INTO tasks (id,team_id,title,assignee_id,estimate_minutes,status) VALUES (:id,1,'Original',2,60,'assigned')"),{'id':pid})
            conn.execute(text("INSERT INTO issue_details (task_id,team_id,project_id,number,issue_key,kind,priority,story_points,labels) VALUES (:id,1,:id,1,:key,'task','medium',0,'[]')"),{'id':pid,'key':f'PR{pid}-1'})
        conn.execute(text("INSERT INTO sprints (id,team_id,project_id,name,goal,start_date,end_date,status) VALUES (1,1,1,'Sprint','','2026-10-01','2026-10-15','planned')"))
    command.upgrade(config,'head')
    command.check(config)
    with engine.connect() as conn:
        rows=conn.execute(text('SELECT user_id,allocation_percent FROM project_members ORDER BY project_id')).all()
        assert rows==[(2,50),(2,50)]
        assert conn.execute(text('SELECT currency,cost,planned_date FROM projects WHERE id=1')).one()==('INR',None,None)
        assert conn.execute(text('SELECT COUNT(*) FROM sprints')).scalar()==1
    command.downgrade(config,'0ec8ef2dd776')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM projects')).scalar()==2
        assert conn.execute(text('SELECT COUNT(*) FROM issue_details')).scalar()==2
    engine.dispose()
