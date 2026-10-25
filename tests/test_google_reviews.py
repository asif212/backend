import json
from urllib.parse import urlparse, parse_qs
import pytest
from fastapi.testclient import TestClient
from my_time.main import app
from my_time.auth import admin
from my_time.config import settings
from my_time import google_reviews as reviews

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'WEBSITE_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(settings, 'GOOGLE_CLIENT_ID', 'test-client')
    monkeypatch.setattr(settings, 'GOOGLE_CLIENT_SECRET', 'private-secret')
    reviews._cache.clear()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(admin, None)

def test_public_disconnected_and_admin_protection(client):
    assert client.get('/api/v1/website/reviews').json()['status'] == 'not_connected'
    assert client.get('/api/v1/website/reviews/google/status').status_code == 401
    assert client.post('/api/v1/website/reviews/google/connect').status_code == 401

def test_oauth_state_pkce_replay_and_private_credentials(client, monkeypatch):
    app.dependency_overrides[admin] = lambda: object()
    url = client.post('/api/v1/website/reviews/google/connect').json()['url']
    params = parse_qs(urlparse(url).query)
    assert params['code_challenge_method'] == ['S256']
    assert 'private-secret' not in url
    assert client.get('/api/v1/website/reviews/google/callback?state=bad&code=x').status_code == 400
    monkeypatch.setattr(reviews, 'request', lambda *args, **kwargs: {'refresh_token': 'private-refresh'})
    callback = '/api/v1/website/reviews/google/callback?state='+params['state'][0]+'&code=test'
    assert client.get(callback).status_code == 200
    assert client.get(callback).status_code == 400
    status = client.get('/api/v1/website/reviews/google/status')
    assert status.json()['connected'] is True
    assert 'private-refresh' not in status.text
    path = reviews.root() / 'google-business-private.json'
    assert path.stat().st_mode & 0o777 == 0o600
    assert client.get('/api/v1/website/assets/google-business-private.json').status_code == 404

def test_pages_ratings_cache_and_disconnect(client, monkeypatch):
    reviews.save({'refresh_token': 'secret', 'location': {'name': 'accounts/1/locations/2', 'title': 'Nial'}})
    monkeypatch.setattr(reviews, 'token', lambda: 'access')
    calls = []
    def google(url, access, **params):
        calls.append(params)
        return {'reviews': [{'reviewId': 'a', 'reviewer': {'displayName': 'A'}, 'starRating': 'TWO', 'comment': 'Honest feedback'}], 'averageRating': 4.2, 'totalReviewCount': 70, 'nextPageToken': 'next'}
    monkeypatch.setattr(reviews, 'google', google)
    first = client.get('/api/v1/website/reviews').json()
    assert first['reviews'][0]['rating'] == 2
    assert first['total'] == 70 and first['next_page_token'] == 'next'
    client.get('/api/v1/website/reviews')
    assert len(calls) == 1
    client.get('/api/v1/website/reviews?page_token=next')
    assert calls[-1]['pageToken'] == 'next'
    app.dependency_overrides[admin] = lambda: object()
    client.delete('/api/v1/website/reviews/google/connection')
    assert client.get('/api/v1/website/reviews').json()['status'] == 'not_connected'
