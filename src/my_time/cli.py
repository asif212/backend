import argparse
from getpass import getpass
from .auth import ph
from .db import SessionLocal
from .models.core import User, AuditLog


def main():
    parser = argparse.ArgumentParser(description="Create an administrator after running migrations")
    parser.add_argument("username")
    args = parser.parse_args()
    password = getpass("Administrator password (12+ characters): ")
    if len(password) < 12:
        parser.error("Password must contain at least 12 characters")
    with SessionLocal() as db:
        if db.query(User).filter_by(username=args.username).first():
            parser.error("Username already exists")
        user = User(username=args.username, name="Administrator", role="super_admin",
                    password_hash=ph.hash(password), must_change_password=False)
        db.add(user)
        db.flush()
        db.add(AuditLog(action="admin_created", actor_id=user.id, target_type="users", target_id=user.id))
        db.commit()
    print("Administrator created")


if __name__ == "__main__":
    main()
