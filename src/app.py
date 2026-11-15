#!/usr/bin/env python3
"""BringMeJobs local MVP: SQLite-backed job discovery and review dashboard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "bringmejobs.sqlite3"))
HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "6767"))
EUROPE = {
    "albania", "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechia",
    "denmark", "estonia", "finland", "france", "germany", "greece", "hungary",
    "iceland", "ireland", "italy", "latvia", "liechtenstein", "lithuania",
    "luxembourg", "malta", "moldova", "monaco", "montenegro", "netherlands",
    "north macedonia", "norway", "poland", "portugal", "romania", "serbia",
    "slovakia", "slovenia", "spain", "sweden", "switzerland", "uk", "ukraine",
    "united kingdom", "vatican", "england", "scotland", "wales",
}
EUROPE_CITIES = {
    "amsterdam", "athens", "barcelona", "berlin", "brussels", "bucharest",
    "budapest", "copenhagen", "dublin", "edinburgh", "frankfurt", "geneva",
    "helsinki", "lisbon", "london", "luxembourg", "lyon", "madrid",
    "manchester", "milan", "munich", "oslo", "oxford", "paris", "prague",
    "rome", "stockholm", "tallinn", "the hague", "vienna", "warsaw",
    "zurich",
}
ROLE_TERMS = (
    "software engineer", "software developer", "backend", "frontend", "full stack",
    "machine learning", "ai engineer", "applied ai", "data engineer",
    "forward deployed", "systems engineer", "infrastructure", "platform engineer",
)
SENIOR_TERMS = (
    "senior", "staff", "principal", "lead", "manager", "director", "head of",
    "vice president", " vp ", "architect",
)
EARLY_CAREER_EXCLUSIONS = (
    "intern", "internship", "new grad", "new graduate",
)
COMPANIES = [
    "Google", "Amazon", "Microsoft", "Apple", "Meta", "Netflix", "NVIDIA",
    "Stripe", "Databricks", "Snowflake", "Palantir", "OpenAI", "Anthropic",
    "DeepMind", "Mistral AI", "Hugging Face", "Cohere", "Scale AI", "Anduril",
    "Tesla", "ASML", "Arm", "Spotify", "Revolut", "Wise", "Adyen",
    "Checkout.com", "Klarna", "Monzo", "N26", "Cloudflare", "Datadog",
    "Elastic", "GitLab", "Atlassian", "Salesforce", "Adobe", "Uber", "Airbnb",
    "Booking.com", "Bloomberg", "Wayve", "Helsing", "Quantum Systems", "DeepL",
    "ElevenLabs", "Celonis", "SAP", "Cisco", "Oracle",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def migrate(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS companies (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, careers_url TEXT NOT NULL DEFAULT '',
          locations TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
          notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_sources (
          id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          source_type TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
          last_success_at TEXT, last_status TEXT, last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES job_sources(id) ON DELETE CASCADE,
          company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          source_job_id TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, canonical_url TEXT NOT NULL,
          posted_at TEXT, fetched_at TEXT NOT NULL, score INTEGER NOT NULL DEFAULT 0,
          match_reasons TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'new',
          raw_json TEXT NOT NULL DEFAULT '{}', UNIQUE(source_id, source_job_id)
        );
        CREATE TABLE IF NOT EXISTS job_runs (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0, fetched INTEGER NOT NULL DEFAULT 0,
          matched INTEGER NOT NULL DEFAULT 0, inserted INTEGER NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS job_run_sources (
          run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
          source_id INTEGER NOT NULL REFERENCES job_sources(id) ON DELETE CASCADE,
          status TEXT NOT NULL, fetched INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(run_id, source_id)
        );
        CREATE TABLE IF NOT EXISTS job_status_history (
          id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          status TEXT NOT NULL, changed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS search_config (
          id INTEGER PRIMARY KEY CHECK(id = 1), locations TEXT NOT NULL,
          role_terms TEXT NOT NULL, excluded_terms TEXT NOT NULL, max_age_days INTEGER NOT NULL,
          schedule TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_job_sources_company_url
          ON job_sources(company_id, url);
        CREATE TABLE IF NOT EXISTS app_meta (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_run_logs (
          id INTEGER PRIMARY KEY,
          run_id INTEGER NOT NULL REFERENCES job_runs(id) ON DELETE CASCADE,
          logged_at TEXT NOT NULL,
          step TEXT NOT NULL,
          level TEXT NOT NULL DEFAULT 'info',
          message TEXT NOT NULL,
          metadata TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    existing_source_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(job_sources)")
    }
    for column, definition in (
        ("health_status", "TEXT"),
        ("health_checked_at", "TEXT"),
        ("health_error", "TEXT"),
    ):
        if column not in existing_source_columns:
            db.execute(f"ALTER TABLE job_sources ADD COLUMN {column} {definition}")
    db.executemany(
        "INSERT OR IGNORE INTO companies(name, created_at) VALUES (?, ?)",
        [(name, now()) for name in dict.fromkeys(COMPANIES)],
    )
    if db.execute("SELECT value FROM app_meta WHERE key='catalog_seed'").fetchone() is None:
        # Remove only untouched entries from the old broad seed. User-entered
        # companies and companies already used by jobs are preserved.
        placeholders = ",".join("?" for _ in COMPANIES)
        db.execute(
            f"""DELETE FROM companies
                WHERE name NOT IN ({placeholders})
                  AND careers_url=''
                  AND id NOT IN (SELECT DISTINCT company_id FROM jobs)""",
            COMPANIES,
        )
    db.execute(
        "INSERT INTO app_meta(key, value) VALUES('catalog_seed', 'premium-50-v1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    if db.execute("SELECT 1 FROM job_sources WHERE source_type != 'fixture' LIMIT 1").fetchone():
        db.execute("UPDATE job_sources SET enabled=0 WHERE source_type='fixture'")
    db.execute(
        """INSERT OR IGNORE INTO search_config(id, locations, role_terms, excluded_terms, max_age_days, schedule)
           VALUES(1, ?, ?, ?, 30, '00:00')""",
        ("London, Berlin, Amsterdam, Paris, Dublin, Zurich, Stockholm, Remote Europe",
         ", ".join(ROLE_TERMS), ", ".join(SENIOR_TERMS)),
    )
    db.commit()


def json_response(handler: BaseHTTPRequestHandler, payload: object, status=HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def log_run(
    db: sqlite3.Connection,
    run_id: int,
    step: str,
    message: str,
    level: str = "info",
    metadata: dict | None = None,
) -> None:
    db.execute(
        """INSERT INTO job_run_logs(run_id, logged_at, step, level, message, metadata)
           VALUES(?,?,?,?,?,?)""",
        (run_id, now(), step, level, message, json.dumps(metadata or {})),
    )
    db.commit()


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 2_000_000:
        raise ValueError("request body is too large")
    return json.loads(handler.rfile.read(length) or b"{}")


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))


def job_id(source_id: int, source_job_id: str, url: str) -> str:
    key = f"{source_id}:{source_job_id}:{canonical_url(url)}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def source_jobs(source: sqlite3.Row, since: datetime) -> list[dict]:
    if source["source_type"] == "fixture":
        return [
            {"id": "fixture-1", "title": "Software Engineer, Developer Platform", "location": "Berlin, Germany",
             "description": "Build reliable services and developer tooling.", "url": "https://example.com/jobs/fixture-1",
             "posted_at": now()},
            {"id": "fixture-2", "title": "Senior Software Engineer", "location": "London, United Kingdom",
             "description": "Lead a large engineering team.", "url": "https://example.com/jobs/fixture-2",
             "posted_at": now()},
            {"id": "fixture-3", "title": "Applied AI Engineer", "location": "Paris, France",
             "description": "Build production machine learning systems.", "url": "https://example.com/jobs/fixture-3",
             "posted_at": now()},
        ]
    parsed_source_url = urllib.parse.urlsplit(source["url"])
    if source["source_type"] == "careers" and parsed_source_url.hostname == "www.palantir.com":
        endpoint = "https://www.palantir.com/api/lever/v1/postings?state=published"
        postings = []
        while endpoint:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "BringMeJobs/0.1"})
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
            postings.extend(payload.get("data", []))
            next_offset = payload.get("next") if payload.get("hasNext") else None
            endpoint = (
                f"https://www.palantir.com/api/lever/v1/postings?state=published&offset={next_offset}"
                if next_offset else ""
            )
        return [
            {
                "id": posting.get("id"),
                "title": posting.get("text", ""),
                "location": ", ".join(posting.get("categories", {}).get("allLocations", []))
                or posting.get("categories", {}).get("location", ""),
                "description": posting.get("content", {}).get("description", ""),
                "url": posting.get("urls", {}).get("show", source["url"]),
                "posted_at": datetime.fromtimestamp(
                    posting.get("createdAt", 0) / 1000, tz=timezone.utc
                ).isoformat(timespec="seconds") if posting.get("createdAt") else now(),
            }
            for posting in postings
        ]
    request = urllib.request.Request(source["url"], headers={"User-Agent": "BringMeJobs/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    if source["source_type"] == "careers" or "html" in content_type:
        class JsonLdParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_script = False
                self.text = []
                self.blocks = []

            def handle_starttag(self, tag, attrs):
                if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
                    self.in_script = True
                    self.text = []

            def handle_data(self, data):
                if self.in_script:
                    self.text.append(data)

            def handle_endtag(self, tag):
                if tag == "script" and self.in_script:
                    self.in_script = False
                    try:
                        self.blocks.append(json.loads("".join(self.text)))
                    except json.JSONDecodeError:
                        pass

        parser = JsonLdParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        data = []
        for block in parser.blocks:
            values = block if isinstance(block, list) else block.get("@graph", [block]) if isinstance(block, dict) else []
            data.extend(item for item in values if isinstance(item, dict) and item.get("@type") in ("JobPosting", ["JobPosting"]))
        return [
            {"id": item.get("identifier", {}).get("value", item.get("url", "")) if isinstance(item.get("identifier"), dict) else item.get("url", ""),
             "title": item.get("title", ""), "location": item.get("jobLocation", {}).get("address", {}).get("addressLocality", "")
             if isinstance(item.get("jobLocation"), dict) else str(item.get("jobLocation", "")),
             "description": item.get("description", ""), "url": item.get("url", source["url"]),
             "posted_at": item.get("datePosted", now())} for item in data
        ]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("source must return JSON or JSON-LD JobPosting data") from exc
    if not isinstance(data, list):
        raise ValueError("JSON source must return an array of job objects")
    return data


def normalize_and_match(raw: dict, source: sqlite3.Row, config: sqlite3.Row) -> dict | None:
    title = str(raw.get("title", "")).strip()
    location = str(raw.get("location", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not title or not location or not url:
        raise ValueError("job requires title, location, and url")
    title_lower = f" {title.lower()} "
    location_lower = location.lower()
    role_terms = [x.strip().lower() for x in config["role_terms"].split(",") if x.strip()]
    excluded = [
        x.strip().lower()
        for x in config["excluded_terms"].split(",")
        if x.strip()
    ] + list(EARLY_CAREER_EXCLUSIONS)
    role_hits = [term for term in role_terms if term in title_lower]
    senior_hits = [term for term in excluded if term in title_lower]
    europe = (
        any(country in location_lower for country in EUROPE)
        or any(city in location_lower for city in EUROPE_CITIES)
        or "europe" in location_lower
    )
    if not role_hits or senior_hits or not europe:
        return None
    reasons = [f"role: {', '.join(role_hits[:3])}", "location: Europe"]
    score = min(100, 50 + len(role_hits) * 10)
    posted = str(raw.get("posted_at") or raw.get("updated_at") or now())
    posted_dt = parse_date(posted)
    if posted_dt and posted_dt < datetime.now(timezone.utc) - timedelta(days=int(config["max_age_days"])):
        return None
    source_job_id = str(raw.get("id") or hashlib.sha256(url.encode()).hexdigest()[:16])
    return {
        "source_job_id": source_job_id, "title": title, "location": location,
        "description": str(raw.get("description", "")), "url": url,
        "canonical_url": canonical_url(url), "posted_at": posted, "score": score,
        "match_reasons": reasons, "raw_json": raw,
    }


RUN_LOCK = threading.Lock()


def run_search(dry_run=False) -> dict:
    if not RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("another search is already running")
    db = connect()
    started = now()
    run_id = db.execute(
        "INSERT INTO job_runs(started_at, status, dry_run) VALUES (?, 'running', ?)",
        (started, int(dry_run)),
    ).lastrowid
    totals = {"run_id": run_id, "fetched": 0, "matched": 0, "inserted": 0, "errors": []}
    try:
        log_run(db, run_id, "run.started", "Search run started", metadata={"dry_run": dry_run})
        config = db.execute("SELECT * FROM search_config WHERE id=1").fetchone()
        sources = db.execute(
            """SELECT s.*, c.name company_name FROM job_sources s JOIN companies c ON c.id=s.company_id
               WHERE s.enabled=1 AND c.enabled=1"""
        ).fetchall()
        since = datetime.now(timezone.utc) - timedelta(days=int(config["max_age_days"]))
        log_run(
            db,
            run_id,
            "configuration.loaded",
            f"Loaded search configuration and {len(sources)} enabled source(s)",
            metadata={"source_count": len(sources), "max_age_days": config["max_age_days"]},
        )
        for source in sources:
            try:
                log_run(
                    db,
                    run_id,
                    "source.started",
                    f"Fetching {source['company_name']}",
                    metadata={"source_id": source["id"], "url": source["url"]},
                )
                raws = source_jobs(source, since)
                log_run(
                    db,
                    run_id,
                    "source.fetched",
                    f"Fetched {len(raws)} listing(s) from {source['company_name']}",
                    metadata={"source_id": source["id"], "fetched": len(raws)},
                )
                matched = 0
                for raw in raws:
                    totals["fetched"] += 1
                    normalized = normalize_and_match(raw, source, config)
                    if not normalized:
                        continue
                    matched += 1
                    totals["matched"] += 1
                    if not dry_run:
                        jid = job_id(source["id"], normalized["source_job_id"], normalized["url"])
                        existing = db.execute("SELECT id FROM jobs WHERE id=?", (jid,)).fetchone()
                        db.execute(
                            """INSERT INTO jobs(id, source_id, company_id, source_job_id, title, location, description,
                               url, canonical_url, posted_at, fetched_at, score, match_reasons, raw_json)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(id) DO UPDATE SET fetched_at=excluded.fetched_at,
                               title=excluded.title, location=excluded.location, description=excluded.description,
                               posted_at=excluded.posted_at, score=excluded.score, match_reasons=excluded.match_reasons,
                               raw_json=excluded.raw_json""",
                            (jid, source["id"], source["company_id"], normalized["source_job_id"],
                             normalized["title"], normalized["location"], normalized["description"],
                             normalized["url"], normalized["canonical_url"], normalized["posted_at"], now(),
                             normalized["score"], json.dumps(normalized["match_reasons"]),
                             json.dumps(normalized["raw_json"])),
                        )
                        if not existing:
                            totals["inserted"] += 1
                            db.execute(
                                "INSERT INTO job_status_history(job_id, status, changed_at) VALUES(?,?,?)",
                                (jid, "new", now()),
                            )
                log_run(
                    db,
                    run_id,
                    "source.processed",
                    f"Processed {source['company_name']}: {matched} matching listing(s)",
                    metadata={"source_id": source["id"], "matched": matched},
                )
                db.execute(
                    "INSERT INTO job_run_sources(run_id, source_id, status, fetched) VALUES(?,?,?,?)",
                    (run_id, source["id"], "success", len(raws)),
                )
                db.execute(
                    "UPDATE job_sources SET last_success_at=?, last_status='success', last_error='' WHERE id=?",
                    (now(), source["id"]),
                )
                log_run(
                    db,
                    run_id,
                    "source.completed",
                    f"Completed {source['company_name']}",
                    metadata={"source_id": source["id"]},
                )
            except Exception as exc:  # each source failure is surfaced in the run result
                if isinstance(exc, HTTPError) and exc.code == 403:
                    detail = "HTTP 403: source rejected automated access; no bypass attempted"
                else:
                    detail = str(exc)
                message = f"{source['company_name']}: {detail}"
                totals["errors"].append(message)
                db.execute(
                    "INSERT INTO job_run_sources(run_id, source_id, status, error) VALUES(?,?,?,?)",
                    (run_id, source["id"], "failed", message),
                )
                db.execute(
                    "UPDATE job_sources SET last_status='failed', last_error=? WHERE id=?",
                    (message, source["id"]),
                )
                log_run(
                    db,
                    run_id,
                    "source.failed",
                    message,
                    level="error",
                    metadata={"source_id": source["id"]},
                )
        successful_sources = db.execute(
            "SELECT COUNT(*) FROM job_run_sources WHERE run_id=? AND status='success'",
            (run_id,),
        ).fetchone()[0]
        status = (
            "failed" if not sources or successful_sources == 0
            else "partial" if totals["errors"]
            else "success"
        )
        db.execute(
            "UPDATE job_runs SET finished_at=?, status=?, fetched=?, matched=?, inserted=?, error=? WHERE id=?",
            (now(), status, totals["fetched"], totals["matched"], totals["inserted"],
             "\n".join(totals["errors"]), run_id),
        )
        log_run(
             db,
             run_id,
             "run.completed",
             f"Search run completed with status {status}",
             metadata={
                 "status": status,
                 "fetched": totals["fetched"],
                 "matched": totals["matched"],
                 "inserted": totals["inserted"],
             },
        )
        db.commit()
        totals["status"] = status
        return totals
    except Exception as exc:
        log_run(db, run_id, "run.failed", str(exc), level="error")
        db.execute("UPDATE job_runs SET finished_at=?, status='failed', error=? WHERE id=?", (now(), str(exc), run_id))
        db.commit()
        raise
    finally:
        db.close()
        RUN_LOCK.release()


def check_source_health() -> dict:
    """Check access to every enabled configured source without parsing jobs."""
    db = connect()
    results = []
    try:
        sources = db.execute(
            """SELECT s.*, c.name company_name FROM job_sources s
               JOIN companies c ON c.id=s.company_id
               WHERE s.enabled=1 AND c.enabled=1"""
        ).fetchall()
        for source in sources:
            checked_at = now()
            status = "healthy"
            error = ""
            try:
                if source["source_type"] == "fixture":
                    status = "healthy"
                else:
                    request = urllib.request.Request(
                        source["url"],
                        headers={
                            "User-Agent": "BringMeJobs/0.1",
                            "Accept": "text/html, application/json;q=0.9, */*;q=0.1",
                            "Range": "bytes=0-2048",
                        },
                    )
                    with urllib.request.urlopen(request, timeout=15):
                        pass
            except HTTPError as exc:
                status = "blocked" if exc.code in {401, 403, 429} else "error"
                error = (
                    f"HTTP {exc.code}: source rejected automated access"
                    if status == "blocked"
                    else f"HTTP {exc.code}: health check failed"
                )
            except (URLError, TimeoutError, ValueError) as exc:
                status = "error"
                error = str(exc)
            db.execute(
                """UPDATE job_sources
                   SET health_status=?, health_checked_at=?, health_error=?
                   WHERE id=?""",
                (status, checked_at, error, source["id"]),
            )
            results.append({
                "source_id": source["id"],
                "company_name": source["company_name"],
                "url": source["url"],
                "status": status,
                "checked_at": checked_at,
                "error": error,
            })
        db.commit()
        return {
            "checked": len(results),
            "healthy": sum(item["status"] == "healthy" for item in results),
            "blocked": sum(item["status"] == "blocked" for item in results),
            "errors": sum(item["status"] == "error" for item in results),
            "sources": results,
        }
    finally:
        db.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_static(self, name: str, content_type: str) -> None:
        path = STATIC / name
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send_static("index.html", "text/html; charset=utf-8")
        if self.path in ("/config", "/config.html"):
            return self.send_static("config.html", "text/html; charset=utf-8")
        if self.path == "/app.js":
            return self.send_static("app.js", "text/javascript; charset=utf-8")
        if self.path == "/styles.css":
            return self.send_static("styles.css", "text/css; charset=utf-8")
        db = connect()
        try:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/companies":
                rows = db.execute(
                    """SELECT c.*, COUNT(DISTINCT j.id) job_count,
                       (SELECT json_group_array(json_object('id', s.id, 'url', s.url,
                        'source_type', s.source_type, 'enabled', s.enabled,
                        'last_status', s.last_status, 'last_error', s.last_error,
                        'health_status', s.health_status,
                        'health_checked_at', s.health_checked_at,
                        'health_error', s.health_error))
                        FROM job_sources s WHERE s.company_id=c.id) sources
                       FROM companies c LEFT JOIN jobs j ON j.company_id=c.id
                       GROUP BY c.id ORDER BY c.name"""
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["sources"] = json.loads(item["sources"] or "[]")
                    result.append(item)
                return json_response(self, result)
            if parsed.path == "/api/jobs":
                query = "SELECT j.*, c.name company_name, s.url source_url FROM jobs j JOIN companies c ON c.id=j.company_id JOIN job_sources s ON s.id=j.source_id"
                params = []
                status = urllib.parse.parse_qs(parsed.query).get("status", [""])[0]
                if status:
                    query += " WHERE j.status=?"
                    params.append(status)
                query += " ORDER BY j.score DESC, j.posted_at DESC"
                rows = db.execute(query, params).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["match_reasons"] = json.loads(item["match_reasons"])
                    result.append(item)
                return json_response(self, result)
            if parsed.path == "/api/runs":
                return json_response(self, [dict(r) for r in db.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 20")])
            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/logs"):
                run_id = int(parsed.path.split("/")[3])
                rows = db.execute(
                    """SELECT id, run_id, logged_at, step, level, message, metadata
                       FROM job_run_logs WHERE run_id=? ORDER BY id""",
                    (run_id,),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["metadata"] = json.loads(item["metadata"])
                    result.append(item)
                return json_response(self, result)
            if parsed.path == "/api/config":
                return json_response(self, dict(db.execute("SELECT * FROM search_config WHERE id=1").fetchone()))
            if parsed.path == "/api/sources":
                return json_response(self, [dict(r) for r in db.execute(
                    "SELECT s.*, c.name company_name FROM job_sources s JOIN companies c ON c.id=s.company_id ORDER BY c.name"
                )])
            self.send_error(404)
        finally:
            db.close()

    def do_POST(self):
        try:
            payload = read_json(self)
            db = connect()
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/search":
                db.close()
                return json_response(self, run_search(bool(payload.get("dry_run"))))
            if path == "/api/sources/health":
                db.close()
                return json_response(self, check_source_health())
            if path.startswith("/api/jobs/") and path.endswith("/status"):
                jid = path.split("/")[3]
                status = payload.get("status")
                if status not in {"new", "reviewed", "saved", "rejected", "archived"}:
                    raise ValueError("invalid status")
                if not db.execute("SELECT 1 FROM jobs WHERE id=?", (jid,)).fetchone():
                    raise ValueError("job not found")
                db.execute("UPDATE jobs SET status=? WHERE id=?", (status, jid))
                db.execute("INSERT INTO job_status_history(job_id, status, changed_at) VALUES(?,?,?)", (jid, status, now()))
                db.commit()
                db.close()
                return json_response(self, {"ok": True})
            if path.startswith("/api/companies/") and path != "/api/companies/save":
                cid = int(path.split("/")[3])
                fields = {
                    "careers_url": str(payload.get("careers_url", "")),
                    "locations": str(payload.get("locations", "")),
                    "notes": str(payload.get("notes", "")),
                    "enabled": int(bool(payload.get("enabled", True))),
                }
                db.execute("UPDATE companies SET careers_url=?, locations=?, notes=?, enabled=? WHERE id=?",
                           (*fields.values(), cid))
                if fields["careers_url"]:
                    db.execute(
                        """INSERT INTO job_sources(company_id, source_type, url) VALUES(?, 'careers', ?)
                           ON CONFLICT(company_id, url) DO UPDATE SET source_type='careers', enabled=1""",
                        (cid, fields["careers_url"]),
                    )
                db.commit()
                db.close()
                return json_response(self, {"ok": True})
            if path == "/api/companies/save":
                companies = payload.get("companies")
                deleted_ids = [int(value) for value in payload.get("deleted_ids", [])]
                if not isinstance(companies, list):
                    raise ValueError("companies must be an array")
                db.execute("BEGIN")
                for company in companies:
                    name = str(company.get("name", "")).strip()
                    if not name:
                        raise ValueError("company name is required")
                    company_id = company.get("id")
                    values = (
                        name, str(company.get("careers_url", "")).strip(),
                        str(company.get("locations", "")).strip(),
                        int(bool(company.get("enabled", True))),
                        str(company.get("notes", "")).strip(),
                    )
                    if company_id:
                        db.execute(
                            """UPDATE companies SET name=?, careers_url=?, locations=?, enabled=?, notes=?
                               WHERE id=?""",
                            (*values, int(company_id)),
                        )
                    else:
                        cursor = db.execute(
                            """INSERT INTO companies(name, careers_url, locations, enabled, notes, created_at)
                               VALUES(?,?,?,?,?,?)""",
                            (*values, now()),
                        )
                        company_id = cursor.lastrowid
                    source_url = str(company.get("source_url") or values[1]).strip()
                    source_type = str(company.get("source_type") or "careers")
                    if source_url:
                        db.execute(
                            """INSERT INTO job_sources(company_id, source_type, url, enabled)
                               VALUES(?,?,?,?)
                               ON CONFLICT(company_id, url) DO UPDATE SET source_type=excluded.source_type,
                               enabled=excluded.enabled""",
                            (company_id, source_type, source_url, values[3]),
                        )
                    else:
                        db.execute("UPDATE job_sources SET enabled=0 WHERE company_id=?", (company_id,))
                if deleted_ids:
                    db.executemany("DELETE FROM companies WHERE id=?", [(value,) for value in deleted_ids])
                if any(
                    str(company.get("source_url") or company.get("careers_url") or "").strip()
                    and str(company.get("source_type") or "careers") != "fixture"
                    for company in companies
                ):
                    db.execute("UPDATE job_sources SET enabled=0 WHERE source_type='fixture'")
                db.commit()
                db.close()
                return json_response(self, {"ok": True})
            if path == "/api/sources":
                company_id = int(payload["company_id"])
                source_type = str(payload.get("source_type", "json"))
                url = str(payload["url"])
                db.execute("INSERT INTO job_sources(company_id, source_type, url) VALUES(?,?,?)",
                           (company_id, source_type, url))
                db.commit()
                db.close()
                return json_response(self, {"ok": True}, HTTPStatus.CREATED)
            if path == "/api/config":
                db.execute(
                    "UPDATE search_config SET locations=?, role_terms=?, excluded_terms=?, max_age_days=?, schedule=? WHERE id=1",
                    (str(payload.get("locations", "")), str(payload.get("role_terms", "")),
                     str(payload.get("excluded_terms", "")), int(payload.get("max_age_days", 30)),
                     str(payload.get("schedule", "00:00"))),
                )
                db.commit()
                db.close()
                return json_response(self, {"ok": True})
            db.close()
            self.send_error(404)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def ensure_fixture_source(db: sqlite3.Connection) -> None:
    if db.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0]:
        return
    company = db.execute("SELECT id FROM companies WHERE name='Palantir'").fetchone()
    db.execute("INSERT INTO job_sources(company_id, source_type, url) VALUES(?, 'fixture', 'fixture://jobs')", (company["id"],))
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="BringMeJobs local job discovery MVP")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("migrate")
    search = sub.add_parser("search")
    search.add_argument("--dry-run", action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("serve")
    args = parser.parse_args()
    db = connect()
    migrate(db)
    if args.command == "migrate":
        print(f"Database ready: {DB_PATH}")
    elif args.command == "doctor":
        ensure_fixture_source(db)
        print(json.dumps({"database": str(DB_PATH), "companies": db.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
                          "sources": db.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0]}, indent=2))
    elif args.command == "search":
        ensure_fixture_source(db)
        db.close()
        print(json.dumps(run_search(args.dry_run), indent=2))
    else:
        ensure_fixture_source(db)
        db.close()
        print(f"BringMeJobs listening on http://{HOST}:{PORT}")
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    if not db is None:
        db.close()


if __name__ == "__main__":
    main()
