from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

from app.schemas.job import RemoteType

SENIORITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bintern(ship)?\b", re.I), "intern"),
    (re.compile(r"\bprincipal\b", re.I), "principal"),
    (re.compile(r"\bstaff\b", re.I), "staff"),
    (re.compile(r"\b(lead|head)\b", re.I), "lead"),
    (re.compile(r"\b(senior|sr\.?)\b", re.I), "senior"),
    (re.compile(r"\b(junior|jr\.?|entry[- ]?level|early[- ]career)\b", re.I), "junior"),
    (re.compile(r"\bmid[- ]?(level|career)?\b", re.I), "mid"),
]


def infer_seniority(title: str) -> str | None:
    for pattern, label in SENIORITY_PATTERNS:
        if pattern.search(title or ""):
            return label
    return None


def infer_remote_type(title: str, location: str | None, description: str | None) -> str:
    blob = " ".join(part for part in (title, location, description) if part).lower()
    if re.search(r"\bhybrid\b", blob):
        return RemoteType.hybrid.value
    if re.search(r"\b(remote|work from home|wfh)\b", blob):
        return RemoteType.remote.value
    if re.search(r"\b(on[- ]?site|in[- ]office)\b", blob):
        return RemoteType.onsite.value
    if location and location.strip() and location.strip().lower() not in {"remote", "anywhere"}:
        return RemoteType.onsite.value
    if location and "remote" in location.lower():
        return RemoteType.remote.value
    return RemoteType.unknown.value


def strip_html(value: str | None) -> str | None:
    if not value:
        return value
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_greenhouse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def normalize_greenhouse_job(raw: dict[str, Any]) -> dict[str, Any]:
    location_obj = raw.get("location") or {}
    location = location_obj.get("name") if isinstance(location_obj, dict) else None
    title = raw.get("title") or ""
    description = strip_html(raw.get("content"))
    posted = parse_greenhouse_datetime(raw.get("first_published")) or parse_greenhouse_datetime(
        raw.get("updated_at")
    )
    return {
        "greenhouse_job_id": str(raw.get("id")),
        "title": title,
        "location": location,
        "remote_type": infer_remote_type(title, location, description),
        "seniority": infer_seniority(title),
        "description": description,
        "url": raw.get("absolute_url") or "",
        "posted_at": posted,
    }
