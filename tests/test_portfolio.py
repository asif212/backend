import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from my_time.main import app
from my_time.auth import admin
from my_time.config import settings

@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'WEBSITE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client, tmp_path
    app.dependency_overrides.pop(admin, None)

def grant():
    app.dependency_overrides[admin] = lambda: object()

def create(client, title, parent=None):
    response=client.post('/api/v1/website/portfolio/sections',json={'title':title,'parent_id':parent})
    assert response.status_code==201,response.text
    return response.json()['sections'][-1]

def upload(client, section):
    image=io.BytesIO();Image.new('RGB',(40,30),'blue').save(image,'PNG')
    return client.post(f'/api/v1/website/portfolio/sections/{section}/photos',files={'file':('photo.png',image.getvalue(),'image/png')})

def test_public_defaults_and_auth(portfolio):
    c,_=portfolio
    result=c.get('/api/v1/website/portfolio')
    assert result.status_code==200
    assert [s['title'] for s in result.json()['sections']]==['Graphic Design','Photo Editing','Motion Graphics','Web Development','Video Editing']
    assert c.post('/api/v1/website/portfolio/sections',json={'title':'Private edit'}).status_code==401
    assert upload(c,'graphic-design').status_code==401
    assert c.delete('/api/v1/website/portfolio/sections/graphic-design').status_code==401

def test_nested_sections_and_cycle_validation(portfolio):
    c,_=portfolio;grant()
    parent=create(c,'Parent');child=create(c,'Child',parent['id']);grandchild=create(c,'Grandchild',child['id'])
    assert c.patch(f"/api/v1/website/portfolio/sections/{parent['id']}",json={'title':'Parent','parent_id':grandchild['id']}).status_code==422
    assert c.patch(f"/api/v1/website/portfolio/sections/{child['id']}",json={'title':'Child','parent_id':child['id']}).status_code==422
    assert c.post('/api/v1/website/portfolio/sections',json={'title':'Bad','parent_id':'missing'}).status_code==404
    assert c.post('/api/v1/website/portfolio/sections',json={'title':'   '}).status_code==422
    assert c.patch(f"/api/v1/website/portfolio/sections/{child['id']}",json={'title':'Moved','parent_id':None}).status_code==200
    assert next(s for s in c.get('/api/v1/website/portfolio').json()['sections'] if s['id']==child['id'])['parent_id'] is None

def test_upload_many_choose_shared_cover_and_delete(portfolio):
    c,path=portfolio;grant()
    parent=create(c,'Parent');child=create(c,'Child',parent['id'])
    for _ in range(10):
        response=upload(c,child['id']);assert response.status_code==201,response.text
    result=response.json();photo=result['photos'][0]
    assert len(result['photos'])==10
    assert c.get(photo['url']).headers['content-type']=='image/webp'
    response=c.patch(f"/api/v1/website/portfolio/sections/{parent['id']}",json={'title':'Parent','cover_id':photo['id']})
    assert response.status_code==200
    assert next(s for s in response.json()['sections'] if s['id']==parent['id'])['cover_id']==photo['id']
    assert c.patch(f"/api/v1/website/portfolio/sections/{parent['id']}",json={'title':'Parent','cover_id':'missing'}).status_code==422
    assert c.delete(f"/api/v1/website/portfolio/photos/{photo['id']}").status_code==200
    assert c.get(photo['url']).status_code==404
    assert next(s for s in c.get('/api/v1/website/portfolio').json()['sections'] if s['id']==parent['id'])['cover_id'] is None
    assert len(list((path/'portfolio_assets').glob('*.webp')))==9
    response=c.delete(f"/api/v1/website/portfolio/sections/{parent['id']}")
    assert response.status_code==200
    assert not response.json()['photos']
    assert not list((path/'portfolio_assets').glob('*.webp'))
    assert not any(s['id'] in {parent['id'],child['id']} for s in response.json()['sections'])
    assert c.get('/api/v1/website/portfolio/photos/..%2Fcontent.json').status_code==404

from test_api import env, auth

def test_non_admin_cannot_edit_portfolio(env,tmp_path,monkeypatch):
    c,_=env;monkeypatch.setattr(settings,'WEBSITE_DATA_DIR',str(tmp_path))
    for username in ['lead','member']:
        headers=auth(c,username)
        assert c.post('/api/v1/website/portfolio/sections',json={'title':'Blocked'},headers=headers).status_code==403
        assert c.delete('/api/v1/website/portfolio/sections/graphic-design',headers=headers).status_code==403
