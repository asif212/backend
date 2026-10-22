import hashlib
import secrets
from datetime import datetime, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .db import get_db
from .models.core import User, Team, Session as LoginSession

ph = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verify(password_hash, password):
    try:
        return ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError, TypeError):
        return False


def issue_session(db, user):
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(id_hash=digest(token), user_id=user.id,
                        expires_at=datetime.utcnow() + timedelta(minutes=30)))
    return token


def authenticated(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(401, "Authentication required")
    session = db.get(LoginSession, digest(credentials.credentials))
    now = datetime.utcnow()
    if not session or session.expires_at <= now or session.created_at + timedelta(hours=12) <= now:
        raise HTTPException(401, "Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account unavailable")
    if user.role != "super_admin":
        team = db.get(Team, user.team_id)
        if not team or team.status != "active":
            raise HTTPException(403, "Team suspended")
    session.last_seen_at = now
    session.expires_at = min(now + timedelta(minutes=30), session.created_at + timedelta(hours=12))
    db.commit()
    return user


def current_user(user: User = Depends(authenticated)):
    if user.must_change_password:
        raise HTTPException(403, "Change your password before continuing")
    return user


def manager(user: User = Depends(current_user)):
    if user.role != "lead":
        raise HTTPException(403, "Team lead required")
    return user


def admin(user: User = Depends(current_user)):
    if user.role != "super_admin":
        raise HTTPException(403, "Administrator required")
    return user
