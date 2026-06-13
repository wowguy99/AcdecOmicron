"""Tests for subject export/import archives."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.transfer import MANIFEST_NAME, PDF_NAME, export_subject, import_subject


def _seed_subject(tmp_path, monkeypatch, name: str = "Test Subject") -> int:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr("app.config.UPLOAD_DIR", upload_dir)
    monkeypatch.setattr("app.transfer.UPLOAD_DIR", upload_dir)

    pdf_path = upload_dir / "guide.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test content")

    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status) "
            "VALUES (?, 'guide.pdf', ?, 2, 'done')",
            (name, str(pdf_path)),
        ).lastrowid
        conn.execute(
            "INSERT INTO tags (subject_id, name, definition, builtin) "
            "VALUES (?, 'date', 'A date', 0), (?, 'other', 'fallback', 1)",
            (sid, sid),
        )
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text, excluded, validated_at) "
            "VALUES (?, NULL, 'section', 'INTRODUCTION', 'INTRODUCTION', 0, 'body', 0, datetime('now'))",
            (sid,),
        ).lastrowid
        sub_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text, excluded) "
            "VALUES (?, ?, 'subheader', 'Topic A', 'INTRODUCTION', 0, 'sub body', 0)",
            (sid, sec_id),
        ).lastrowid
        chunk_id = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 0, 'A', 'chunk text', 'done')",
            (sec_id,),
        ).lastrowid
        card_id = conn.execute(
            "INSERT INTO cards (node_id, chunk_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, ?, 'Q?', 'A!', 'date', 'A', 'hash1', 'ai')",
            (sec_id, chunk_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO jobs (subject_id, status, message, total, completed) "
            "VALUES (?, 'done', 'ok', 1, 1)",
            (sid,),
        )
        conn.execute(
            "INSERT INTO validation_progress (validation_node_id, card_id, track) "
            "VALUES (?, ?, 'master')",
            (sec_id, card_id),
        )
    return sid


def test_export_import_round_trip(tmp_path, monkeypatch):
    sid = _seed_subject(tmp_path, monkeypatch)
    archive, filename = export_subject(sid)
    assert filename.endswith(".acdec-subject.zip")

    import zipfile
    import io
    import json

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert MANIFEST_NAME in zf.namelist()
        assert PDF_NAME in zf.namelist()
        manifest = json.loads(zf.read(MANIFEST_NAME))
        assert manifest["format_version"] == 1
        assert len(manifest["cards"]) == 1
        assert manifest["cards"][0]["front"] == "Q?"

    new_id, new_name = import_subject(archive)
    assert new_id != sid
    assert new_name == "Test Subject (imported)"

    with get_conn() as conn:
        cards = conn.execute(
            "SELECT front, back FROM cards WHERE node_id IN "
            "(SELECT id FROM nodes WHERE subject_id = ?) AND deleted = 0",
            (new_id,),
        ).fetchall()
        assert len(cards) == 1
        assert cards[0]["front"] == "Q?"
        assert cards[0]["back"] == "A!"
        sub = conn.execute("SELECT pdf_path FROM subjects WHERE id = ?", (new_id,)).fetchone()
        assert Path(sub["pdf_path"]).is_file()
        vp = conn.execute(
            "SELECT COUNT(*) c FROM validation_progress vp "
            "JOIN nodes n ON n.id = vp.validation_node_id WHERE n.subject_id = ?",
            (new_id,),
        ).fetchone()
        assert vp["c"] == 1


def test_export_missing_subject():
    init_db()
    with pytest.raises(KeyError):
        export_subject(999999)


def test_import_duplicate_name_suffix(tmp_path, monkeypatch):
    sid = _seed_subject(tmp_path, monkeypatch, name="Art")
    archive, _ = export_subject(sid)
    _, name1 = import_subject(archive)
    assert name1 == "Art (imported)"
    _, name2 = import_subject(archive)
    assert name2 == "Art (imported 2)"
