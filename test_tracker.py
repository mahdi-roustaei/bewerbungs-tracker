import csv
import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from main import create_app

HEADERS = {"X-Requested-With": "BewerbungsTracker"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.sqlite3"), headers=HEADERS) as value:
        yield value


def create(client, **overrides):
    response = client.post(
        "/api/applications",
        json={"company": "Musterwerk", "role": "Werkstudent Backend", **overrides},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_read_and_persistence(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(path), headers=HEADERS) as first:
        record = create(first, company="  Übermorgen GmbH  ", notes="Grüße 👋")
        assert record["company"] == "Übermorgen GmbH"
        assert first.get(f"/api/applications/{record['id']}").json()["notes"] == "Grüße 👋"
    with TestClient(create_app(path)) as second:
        assert second.get("/api/applications").json()[0]["id"] == record["id"]


def test_status_history_records_only_status_changes(client):
    record = create(client)
    path = f"/api/applications/{record['id']}"
    payload = {"company": "Musterwerk", "role": "Backend", "status": "interview"}
    assert client.put(path, json=payload).status_code == 200
    assert client.put(path, json={**payload, "notes": "Termin bestätigt"}).status_code == 200
    history = client.get(path + "/history").json()
    assert [(h["previous_status"], h["status"]) for h in history] == [
        (None, "saved"),
        ("saved", "interview"),
    ]


def test_archive_restore_filters_and_statistics(client):
    record = create(client, status="interview")
    path = f"/api/applications/{record['id']}/archive"
    assert client.patch(path, json={"archived": True}).json()["archived"] is True
    assert client.get("/api/applications").json() == []
    assert client.get("/api/stats").json()["total"] == 0
    assert len(client.get("/api/applications?archived=true").json()) == 1
    assert client.patch(path, json={"archived": False}).status_code == 200
    assert client.get("/api/stats").json()["by_status"]["interview"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"company": " "},
        {"role": ""},
        {"status": "hired"},
        {"company": "x" * 121},
        {"notes": "x" * 5001},
        {"surprise": True},
        {"job_url": "javascript:alert(1)"},
        {"job_url": "file:///etc/passwd"},
        {"job_url": "https://user:secret@example.com"},
        {"applied_on": "2026-02-30"},
    ],
)
def test_invalid_input_rejected(client, payload):
    result = client.post(
        "/api/applications", json={"company": "Example", "role": "Developer", **payload}
    )
    assert result.status_code == 422
    assert client.get("/api/applications").json() == []


def test_search_status_filter_and_literal_sql_characters(client):
    create(client, company="Example 100%", location="Hannover", status="applied")
    create(client, company="Other", status="saved")
    assert (
        len(client.get("/api/applications", params={"q": "hannover", "status": "applied"}).json())
        == 1
    )
    assert len(client.get("/api/applications", params={"q": "%"}).json()) == 1
    assert client.get("/api/applications", params={"q": "' OR 1=1 --"}).json() == []
    assert client.get("/api/applications?status=invalid").status_code == 422


def test_due_dates_exclude_closed_future_and_archived(client):
    today = date.today()
    create(client, follow_up_on=today.isoformat(), status="applied")
    create(client, follow_up_on=(today - timedelta(days=1)).isoformat(), status="interview")
    create(client, follow_up_on=(today + timedelta(days=1)).isoformat())
    create(client, follow_up_on=today.isoformat(), status="rejected")
    archived = create(client, follow_up_on=today.isoformat())
    client.patch(f"/api/applications/{archived['id']}/archive", json={"archived": True})
    assert len(client.get("/api/applications?due=true").json()) == 2
    stats = client.get("/api/stats").json()
    assert stats["follow_ups_due"] == 2
    assert stats["total"] == 4


def test_csv_preserves_unicode_quotes_and_neutralizes_formulas(client):
    create(client, company='=HYPERLINK("evil")', notes="Grüße, Welt\nZeile zwei", role="+SUM(1,2)")
    response = client.get("/api/export.csv")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert rows[0]["company"].startswith("'=")
    assert rows[0]["role"].startswith("'+")
    assert rows[0]["notes"] == "Grüße, Welt\nZeile zwei"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/applications/999", None),
        ("get", "/api/applications/999/history", None),
        ("put", "/api/applications/999", {"company": "X", "role": "Y"}),
        ("patch", "/api/applications/999/archive", {"archived": True}),
    ],
)
def test_missing_records_are_404(client, method, path, body):
    assert client.request(method, path, **({"json": body} if body else {})).status_code == 404


def test_browser_write_protection_and_host_validation(client):
    payload = {"company": "Example", "role": "Developer"}
    assert (
        client.post("/api/applications", json=payload, headers={"X-Requested-With": ""}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/applications", json=payload, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/applications", json=payload, headers={"Origin": "http://testserver"}
        ).status_code
        == 201
    )
    assert client.get("/api/applications", headers={"Host": "evil.example"}).status_code == 400


def test_shell_assets_and_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
    response = client.get("/")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "Deine Bewerbungen" in response.text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/database.py").status_code == 404


def test_failed_update_keeps_original_and_history(client):
    record = create(client)
    path = f"/api/applications/{record['id']}"
    assert (
        client.put(path, json={"company": "X", "role": "Y", "status": "invalid"}).status_code == 422
    )
    assert client.get(path).json()["status"] == "saved"
    assert len(client.get(path + "/history").json()) == 1
