"""Small SQLite repository. Each operation owns and closes its connection."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN
        ('saved','applied','interview','offer','rejected','withdrawn')),
    job_url TEXT,
    applied_on TEXT,
    follow_up_on TEXT,
    notes TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    previous_status TEXT,
    status TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(archived,status);
CREATE INDEX IF NOT EXISTS idx_history_application ON status_history(application_id,id);
PRAGMA user_version = 1;
"""


@contextmanager
def connect(path: str | Path):
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path: str | Path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError(f"Unsupported database version: {version}")
        connection.executescript(SCHEMA)


def filters(query="", status=None, archived=False, due=None):
    clauses, values = ["archived = ?"], [int(archived)]
    if query:
        # instr treats percent and underscore as literal search characters.
        clauses.append(
            "(instr(lower(company),lower(?)) > 0 OR "
            "instr(lower(role),lower(?)) > 0 OR "
            "instr(lower(location),lower(?)) > 0)"
        )
        values.extend([query] * 3)
    if status:
        clauses.append("status = ?")
        values.append(status.value)
    if due:
        clauses.append("follow_up_on <= ? AND status IN ('saved','applied','interview')")
        values.append(due)
    return " AND ".join(clauses), values
