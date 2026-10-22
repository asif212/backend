from datetime import date, datetime, timedelta
from decimal import Decimal
from test_api import env, auth
from my_time.models.core import Attendance, User, AttendanceAdjustment
from my_time.models.hr import EmployeeProfile
from my_time.models.work import Project, IssueDetail
from my_time.models.leave import LeaveLedger, LeaveAccount, LeavePolicy
from my_time.services.leave import accrue, available


def test_project_issue_sprint_lifecycle_and_isolation(env):
    client,_=env
    lead=auth(client,"lead"); member=auth(client,"member"); other=auth(client,"other")
    project=client.post('/api/v1/projects',headers=lead,json={"key":"APP","name":"App"})
    assert project.status_code==201,project.text
    pid=project.json()['id']
    assert client.post(f'/api/v1/projects/{pid}/members',headers=lead,json={'user_id':2}).status_code==200
    assert client.post('/api/v1/projects',headers=lead,json={"key":"APP","name":"Duplicate"}).status_code==409
    assert client.post('/api/v1/projects',headers=member,json={"key":"NO","name":"No"}).status_code==403
    assert client.get('/api/v1/projects',headers=other).json()==[]
    sprint=client.post('/api/v1/sprints',headers=lead,json={"project_id":pid,"name":"Sprint 1","start_date":"2026-10-01","end_date":"2026-10-15"})
    assert sprint.status_code==201,sprint.text
    sid=sprint.json()['id']
    payload={"project_id":pid,"title":"Implement","assignee_id":2,"estimate_minutes":60,"sprint_id":sid,"kind":"story","story_points":5}
    issue=client.post('/api/v1/issues',headers=lead,json=payload)
    assert issue.status_code==201,issue.text
    task_id=issue.json()['id']
    assert issue.json()['issue_key']=='APP-1'
    second=client.post('/api/v1/issues',headers=lead,json={**payload,"title":"Second"})
    assert second.json()['issue_key']=='APP-2'
    assert client.get('/api/v1/issues',headers=other).json()==[]
    assert client.get(f'/api/v1/issues/{task_id}',headers=other).status_code==404
    assert client.post(f'/api/v1/issues/{task_id}/comments',headers=member,json={"body":"Working on this"}).status_code==201
    assert client.post(f'/api/v1/issues/{task_id}/work-logs',headers=member,json={"work_date":"2026-10-01","minutes":60}).status_code==201
    assert client.post(f'/api/v1/issues/{task_id}/work-logs',headers=member,json={"work_date":"2026-10-01","minutes":1400}).status_code==422
    detail=client.get(f'/api/v1/issues/{task_id}',headers=member).json()
    assert len(detail['comments'])==1 and len(detail['events'])==1
    assert client.post(f'/api/v1/sprints/{sid}/status',headers=lead,json={"status":"active"}).status_code==200
    assert client.post(f'/api/v1/sprints/{sid}/status',headers=lead,json={"status":"completed"}).status_code==200
    completed=client.get('/api/v1/sprints',headers=lead).json()[0]
    assert len(completed['snapshot'])==2
    assert len(client.get('/api/v1/issues?backlog=true',headers=lead).json())==2
    assert client.post('/api/v1/issues',headers=lead,json=payload).status_code==422


def test_issue_parent_validation_and_sprint_project_boundary(env):
    client,_=env; lead=auth(client,'lead')
    p1=client.post('/api/v1/projects',headers=lead,json={"key":"AA","name":"One"}).json()['id']
    assert client.post(f'/api/v1/projects/{p1}/members',headers=lead,json={'user_id':2}).status_code==200
    p2=client.post('/api/v1/projects',headers=lead,json={"key":"BB","name":"Two"}).json()['id']
    sprint=client.post('/api/v1/sprints',headers=lead,json={"project_id":p2,"name":"Other","start_date":"2026-10-01","end_date":"2026-10-02"}).json()['id']
    payload={"project_id":p1,"title":"Child","assignee_id":2,"estimate_minutes":20}
    assert client.post('/api/v1/issues',headers=lead,json={**payload,"sprint_id":sprint}).status_code==422
    assert client.post('/api/v1/issues',headers=lead,json={**payload,"kind":"subtask"}).status_code==422
    parent=client.post('/api/v1/issues',headers=lead,json=payload).json()['id']
    assert client.post('/api/v1/issues',headers=lead,json={**payload,"kind":"subtask","parent_id":parent}).status_code==201


def test_leave_balance_reservation_rejection_and_cancellation(env):
    client,factory=env; lead=auth(client,'lead'); member=auth(client,'member'); other=auth(client,'other')
    policy=client.post('/api/v1/leave-policies',headers=lead,json={"name":"Annual","annual_days":"12","accrual":"annual"})
    assert policy.status_code==201,policy.text
    pid=policy.json()['id']
    # Accrual only credits the current calendar year; choose a working day in it.
    year=datetime.now().year
    account=client.post('/api/v1/leave-accounts',headers=lead,json={"user_id":2,"policy_id":pid,"year":year})
    assert account.status_code==201,account.text
    aid=account.json()['id']
    assert Decimal(str(account.json()['available_days']))==12
    assert client.post('/api/v1/leave-accruals/run',headers=lead).status_code==200
    assert client.post('/api/v1/leave-accruals/run',headers=lead).status_code==200
    with factory() as db:
        assert db.query(LeaveLedger).filter_by(account_id=aid,kind='accrual').count()==1
    day=date(year,1,1)
    while day.isoweekday()>5:day+=timedelta(days=1)
    payload={"policy_id":pid,"start_date":str(day),"end_date":str(day),"reason":"Rest"}
    leave=client.post('/api/v1/leave',headers=member,json=payload)
    assert leave.status_code==201,leave.text
    lid=leave.json()['id']
    assert Decimal(client.get('/api/v1/leave-accounts',headers=member).json()[0]['available_days'])==11
    assert client.get(f'/api/v1/leave-accounts/{aid}/ledger',headers=other).status_code==404
    assert client.post(f'/api/v1/leave/{lid}/decision',headers=lead,json={"status":"rejected"}).status_code==200
    assert Decimal(client.get('/api/v1/leave-accounts',headers=member).json()[0]['available_days'])==12
    again=client.post('/api/v1/leave',headers=member,json=payload).json()['id']
    assert client.post(f'/api/v1/leave/{again}/cancel',headers=member).status_code==200
    assert client.post(f'/api/v1/leave/{again}/cancel',headers=member).status_code==409
    assert Decimal(client.get('/api/v1/leave-accounts',headers=member).json()[0]['available_days'])==12


def test_monthly_accrual_exact_annual_total_and_repeat_safety(env):
    _,factory=env
    with factory() as db:
        policy=LeavePolicy(team_id=1,name='Monthly',annual_days=Decimal('10'),accrual='monthly')
        db.add(policy);db.flush()
        account=LeaveAccount(team_id=1,user_id=2,policy_id=policy.id,year=2026)
        db.add(account);db.flush()
        accrue(db,account,date(2026,3,1)); db.commit()
        assert available(db,account.id)==Decimal('2.49')
        accrue(db,account,date(2026,3,20)); db.commit()
        assert available(db,account.id)==Decimal('2.49')
        accrue(db,account,date(2026,12,1)); db.commit()
        assert available(db,account.id)==Decimal('10.00')


def test_employee_offboarding_and_profile_privacy(env):
    client,_=env; lead=auth(client,'lead'); member=auth(client,'member'); other=auth(client,'other')
    assert client.get('/api/v1/employees/1/profile',headers=member).status_code==403
    assert client.get('/api/v1/employees/2/profile',headers=other).status_code==404
    assert client.patch('/api/v1/employees/2/profile',headers=lead,json={"name":"Member","department":"Engineering","active":False}).status_code==200
    assert client.get('/api/v1/auth/me',headers=member).status_code==401


def test_correction_preserves_original_and_reports_effective_times(env):
    client,factory=env; lead=auth(client,'lead'); member=auth(client,'member')
    now=datetime.utcnow()-timedelta(days=2)
    start=now.replace(hour=4,minute=0,second=0,microsecond=0)
    with factory() as db:
        row=Attendance(team_id=1,user_id=2,work_date=start.date(),check_in_at=start,check_out_at=start+timedelta(hours=7))
        db.add(row);db.commit();aid=row.id
    response=client.post('/api/v1/corrections',headers=member,json={"attendance_id":aid,"check_in_at":start.isoformat(),"check_out_at":(start+timedelta(hours=8)).isoformat(),"reason":"Forgot checkout"})
    assert response.status_code==201,response.text
    cid=response.json()['id']
    assert client.post(f'/api/v1/corrections/{cid}/decision',headers=member,json={"status":"approved"}).status_code==403
    assert client.post(f'/api/v1/corrections/{cid}/decision',headers=lead,json={"status":"approved"}).status_code==200
    assert client.post(f'/api/v1/corrections/{cid}/decision',headers=lead,json={"status":"approved"}).status_code==409
    with factory() as db:
        assert db.get(Attendance,aid).check_out_at==start+timedelta(hours=7)
        assert db.query(AttendanceAdjustment).filter_by(attendance_id=aid).count()==2
    report=client.get(f'/api/v1/reports?start={start.date()}&end={start.date()}',headers=lead)
    assert report.status_code==200,report.text
    assert report.json()['attendance'][0]['minutes']==480


def test_settings_and_notifications_are_scoped(env):
    client,_=env; lead=auth(client,'lead'); member=auth(client,'member'); other=auth(client,'other')
    assert client.get('/api/v1/settings',headers=member).status_code==403
    assert client.patch('/api/v1/settings',headers=lead,json={"timezone":"Bad/Zone","work_days":"1,2,3","work_start":"09:00","work_end":"18:00"}).status_code==422
    task=client.post('/api/v1/tasks',headers=lead,json={"title":"Notify","assignee_id":2,"estimate_minutes":10})
    assert task.status_code==201
    notification=client.get('/api/v1/notifications',headers=member).json()[0]['id']
    assert client.post(f'/api/v1/notifications/{notification}/read',headers=other).status_code==404
    assert client.post(f'/api/v1/notifications/{notification}/read',headers=member).status_code==200


def test_links_cycle_prevention_watchers_and_attachment_access(env):
    client,_=env; lead=auth(client,'lead'); member=auth(client,'member'); other=auth(client,'other')
    project=client.post('/api/v1/projects',headers=lead,json={"key":"LINK","name":"Links"}).json()['id']
    assert client.post(f'/api/v1/projects/{project}/members',headers=lead,json={'user_id':2}).status_code==200
    payload={"project_id":project,"title":"Source","assignee_id":2,"estimate_minutes":10}
    first=client.post('/api/v1/issues',headers=lead,json=payload).json()['id']
    second=client.post('/api/v1/issues',headers=lead,json={**payload,"title":"Target"}).json()['id']
    assert client.post(f'/api/v1/issues/{first}/links',headers=lead,json={"target_id":second,"kind":"blocks"}).status_code==201
    assert client.post(f'/api/v1/issues/{second}/links',headers=lead,json={"target_id":first,"kind":"blocks"}).status_code==422
    assert client.post(f'/api/v1/issues/{first}/links',headers=lead,json={"target_id":first,"kind":"relates"}).status_code==422
    assert client.patch(f'/api/v1/tasks/{second}/status',headers=member,json={"status":"in_progress"}).status_code==200
    assert client.patch(f'/api/v1/tasks/{second}/status',headers=member,json={"status":"done"}).status_code==409
    assert client.post(f'/api/v1/issues/{first}/watch',headers=lead,json={"watching":True}).status_code==200
    assert client.post(f'/api/v1/issues/{first}/comments',headers=member,json={"body":"Update"}).status_code==201
    assert any(n['type']=='issue_comment' for n in client.get('/api/v1/notifications',headers=lead).json())
    uploaded=client.post(f'/api/v1/issues/{first}/attachments',headers=member,files={'file':('../notes.txt',b'hello','text/plain')})
    assert uploaded.status_code==201,uploaded.text
    assert uploaded.json()['filename']=='notes.txt'
    aid=uploaded.json()['id']
    assert client.get(f'/api/v1/attachments/{aid}/download',headers=other).status_code==404
    download=client.get(f'/api/v1/attachments/{aid}/download',headers=member)
    assert download.content==b'hello'
    assert download.headers['content-type']=='application/octet-stream'
    detail=client.get(f'/api/v1/issues/{first}',headers=member).json()
    assert 'content' not in detail['attachments'][0]


def test_distinct_multistep_leave_approvals(env):
    client,factory=env; lead=auth(client,'lead'); member=auth(client,'member')
    from my_time.auth import ph
    with factory() as db:
        db.add(User(id=5,team_id=1,username='lead2',name='Lead Two',role='lead',active=True,must_change_password=False,password_hash=ph.hash('test-password-123')))
        db.commit()
    second=auth(client,'lead2')
    policy=client.post('/api/v1/leave-policies',headers=lead,json={'name':'Two approvals','annual_days':'20','approval_steps':2}).json()['id']
    year=datetime.now().year
    assert client.post('/api/v1/leave-accounts',headers=lead,json={'user_id':2,'policy_id':policy,'year':year}).status_code==201
    day=date(year,1,1)
    while day.isoweekday()>5:day+=timedelta(days=1)
    request=client.post('/api/v1/leave',headers=member,json={'policy_id':policy,'start_date':str(day),'end_date':str(day),'reason':'Leave'})
    assert request.status_code==201,request.text
    lid=request.json()['id'];url=f'/api/v1/leave/{lid}/decision'
    first=client.post(url,headers=lead,json={'status':'approved'})
    assert first.status_code==200 and first.json()['status']=='pending'
    assert client.post(url,headers=lead,json={'status':'approved'}).status_code==409
    final=client.post(url,headers=second,json={'status':'approved'})
    assert final.status_code==200 and final.json()['status']=='approved'


def test_insufficient_leave_rolls_back_request_and_holidays_are_excluded(env):
    client,factory=env; lead=auth(client,'lead'); member=auth(client,'member')
    from my_time.models.hr import LocationHoliday
    from my_time.models.core import WorkLocation,LeaveRequest
    year=datetime.now().year
    with factory() as db:
        location=WorkLocation(team_id=1,name='Office',lat=0,lng=0,created_by=1)
        db.add(location);db.flush();locid=location.id
        db.add(EmployeeProfile(user_id=2,team_id=1,location_id=locid))
        # January 5–9, 2026 is a full working week; construct one in any year.
        monday=date(year,1,1)
        while monday.isoweekday()!=1:monday+=timedelta(days=1)
        db.add(LocationHoliday(team_id=1,location_id=locid,date=monday,name='Local holiday'));db.commit()
    pid=client.post('/api/v1/leave-policies',headers=lead,json={'name':'Small','annual_days':'1','location_id':locid}).json()['id']
    client.post('/api/v1/leave-accounts',headers=lead,json={'user_id':2,'policy_id':pid,'year':year})
    rejected=client.post('/api/v1/leave',headers=member,json={'policy_id':pid,'start_date':str(monday),'end_date':str(monday+timedelta(days=4)),'reason':'Week'})
    assert rejected.status_code==409,rejected.text
    with factory() as db:assert db.query(LeaveRequest).filter_by(user_id=2).count()==0
    accepted=client.post('/api/v1/leave',headers=member,json={'policy_id':pid,'start_date':str(monday),'end_date':str(monday+timedelta(days=1)),'reason':'Two dates one working day'})
    assert accepted.status_code==201,accepted.text
    assert Decimal(client.get('/api/v1/leave-accounts',headers=member).json()[0]['available_days'])==0


def test_carry_forward_transfers_and_prorated_joiners(env):
    _,factory=env
    from my_time.services.leave import rollover_team
    with factory() as db:
        policy=LeavePolicy(team_id=1,name='Carry',annual_days=Decimal('12'),accrual='annual',carry_forward_days=Decimal('3'))
        db.add(policy);db.flush()
        old=LeaveAccount(team_id=1,user_id=2,policy_id=policy.id,year=2025)
        db.add(old);db.flush();accrue(db,old,date(2025,12,31));db.commit()
        assert available(db,old.id)==12
        rollover_team(db,1,date(2026,1,1));db.flush()
        new=db.query(LeaveAccount).filter_by(policy_id=policy.id,user_id=2,year=2026).one()
        accrue(db,new,date(2026,1,1));db.commit()
        assert available(db,new.id)==15 and available(db,old.id)==9
        accrue(db,new,date(2026,1,2));db.commit()
        assert available(db,new.id)==15
        db.add(EmployeeProfile(user_id=2,team_id=1,joined_on=date(2026,7,1)))
        prorated=LeavePolicy(team_id=1,name='Prorated',annual_days=Decimal('12'),accrual='annual',prorate_joiners=True)
        db.add(prorated);db.flush()
        account=LeaveAccount(team_id=1,user_id=2,policy_id=prorated.id,year=2026)
        db.add(account);db.flush();accrue(db,account,date(2026,7,1));db.commit()
        assert available(db,account.id)==Decimal('6.04')


def test_half_day_and_waiting_period_policy(env):
    client,factory=env;lead=auth(client,'lead');member=auth(client,'member')
    year=datetime.now().year
    with factory() as db:
        db.add(EmployeeProfile(user_id=2,team_id=1,joined_on=date(year,1,1)));db.commit()
    pid=client.post('/api/v1/leave-policies',headers=lead,json={'name':'Half days','annual_days':'12','waiting_days':30}).json()['id']
    assert client.post('/api/v1/leave-accounts',headers=lead,json={'user_id':2,'policy_id':pid,'year':year}).status_code==201
    day=date(year,2,1)
    while day.isoweekday()>5:day+=timedelta(days=1)
    data={'policy_id':pid,'start_date':str(day),'end_date':str(day),'reason':'Half day','duration':'half'}
    response=client.post('/api/v1/leave',headers=member,json=data)
    assert response.status_code==201,response.text
    assert Decimal(client.get('/api/v1/leave-accounts',headers=member).json()[0]['available_days'])==Decimal('11.5')
    early={**data,'start_date':f'{year}-01-02','end_date':f'{year}-01-02'}
    assert client.post('/api/v1/leave',headers=member,json=early).status_code==422
