"""Tests for dev vs frozen path resolution."""
from __future__ import annotations

from app import paths


def test_dev_paths_use_backend_data():
    assert not paths.is_frozen()
    assert paths.data_dir().name == "data"
    assert paths.data_dir().parent.name == "backend"
    assert paths.frontend_dist_dir().name == "dist"
    assert paths.frontend_dist_dir().parent.name == "frontend"
