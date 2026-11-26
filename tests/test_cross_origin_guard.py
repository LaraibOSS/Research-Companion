"""The Lab has no login, so "local" must mean "from the Lab's own page".

A page on any other origin can make the browser send a request to
http://127.0.0.1:<port>. Several endpoints start paid model calls or change
state with no request body, so they were reachable that way. These pin the
guard, and pin that it does not get in the way of the Lab itself, the CLI or
a plain link to the page.
"""
from __future__ import annotations

import pytest

from research_companion.lab_api import cross_origin_rejection

HOST = "127.0.0.1:8765"


def _check(**kw):
    base = {"path": "/api/gaps/refresh", "host": HOST, "origin": None, "sec_fetch_site": None}
    base.update(kw)
    return cross_origin_rejection(**base)


@pytest.mark.parametrize("origin", [
    "https://evil.example",
    "http://evil.example",
    "http://localhost:3000",          # another local web app is still another origin
    "http://127.0.0.1:9999",
    "http://127.0.0.1:8765.evil.example",
    "null",                           # sandboxed iframe / file:// page
])
def test_another_origin_is_refused(origin):
    assert _check(origin=origin) is not None


def test_the_labs_own_origin_is_allowed():
    assert _check(origin="http://127.0.0.1:8765", sec_fetch_site="same-origin") is None
    assert _check(origin="HTTP://127.0.0.1:8765") is None


def test_non_browser_clients_are_allowed():
    # curl, the CLI, the test client and MCP hosts send neither header.
    assert _check() is None


def test_cross_site_without_origin_is_refused():
    # <img src="http://127.0.0.1:8765/api/discover?expand=1"> carries no Origin.
    assert _check(path="/api/discover", sec_fetch_site="cross-site") is not None


def test_a_link_to_the_page_still_works():
    # Following a link from another site to the Lab is cross-site navigation
    # to a non-API path; it must not be blocked.
    assert _check(path="/", sec_fetch_site="cross-site", origin=None) is None
    assert _check(path="/static/js/main.js", sec_fetch_site="cross-site") is None


def test_endpoints_refuse_a_cross_origin_post(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient

    from research_companion.agents.bus import Bus
    from research_companion.lab_api import create_lab_app

    monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_COMPANION_WORKSPACE", "guard")
    client = TestClient(create_lab_app(Bus()))
    hostile = client.post("/api/gaps/refresh", headers={"Origin": "https://evil.example"})
    assert hostile.status_code == 403
    assert hostile.json()["error"] == "cross_origin_rejected"
    # The same request from the Lab's own page is not refused by the guard.
    own = client.post("/api/gaps/refresh", headers={"Origin": "http://testserver"})
    assert own.status_code != 403
