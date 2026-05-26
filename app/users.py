"""User management CLI.

Run as: python -m app.users <command>

Commands:
    create  --email X --role admin|uploader|viewer [--password Y]
    list
    passwd  --email X [--password Y]
    deactivate --email X
    activate   --email X
"""
import argparse
import getpass
import sqlite3
import sys
from datetime import datetime, timezone

from .auth import hash_password
from .db import DB_PATH, init_db


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _prompt_password(provided: str | None) -> str:
    if provided:
        return provided
    while True:
        p1 = getpass.getpass("Password: ")
        if len(p1) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            continue
        p2 = getpass.getpass("Confirm: ")
        if p1 != p2:
            print("Passwords did not match.", file=sys.stderr)
            continue
        return p1


def cmd_create(args) -> int:
    pw = _prompt_password(args.password)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (
                args.email.strip().lower(),
                hash_password(pw),
                args.role,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"User '{args.email}' already exists.", file=sys.stderr)
        return 1
    print(f"Created {args.role}: {args.email}")
    return 0


def cmd_list(_args) -> int:
    conn = _connect()
    rows = conn.execute(
        "SELECT email, role, is_active, created_at FROM users ORDER BY created_at"
    ).fetchall()
    if not rows:
        print("(no users)")
        return 0
    print(f"{'EMAIL':<32} {'ROLE':<10} {'STATUS':<10} CREATED")
    for r in rows:
        state = "active" if r["is_active"] else "inactive"
        print(f"{r['email']:<32} {r['role']:<10} {state:<10} {r['created_at']}")
    return 0


def cmd_passwd(args) -> int:
    pw = _prompt_password(args.password)
    conn = _connect()
    cur = conn.execute(
        "UPDATE users SET password_hash = ? WHERE email = ?",
        (hash_password(pw), args.email.strip().lower()),
    )
    conn.commit()
    if not cur.rowcount:
        print(f"No user '{args.email}'.", file=sys.stderr)
        return 1
    print(f"Password reset for {args.email}")
    return 0


def _toggle(email: str, active: int) -> int:
    conn = _connect()
    cur = conn.execute(
        "UPDATE users SET is_active = ? WHERE email = ?",
        (active, email.strip().lower()),
    )
    conn.commit()
    if not cur.rowcount:
        print(f"No user '{email}'.", file=sys.stderr)
        return 1
    print(f"{'Activated' if active else 'Deactivated'}: {email}")
    return 0


def cmd_deactivate(args) -> int:
    return _toggle(args.email, 0)


def cmd_activate(args) -> int:
    return _toggle(args.email, 1)


def main() -> int:
    init_db()
    p = argparse.ArgumentParser(prog="python -m app.users")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("create", help="Create a new user")
    pc.add_argument("--email", required=True)
    pc.add_argument("--role", choices=["admin", "uploader", "viewer"], required=True)
    pc.add_argument("--password", help="(if omitted, prompts securely)")
    pc.set_defaults(func=cmd_create)

    pl = sub.add_parser("list", help="List all users")
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("passwd", help="Reset a user's password")
    pp.add_argument("--email", required=True)
    pp.add_argument("--password", help="(if omitted, prompts securely)")
    pp.set_defaults(func=cmd_passwd)

    pd = sub.add_parser("deactivate", help="Deactivate a user (cannot log in)")
    pd.add_argument("--email", required=True)
    pd.set_defaults(func=cmd_deactivate)

    pa = sub.add_parser("activate", help="Reactivate a previously deactivated user")
    pa.add_argument("--email", required=True)
    pa.set_defaults(func=cmd_activate)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
