import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from my_time.main import app
from my_time.auth import admin
from my_time.config import settings
from my_time.website import DEFAULT, MAX_UPLOAD, SLOTS

@pytest.fixture
def website(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'WEBSITE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client, tmp_path
    app.dependency_overrides.pop(admin, None)

def grant_admin():
    app.dependency_overrides[admin] = lambda: object()

def image_bytes(colour='red'):
    data = io.BytesIO()
    Image.new('RGB', (100, 70), colour).save(data, 'PNG')
    return data.getvalue()

def test_public_content_and_protected_writes(website):
    client, _ = website
    response = client.get('/api/v1/website')
    assert response.status_code == 200
    assert response.json()['brand'] == 'NialTech'
    assert 'password' not in response.text
    assert client.patch('/api/v1/website', json=DEFAULT.model_dump()).status_code == 401
    assert client.post('/api/v1/website/assets/hero', files={'file': ('a.png', image_bytes())}).status_code == 401

def test_edit_persists_and_rejects_unbounded_or_unsafe_content(website):
    client, _ = website
    grant_admin()
    data = DEFAULT.model_dump()
    data['hero_title'] = 'A new chapter'
    data['sections'][1]['visible'] = False
    assert client.patch('/api/v1/website', json=data).status_code == 200
    saved = client.get('/api/v1/website').json()
    assert saved['hero_title'] == 'A new chapter'
    assert saved['sections'][1]['visible'] is False
    data['cards'][0]['link'] = 'javascript:alert(1)'
    assert client.patch('/api/v1/website', json=data).status_code == 422
    data['cards'][0]['link'] = ''
    data['cards'].append(data['cards'][0])
    assert client.patch('/api/v1/website', json=data).status_code == 422
    data = DEFAULT.model_dump()
    data['accent'] = 'red;display:none'
    assert client.patch('/api/v1/website', json=data).status_code == 422

def test_replacement_is_bounded_and_reencoded(website):
    client, path = website
    grant_admin()
    for colour in ['red', 'blue']:
        response = client.post('/api/v1/website/assets/hero', files={'file': ('not-trusted.jpg', image_bytes(colour), 'image/jpeg')})
        assert response.status_code == 200
        assert 'hero' in response.json()['images']
        assert list(path.glob('*.webp')) == [path / 'hero.webp']
        assert not list(path.glob('.replace-*'))
    with Image.open(path / 'hero.webp') as image:
        assert image.format == 'WEBP'
        assert image.getpixel((0, 0))[2] > 200
    response = client.get('/api/v1/website/assets/hero')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/webp'
    assert client.get('/api/v1/website/assets/nonexistent').status_code == 404
    for slot in SLOTS:
        assert client.post(f'/api/v1/website/assets/{slot}', files={'file': ('a.png', image_bytes())}).status_code == 200
    assert len(list(path.glob('*.webp'))) == 8

def test_invalid_upload_keeps_previous_image(website):
    client, path = website
    grant_admin()
    client.post('/api/v1/website/assets/hero', files={'file': ('a.png', image_bytes())})
    previous = (path / 'hero.webp').read_bytes()
    assert client.post('/api/v1/website/assets/hero', files={'file': ('a.png', b'not an image')}).status_code == 415
    assert client.post('/api/v1/website/assets/hero', files={'file': ('a.svg', b'<svg/>')}).status_code == 415
    assert client.post('/api/v1/website/assets/hero', files={'file': ('a.png', b'x' * (MAX_UPLOAD+1))}).status_code == 413
    assert client.post('/api/v1/website/assets/new-slot', files={'file': ('a.png', image_bytes())}).status_code == 404
    assert (path / 'hero.webp').read_bytes() == previous

# Exercise the real authentication dependency as well as the isolated content tests.
from test_api import env, auth

def test_leads_and_members_cannot_edit_public_website(env, tmp_path, monkeypatch):
    client, _ = env
    monkeypatch.setattr(settings, 'WEBSITE_DATA_DIR', str(tmp_path))
    for role in ['lead', 'member']:
        headers = auth(client, role)
        assert client.patch('/api/v1/website', json=DEFAULT.model_dump(), headers=headers).status_code == 403
        assert client.post('/api/v1/website/assets/hero', files={'file': ('a.png', image_bytes())}, headers=headers).status_code == 403
    headers = auth(client, 'admin')
    assert client.patch('/api/v1/website', json=DEFAULT.model_dump(), headers=headers).status_code == 200
