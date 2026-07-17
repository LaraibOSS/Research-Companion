"""Lab HTTP-server security: DNS-rebinding Host allowlist + upload CSRF guard."""
from fastapi.testclient import TestClient

from research_companion.agents.bus import Bus
from research_companion.lab_api import create_lab_app

_PDF = b"%PDF-1.4 minimal test body"


def _client():
    return TestClient(create_lab_app(Bus()))


def test_loopback_host_is_allowed():
    # TestClient's default Host is "testserver" (in the allowlist).
    assert _client().get("/api/lab").status_code == 200


def test_foreign_host_is_rejected_dns_rebinding():
    r = _client().get("/api/lab", headers={"host": "evil.attacker.example"})
    assert r.status_code == 400  # TrustedHostMiddleware


def test_upload_requires_pdf_content_type():
    r = _client().post("/api/papers/upload?filename=x.pdf", content=_PDF,
                       headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_upload_accepts_pdf_content_type():
    # application/pdf passes the CSRF guard (real frontend sends this).
    r = _client().post("/api/papers/upload?filename=x.pdf", content=_PDF,
                       headers={"Content-Type": "application/pdf"})
    assert r.status_code == 202
