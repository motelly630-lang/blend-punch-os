"""
Seed script: creates default admin user if not already present.
Run once after uv sync:

    uv run python seed.py
"""
from app.database import init_db, SessionLocal
from app.models.user import User
from app.auth.service import hash_password

DEFAULT_USERNAME = "master"
DEFAULT_PASSWORD = "ChangeMe123!"
DEFAULT_ROLE = "admin"


def seed():
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == DEFAULT_USERNAME).first():
            print(f"[seed] User '{DEFAULT_USERNAME}' already exists — skipping.")
            return

        admin = User(
            username=DEFAULT_USERNAME,
            hashed_password=hash_password(DEFAULT_PASSWORD),
            role=DEFAULT_ROLE,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"[seed] Created admin user: {DEFAULT_USERNAME}")
        print(f"[seed] Default password: {DEFAULT_PASSWORD}")
        print("[seed] ⚠  Change the password after first login!")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
