"""Tests for Google Sheet export."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.config import ProviderConfig, load_config, save_config
from app.export.google_sheets import cards_to_sheet_values, create_spreadsheet
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    return TestClient(app)


def test_cards_to_sheet_values_no_header():
    cards = [{"front": "Q?", "back": "A", "tag": "other"}]
    assert cards_to_sheet_values(cards) == [["Q?", "A", "other"]]


@patch("app.export.google_sheets.get_google_credentials")
@patch("app.export.google_sheets.build")
def test_create_spreadsheet_writes_rows(mock_build, mock_creds):
    service = MagicMock()
    mock_build.return_value = service
    service.spreadsheets().create().execute.return_value = {
        "spreadsheetId": "abc123",
        "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/abc123",
    }
    service.spreadsheets().values().update().execute.return_value = {}

    url = create_spreadsheet(
        "Social_Science_TextOnly.csv",
        [{"front": "Q", "back": "A", "tag": "date"}],
    )
    assert url.endswith("abc123")
    update_call = service.spreadsheets().values().update
    assert update_call.called
    body = update_call.call_args.kwargs["body"]
    assert body["values"] == [["Q", "A", "date"]]


def _seed_validated_subheader(conn):
    sid = conn.execute(
        "INSERT INTO subjects (name, filename, pdf_path, status) "
        "VALUES ('T', 't.pdf', 'x', 'approved')"
    ).lastrowid
    nid = conn.execute(
        "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
        "VALUES (?, NULL, 'section', 'S', 'BODY', 0)",
        (sid,),
    ).lastrowid
    conn.execute(
        "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
        "VALUES (?, 'Q', 'A', 'other', 'A', 'h', 'ai')",
        (nid,),
    )
    conn.execute(
        "UPDATE nodes SET validated_at = datetime('now') WHERE id = ?", (nid,)
    )
    return sid, nid


def test_export_node_sheet_requires_google_connection(client):
    save_config(ProviderConfig(text_export_format="google_sheet"))
    from app.db.database import get_conn, init_db

    init_db()
    with get_conn() as conn:
        _, nid = _seed_validated_subheader(conn)

    res = client.post(f"/api/nodes/{nid}/export")
    assert res.status_code == 401

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = (SELECT subject_id FROM nodes WHERE id = ?)", (nid,))


@patch("app.main.create_spreadsheet", return_value="https://docs.google.com/spreadsheets/d/x")
def test_export_node_sheet_success(mock_create, client):
    save_config(
        ProviderConfig(
            text_export_format="google_sheet",
            google_client_id="client-id",
            google_refresh_token="refresh-token",
        )
    )
    from app.db.database import get_conn, init_db

    init_db()
    with get_conn() as conn:
        _, nid = _seed_validated_subheader(conn)

    res = client.post(f"/api/nodes/{nid}/export")
    assert res.status_code == 200
    assert res.json()["url"].startswith("https://docs.google.com")
    mock_create.assert_called_once()

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = (SELECT subject_id FROM nodes WHERE id = ?)", (nid,))


def test_export_node_sheet_requires_validation(client):
    save_config(
        ProviderConfig(
            text_export_format="google_sheet",
            google_refresh_token="token",
            google_client_id="id",
        )
    )
    from app.db.database import get_conn, init_db

    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        nid = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'S', 'BODY', 0)",
            (sid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q', 'A', 'other', 'A', 'h', 'ai')",
            (nid,),
        )

    res = client.post(f"/api/nodes/{nid}/export")
    assert res.status_code == 403

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
