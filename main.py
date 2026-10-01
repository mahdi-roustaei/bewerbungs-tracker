"""Local-first job application tracker with a same-origin browser client."""

import csv
import io
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from database import connect, filters, initialize
from models import Application, ApplicationInput, ArchiveInput, HistoryEntry, Status

ROOT = Path(__file__).parent


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def safe_csv(value):
    """Prevent spreadsheet formula interpretation, including leading whitespace."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def create_app(db_path=None):
    path = Path(db_path or os.getenv("TRACKER_DB", ROOT / "data" / "tracker.sqlite3"))

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield

    app = FastAPI(title="Bewerbungs-Tracker API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def browser_protection(request: Request, call_next):
        # A cross-origin site cannot send this header without a CORS preflight.
        # No CORS access is granted. Also reject explicit cross-origin writes.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if request.headers.get("x-requested-with") != "BewerbungsTracker":
                return JSONResponse(
                    {"detail": "Missing request verification header"}, status_code=403
                )
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "Cross-origin writes are not allowed"}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        return response

    def get_record(connection, identifier):
        row = connection.execute("SELECT * FROM applications WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise HTTPException(404, "Application not found")
        return dict(row)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "index.html")

    @app.get("/assets/{name}", include_in_schema=False)
    def asset(name: str):
        if name not in {"app.js", "styles.css"}:
            raise HTTPException(404)
        return FileResponse(ROOT / name)

    @app.get("/api/health")
    def health():
        with connect(path) as connection:
            connection.execute("SELECT 1 FROM applications LIMIT 1")
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/api/applications", response_model=list[Application])
    def list_applications(
        q: Annotated[str, Query(max_length=160)] = "",
        status: Status | None = None,
        archived: bool = False,
        due: bool = False,
    ):
        where, values = filters(q, status, archived, date.today().isoformat() if due else None)
        with connect(path) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM applications WHERE {where} ORDER BY updated_at DESC,id DESC",
                    values,
                )
            ]

    @app.get("/api/stats")
    def stats():
        with connect(path) as connection:
            counts = {item.value: 0 for item in Status}
            for row in connection.execute(
                "SELECT status,COUNT(*) AS count FROM applications WHERE archived=0 GROUP BY status"
            ):
                counts[row["status"]] = row["count"]
            due = connection.execute(
                "SELECT COUNT(*) FROM applications WHERE archived=0 AND follow_up_on<=? "
                "AND status IN ('saved','applied','interview')",
                (date.today().isoformat(),),
            ).fetchone()[0]
        return {"total": sum(counts.values()), "by_status": counts, "follow_ups_due": due}

    @app.get("/api/export.csv")
    def export_csv():
        output = io.StringIO(newline="")
        fields = [
            "id",
            "company",
            "role",
            "location",
            "status",
            "job_url",
            "applied_on",
            "follow_up_on",
            "notes",
            "archived",
            "created_at",
            "updated_at",
        ]
        writer = csv.writer(output)
        writer.writerow(fields)
        with connect(path) as connection:
            for row in connection.execute("SELECT * FROM applications ORDER BY id"):
                writer.writerow([safe_csv(row[field]) for field in fields])
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="bewerbungen.csv"'},
        )

    @app.post("/api/applications", response_model=Application, status_code=201)
    def create_application(payload: ApplicationInput):
        data = payload.model_dump(mode="json")
        now = timestamp()
        with connect(path) as connection:
            cursor = connection.execute(
                "INSERT INTO applications(company,role,location,status,job_url,applied_on,"
                "follow_up_on,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (*data.values(), now, now),
            )
            connection.execute(
                "INSERT INTO status_history(application_id,previous_status,status,changed_at) "
                "VALUES(?,NULL,?,?)",
                (cursor.lastrowid, data["status"], now),
            )
            return get_record(connection, cursor.lastrowid)

    @app.get("/api/applications/{identifier}", response_model=Application)
    def read_application(identifier: int):
        with connect(path) as connection:
            return get_record(connection, identifier)

    @app.put("/api/applications/{identifier}", response_model=Application)
    def update_application(identifier: int, payload: ApplicationInput):
        data = payload.model_dump(mode="json")
        now = timestamp()
        with connect(path) as connection:
            previous = get_record(connection, identifier)
            connection.execute(
                "UPDATE applications SET company=?,role=?,location=?,status=?,job_url=?,"
                "applied_on=?,follow_up_on=?,notes=?,updated_at=? WHERE id=?",
                (*data.values(), now, identifier),
            )
            if previous["status"] != data["status"]:
                connection.execute(
                    "INSERT INTO status_history(application_id,previous_status,status,changed_at) "
                    "VALUES(?,?,?,?)",
                    (identifier, previous["status"], data["status"], now),
                )
            return get_record(connection, identifier)

    @app.patch("/api/applications/{identifier}/archive", response_model=Application)
    def archive_application(identifier: int, payload: ArchiveInput):
        with connect(path) as connection:
            get_record(connection, identifier)
            connection.execute(
                "UPDATE applications SET archived=?,updated_at=? WHERE id=?",
                (int(payload.archived), timestamp(), identifier),
            )
            return get_record(connection, identifier)

    @app.get("/api/applications/{identifier}/history", response_model=list[HistoryEntry])
    def history(identifier: int):
        with connect(path) as connection:
            get_record(connection, identifier)
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id,previous_status,status,changed_at FROM status_history "
                    "WHERE application_id=? ORDER BY id",
                    (identifier,),
                )
            ]

    return app


app = create_app()
