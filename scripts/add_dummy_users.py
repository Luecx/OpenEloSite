from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "server"
sys.path.insert(0, str(SERVER_ROOT))

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.repositories import user_repository
from app.db.session import SessionLocal
from app.db.session import engine
from app.security.password_hasher import hash_password
from app.services.schema_service import ensure_schema
from app.services.seed_service import ensure_admin
from app.services.seed_service import ensure_roles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add dummy users to the OpenELO database.")
    parser.add_argument("--count", type=int, default=50, help="Number of dummy users to create.")
    parser.add_argument("--prefix", default="dummy", help="Username/email prefix.")
    parser.add_argument("--password", default="dummy123", help="Password for all created users.")
    parser.add_argument(
        "--roles",
        default="",
        help="Comma-separated role names to assign, e.g. tester or admin,tester.",
    )
    return parser.parse_args()


def normalize_roles(raw_roles: str) -> list[str]:
    return [item.strip() for item in raw_roles.split(",") if item.strip()]


def next_available_identity(db, prefix: str, start_index: int) -> tuple[str, str, str]:
    index = start_index
    while True:
        username = f"{prefix}{index:03d}"
        email = f"{username}@example.com"
        if user_repository.get_user_by_username(db, username) is None and user_repository.get_user_by_email(db, email) is None:
            display_name = f"Dummy User {index:03d}"
            return username, display_name, email
        index += 1


def main() -> None:
    args = parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be greater than 0")

    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)

    db = SessionLocal()
    try:
        ensure_roles(db)
        ensure_admin(db)

        roles = normalize_roles(args.roles)
        password_hash = hash_password(args.password)

        created_users = []
        next_index = 1
        for _ in range(args.count):
            username, display_name, email = next_available_identity(db, args.prefix, next_index)
            user = user_repository.create_user(
                db=db,
                username=username,
                display_name=display_name,
                email=email,
                password_hash=password_hash,
            )
            for role_name in roles:
                user_repository.assign_role(db, user, role_name)
            created_users.append(user)
            next_index = int(username.removeprefix(args.prefix)) + 1

        print(f"Created {len(created_users)} dummy users.")
        print(f"Prefix   : {args.prefix}")
        print(f"Password : {args.password}")
        print(f"Roles    : {', '.join(roles) if roles else '-'}")
        print()
        for user in created_users[:10]:
            print(f"- {user.username} | {user.email}")
        if len(created_users) > 10:
            print(f"... and {len(created_users) - 10} more")
    finally:
        db.close()


if __name__ == "__main__":
    main()
