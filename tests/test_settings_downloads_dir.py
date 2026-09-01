"""Where the watcher looks. One setting, detected by default."""
from __future__ import annotations

import pathlib

from research_companion.settings import DEFAULTS, default_downloads_dir


def test_the_setting_exists_and_defaults_to_detection():
    assert DEFAULTS["downloads_dir"] == ""


def test_detection_returns_an_absolute_path():
    p = default_downloads_dir()
    assert p == "" or pathlib.Path(p).is_absolute()


def test_detection_never_raises(monkeypatch):
    monkeypatch.setenv("USERPROFILE", "")
    monkeypatch.setenv("HOME", "")
    assert isinstance(default_downloads_dir(), str)


def test_the_setting_round_trips(tmp_path):
    from research_companion.settings import get_settings, update_settings
    update_settings({"downloads_dir": str(tmp_path)})
    assert get_settings()["downloads_dir"] == str(tmp_path)
