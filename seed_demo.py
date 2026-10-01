"""Opt-in fictional examples. Refuses to touch a nonempty database."""

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

from database import connect, initialize
from main import timestamp


def seed(path):
    initialize(path)
    today = date.today()
    examples = [
        ("Musterwerk GmbH", "Werkstudent Backend", "Hannover · Hybrid", "interview", 8, 0),
        (
            "Nordlicht Digital (Demo)",
            "Python Developer · Werkstudent",
            "Hamburg · Remote",
            "applied",
            5,
            2,
        ),
        ("Fiktiv Labs", "Werkstudent Data Engineering", "Berlin · Hybrid", "saved", None, 3),
        ("Beispiel & Partner", "IT Support · Werkstudent", "Hannover", "offer", 16, None),
        ("Demo Cloud Studio", "Junior Software Developer", "Remote", "rejected", 20, None),
        (
            "Morgenrot Systems (Demo)",
            "Werkstudent Softwareentwicklung",
            "Braunschweig",
            "applied",
            12,
            -2,
        ),
    ]
    with connect(path) as connection:
        # Acquire the writer lock before checking: two seed processes cannot race.
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]:
            raise SystemExit("Database is not empty; no demo data added.")
        for company, role, location, status, applied, follow_up in examples:
            now = timestamp()
            cursor = connection.execute(
                "INSERT INTO applications(company,role,location,status,applied_on,follow_up_on,"
                "notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    company,
                    role,
                    location,
                    status,
                    (today - timedelta(days=applied)).isoformat() if applied is not None else None,
                    (today + timedelta(days=follow_up)).isoformat()
                    if follow_up is not None
                    else None,
                    "Fiktiver Beispieldatensatz – keine echte Bewerbung.",
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO status_history(application_id,status,changed_at) VALUES(?,?,?)",
                (cursor.lastrowid, status, now),
            )
    print("Added six fictional applications.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=os.getenv("TRACKER_DB", str(Path(__file__).parent / "data/tracker.sqlite3"))
    )
    seed(parser.parse_args().db)
