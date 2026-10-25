"""Authorized Google Business Profile reviews; credentials never leave the server."""
import hashlib
import base64
import json
import secrets
import time
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .auth import admin
from .config import settings
from .website import root, locked, atomic_write

router = APIRouter(prefix='/api/v1/website/reviews', tags=['Google reviews'])
_cache = {}
MAPS = 'https://maps.app.goo.gl/hqcUR8DCvtaxcHKfA'

def read():
    path = root() / 'google-business-private.json'
    return json.loads(path.read_text()) if path.exists() else {}

def save(data):
    _cache.clear()
    atomic_write(root() / 'google-business-private.json', json.dumps(data).encode())

def configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)

def request(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Google could not complete this request. Check the connection and Business Profile API access.') from None

def token():
    data = read()
    if not configured() or not data.get('refresh_token'):
        raise HTTPException(409, 'Connect Google Business Profile first.')
    return request('POST', 'https://oauth2.googleapis.com/token', data={
        'client_id': settings.GOOGLE_CLIENT_ID, 'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'refresh_token': data['refresh_token'], 'grant_type': 'refresh_token'})['access_token']

def google(url, access, **params):
    return request('GET', url, headers={'Authorization': f'Bearer {access}'}, params=params)

def locations():
    access = token()
    result = []
    page = ''
    while True:
        accounts = google('https://mybusinessaccountmanagement.googleapis.com/v1/accounts', access, pageToken=page)
        for account in accounts.get('accounts', []):
            next_page = ''
            while True:
                listing = google(f"https://mybusinessbusinessinformation.googleapis.com/v1/{account['name']}/locations", access, readMask='name,title', pageSize=100, pageToken=next_page)
                result.extend({'name': account['name'] + '/' + item['name'], 'title': item.get('title', item['name'])} for item in listing.get('locations', []))
                next_page = listing.get('nextPageToken', '')
                if not next_page:
                    break
        page = accounts.get('nextPageToken', '')
        if not page:
            return result

@router.get('/google/status')
def status(_=Depends(admin)):
    data = read()
    return {'configured': configured(), 'connected': bool(data.get('refresh_token')), 'location': data.get('location'), 'redirect_uri': settings.GOOGLE_REDIRECT_URI}

@router.post('/google/connect')
def connect(_=Depends(admin)):
    if not configured():
        raise HTTPException(409, 'Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the backend environment first.')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    with locked():
        data = read()
        data['pending'] = {'state': state, 'verifier': verifier, 'expires': time.time() + 600}
        save(data)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': settings.GOOGLE_CLIENT_ID, 'redirect_uri': settings.GOOGLE_REDIRECT_URI,
        'response_type': 'code', 'scope': 'https://www.googleapis.com/auth/business.manage',
        'access_type': 'offline', 'prompt': 'consent', 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})}

@router.get('/google/callback', response_class=HTMLResponse)
def callback(state: str = '', code: str = '', error: str = ''):
    with locked():
        data = read()
        pending = data.get('pending', {})
        if not state or not secrets.compare_digest(state, pending.get('state', '')) or pending.get('expires', 0) < time.time():
            raise HTTPException(400, 'This connection request expired. Start again from the website editor.')
        data.pop('pending', None)
        save(data)
    if error or not code:
        raise HTTPException(400, 'Google authorization was not completed.')
    result = request('POST', 'https://oauth2.googleapis.com/token', data={
        'client_id': settings.GOOGLE_CLIENT_ID, 'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'redirect_uri': settings.GOOGLE_REDIRECT_URI, 'code': code,
        'code_verifier': pending['verifier'], 'grant_type': 'authorization_code'})
    if not result.get('refresh_token'):
        raise HTTPException(400, 'Google did not issue offline access. Reconnect and grant access.')
    with locked():
        data = read()
        data['refresh_token'] = result['refresh_token']
        data.pop('location', None)
        save(data)
    return '<!doctype html><title>Google connected</title><h1>Google connected</h1><p>Close this tab, then refresh the connection in the website editor and select your business.</p>'

@router.get('/google/locations')
def list_locations(_=Depends(admin)):
    return {'locations': locations()}

class Selection(BaseModel):
    name: str = Field(pattern=r'^accounts/[0-9]+/locations/[0-9]+$')

@router.post('/google/location')
def select_location(value: Selection, _=Depends(admin)):
    found = next((item for item in locations() if item['name'] == value.name), None)
    if not found:
        raise HTTPException(422, 'Choose a business managed by your connected account.')
    with locked():
        data = read()
        data['location'] = found
        save(data)
    return {'location': found}

@router.delete('/google/connection')
def disconnect(_=Depends(admin)):
    with locked():
        save({})
    return {'connected': False}

@router.get('')
def reviews(page_token: str = Query(default='', max_length=4096)):
    location = read().get('location')
    base = {'maps_url': MAPS, 'reviews': [], 'next_page_token': ''}
    if not location:
        return {**base, 'status': 'not_connected'}
    key = (location['name'], page_token)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        result = google(f"https://mybusiness.googleapis.com/v4/{location['name']}/reviews", token(), pageSize=50, orderBy='updateTime desc', pageToken=page_token)
    except HTTPException:
        return {**base, 'status': 'unavailable'}
    ratings = {'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4, 'FIVE': 5}
    payload = {**base, 'status': 'ready', 'business': location['title'], 'average_rating': result.get('averageRating', 0), 'total': result.get('totalReviewCount', 0), 'next_page_token': result.get('nextPageToken', ''), 'reviews': [
        {'id': item['reviewId'], 'author': item.get('reviewer', {}).get('displayName', 'Google reviewer'), 'rating': ratings.get(item.get('starRating'), 0), 'text': item.get('comment', ''), 'date': item.get('createTime', '')}
        for item in result.get('reviews', [])]}

    if len(_cache) >= 64:
        _cache.clear()
    _cache[key] = (time.monotonic() + 120, payload)
    return payload
