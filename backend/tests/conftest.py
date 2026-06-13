import os
import sys
from pathlib import Path

import pytest

# Make the backend package importable when running pytest from repo root.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

GUIDE = BACKEND.parent / "Guides" / "SocialScienceRG_Transportation.pdf"


@pytest.fixture(autouse=True)
def _isolated_test_db(tmp_path, monkeypatch):
    """Never write pytest fixtures into the developer's real acdec.db."""
    db_path = tmp_path / "test_acdec.db"
    monkeypatch.setattr("app.config.DB_PATH", db_path)
    monkeypatch.setattr("app.db.database.DB_PATH", db_path)
    from app.db.database import init_db

    init_db()


@pytest.fixture(scope="session")
def blueprint():
    if not GUIDE.exists():
        pytest.skip(f"sample guide not found at {GUIDE}")
    from app.parsing.structure import build_blueprint, collapse_duplicate_singletons
    from app.parsing.captions import attach_captions
    from app.parsing.navigation import strip_guide_navigation

    doc, sections = build_blueprint(str(GUIDE))
    attach_captions(doc, sections)
    for sec in sections:
        if sec.body_text:
            sec.body_text = strip_guide_navigation(sec.body_text)
        for sub in sec.subheaders:
            if sub.body_text:
                sub.body_text = strip_guide_navigation(sub.body_text)
    collapse_duplicate_singletons(sections)
    return doc, sections
