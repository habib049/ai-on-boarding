"""Helpers for the weekly usage report."""
import json
import os
from datetime import datetime

from django.contrib.auth.models import User


def format_row(user: User) -> dict:
    return {
        "email": user.email,
        "joined": user.date_joined.isoformat(),
        "last_seen": user.last_login.isoformat() if user.last_login else None,
    }


def summarise(users, window_days=7):
    rows = [format_row(u) for u in users]
    cutoff = datetime.now().timestamp() - (window_days * 86400)
    active = [r for r in rows if r["last_seen"] and _to_ts(r["last_seen"]) > cutoff]
    return {
        "total": len(rows),
        "active": len(active),
        "generated_at": datetime.now().isoformat(),
    }


def write_report(users, path):
    with open(path, "w") as handle:
        json.dump(summarise(users), handle)
