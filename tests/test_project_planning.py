from decimal import Decimal
from test_api import env, auth


def project(client, headers, key="PLAN", **fields):
    response=client.post("/api/v1/projects",headers=headers,json={"key":key,"name":"Planning",**fields})
    assert response.status_code==201,response.text
    return response.json()["id"]


def test_project_owner_cost_estimate_and_dates(env):
    client,_=env;lead=auth(client,"lead");other=auth(client,"other")
    pid=project(client,lead,owner_id=1,cost="150000.25",currency="INR",estimate_minutes=4800,
                planned_date="2026-11-01",release_date="2026-12-01")
    row=client.get(f"/api/v1/projects/{pid}",headers=lead).json()
    assert Decimal(row['cost'])==Decimal('150000.25')
    assert row['estimate_minutes']==4800 and row['owner_id']==1
    assert client.get(f"/api/v1/projects/{pid}",headers=other).status_code==404
    assert client.patch(f"/api/v1/projects/{pid}",headers=lead,json={"planned_date":"2027-01-01"}).status_code==422
    changed=client.patch(f"/api/v1/projects/{pid}",headers=lead,json={"cost":"200000.99","estimate_minutes":9600})
    assert changed.status_code==200,changed.text
    assert changed.json()['planned_date']=='2026-11-01'
    assert changed.json()['estimate_minutes']==9600
    assert client.post('/api/v1/projects',headers=lead,json={'key':'BAD','name':'Bad','cost':'-1'}).status_code==422
    assert client.post('/api/v1/projects',headers=lead,json={'key':'BAD','name':'Bad','owner_id':3}).status_code==422


def test_allocation_requires_same_team_and_project_assignment(env):
    client,_=env;lead=auth(client,'lead');member=auth(client,'member');other=auth(client,'other')
    pid=project(client,lead)
    payload={'project_id':pid,'title':'Feature','kind':'feature','assignee_id':2,'estimate_minutes':240}
    assert client.post('/api/v1/issues',headers=lead,json=payload).status_code==422
    assert client.post(f'/api/v1/projects/{pid}/members',headers=member,json={'user_id':2}).status_code==403
    assert client.post(f'/api/v1/projects/{pid}/members',headers=lead,json={'user_id':3}).status_code==404
    added=client.post(f'/api/v1/projects/{pid}/members',headers=lead,json={'user_id':2,'allocation_percent':'50'})
    assert added.status_code==200,added.text
    assert client.get(f'/api/v1/projects/{pid}/members',headers=other).status_code==404
    issue=client.post('/api/v1/issues',headers=lead,json=payload)
    assert issue.status_code==201,issue.text
    assert issue.json()['kind']=='feature'
    assert client.post(f'/api/v1/projects/{pid}/members',headers=lead,json={'user_id':2,'active':False}).status_code==409


def test_allocation_capacity_sweep_and_updates(env):
    client,_=env;lead=auth(client,'lead')
    one=project(client,lead,'ONE');two=project(client,lead,'TWO');three=project(client,lead,'THREE')
    def allocate(pid,percent,start,end):
        return client.post(f'/api/v1/projects/{pid}/members',headers=lead,json={'user_id':2,'allocation_percent':percent,'start_date':start,'end_date':end})
    assert allocate(one,60,'2026-11-01','2026-11-15').status_code==200
    assert allocate(two,60,'2026-11-16','2026-11-30').status_code==200
    # Existing intervals are disjoint, so a 40% month-long booking fits both.
    assert allocate(three,40,'2026-11-01','2026-11-30').status_code==200
    assert allocate(three,41,'2026-11-01','2026-11-30').status_code==409
    assert allocate(three,40,'2026-11-30','2026-11-01').status_code==422
    assert allocate(one,101,'2026-11-01','2026-11-15').status_code==422
    rows=client.get(f'/api/v1/projects/{three}/members',headers=lead).json()
    assert len(rows)==1 and Decimal(rows[0]['allocation_percent'])==40


def test_feature_metadata_edit_and_allocation_dates(env):
    client,_=env;lead=auth(client,'lead')
    pid=project(client,lead)
    assert client.post(f'/api/v1/projects/{pid}/members',headers=lead,json={'user_id':2,'start_date':'2026-11-01','end_date':'2026-11-30'}).status_code==200
    payload={'project_id':pid,'title':'Payments','kind':'feature','assignee_id':2,'estimate_minutes':1200,
             'planned_date':'2026-11-05','release_date':'2026-11-20','cost':'12345.67','currency':'USD'}
    assert client.post('/api/v1/issues',headers=lead,json={**payload,'planned_date':'2026-10-01'}).status_code==422
    response=client.post('/api/v1/issues',headers=lead,json=payload)
    assert response.status_code==201,response.text
    row=response.json();iid=row['id']
    assert Decimal(row['cost'])==Decimal('12345.67') and row['currency']=='USD'
    edit={'title':'Updated payments','assignee_id':2,'estimate_minutes':1440,'cost':'99.99','currency':'EUR',
          'planned_date':'2026-11-10','release_date':'2026-11-25','kind':'feature'}
    response=client.patch(f'/api/v1/issues/{iid}',headers=lead,json=edit)
    assert response.status_code==200,response.text
    assert response.json()['estimate_minutes']==1440 and response.json()['kind']=='feature'
    assert client.patch(f'/api/v1/issues/{iid}',headers=lead,json={**edit,'release_date':'2026-11-01'}).status_code==422
    assert client.patch(f'/api/v1/issues/{iid}',headers=lead,json={**edit,'planned_date':'2026-12-01','release_date':'2026-12-10'}).status_code==422
    assert client.patch(f'/api/v1/issues/{iid}',headers=lead,json={**edit,'cost':'0.001'}).status_code==422


def test_member_can_be_removed_and_reactivated_without_duplicate_rows(env):
    client,_=env;lead=auth(client,'lead')
    pid=project(client,lead)
    url=f'/api/v1/projects/{pid}/members'
    first=client.post(url,headers=lead,json={'user_id':2}).json()
    removed=client.post(url,headers=lead,json={'user_id':2,'active':False})
    assert removed.status_code==200 and removed.json()['active'] is False
    active=client.post(url,headers=lead,json={'user_id':2,'allocation_percent':25})
    assert active.status_code==200 and active.json()['id']==first['id']
    assert len(client.get(url,headers=lead).json())==1
