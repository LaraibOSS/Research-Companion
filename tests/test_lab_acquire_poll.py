"""GET /api/acquire/status polls the watcher and acts on what it catches.

Task 10C: ArmedWatcher.poll() previously had no caller anywhere outside its
own tests -- arming worked, the countdown ran, and no downloaded file was
ever caught. The status endpoint is the natural tick (the UI already polls
it to render the countdown), so it calls poll() first and then, for each
caught file: saves it against its paper and re-runs the retry-flow re-ingest
when matched, or reports-and-leaves-alone when it isn't.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from research_companion.agents.bus import Bus
from research_companion.lab_api import create_lab_app


@pytest.fixture
def lab_client():
    """Mirrors _make_client in tests/test_lab_api.py. Workspace isolation is
    autouse via conftest.isolated_papergraph_dir."""
    return TestClient(create_lab_app(Bus()))


def _arm_with_directory(app, tmp_path, paper_ids, queued=()):
    """Point the watcher at a controlled tmp directory and arm it directly
    (bypassing POST /api/acquire/arm, which re-resolves the directory from
    settings and would clobber this)."""
    app.state.watcher.directory = tmp_path
    app.state.watcher.arm(paper_ids, ttl=600, queued=queued)


def _wait_for_job(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job.get("status") != "running":
            return job
        time.sleep(0.05)
    return job


def test_matched_file_is_saved_against_its_paper(lab_client, tmp_path, fake_pdf_bytes):
    from research_companion import store

    paper_id = "doi:10.1145/3676641.3716025"
    queued = [{"paper_id": paper_id, "title": "TAPAS"}]
    _arm_with_directory(lab_client.app, tmp_path, [paper_id], queued=queued)

    async def fast_retry(path, pid, bus):
        pass

    lab_client.app.state.retry_override = fast_retry

    (tmp_path / "3676641.3716025.pdf").write_bytes(fake_pdf_bytes)

    r1 = lab_client.get("/api/acquire/status")
    assert r1.status_code == 200
    assert r1.json()["matched"] == []
    assert r1.json()["unmatched"] == []

    r2 = lab_client.get("/api/acquire/status")
    body = r2.json()
    assert len(body["matched"]) == 1
    entry = body["matched"][0]
    assert entry["paper_id"] == paper_id
    assert entry["filename"] == "3676641.3716025.pdf"
    assert body["unmatched"] == []

    saved = store.pdf_path(paper_id)
    assert saved is not None
    assert saved.read_bytes() == fake_pdf_bytes


def test_matched_file_clears_the_failure_record(lab_client, tmp_path, fake_pdf_bytes):
    from research_companion import store

    paper_id = "doi:10.1145/3676641.3716025"
    store.record_failure(paper_id, {"stage": "add", "error": "no pdf",
                                    "paper_id": paper_id})
    queued = [{"paper_id": paper_id, "title": "TAPAS"}]
    _arm_with_directory(lab_client.app, tmp_path, [paper_id], queued=queued)

    async def fast_retry(path, pid, bus):
        pass

    lab_client.app.state.retry_override = fast_retry

    (tmp_path / "3676641.3716025.pdf").write_bytes(fake_pdf_bytes)
    lab_client.get("/api/acquire/status")
    body = lab_client.get("/api/acquire/status").json()
    job_id = body["matched"][0]["job_id"]

    job = _wait_for_job(lab_client, job_id)
    assert job["status"] == "done", f"expected done, got: {job}"
    assert paper_id not in store.list_failures()


def test_matched_file_triggers_the_reingest_path(lab_client, tmp_path, fake_pdf_bytes):
    paper_id = "doi:10.1145/3676641.3716025"
    queued = [{"paper_id": paper_id, "title": "TAPAS"}]
    _arm_with_directory(lab_client.app, tmp_path, [paper_id], queued=queued)

    calls = []

    async def fast_retry(path, pid, bus):
        calls.append((path, pid))

    lab_client.app.state.retry_override = fast_retry

    (tmp_path / "3676641.3716025.pdf").write_bytes(fake_pdf_bytes)
    lab_client.get("/api/acquire/status")
    body = lab_client.get("/api/acquire/status").json()
    job_id = body["matched"][0]["job_id"]
    job = _wait_for_job(lab_client, job_id)

    assert job["status"] == "done"
    assert len(calls) == 1
    called_path, called_pid = calls[0]
    assert called_pid == paper_id


def test_a_reingest_failure_keeps_the_failure_record(lab_client, tmp_path, fake_pdf_bytes):
    """Preserve the existing care around clear_failure: it clears only on
    success, keeping the record when the re-ingest errors."""
    from research_companion import store

    paper_id = "doi:10.1145/3676641.3716025"
    store.record_failure(paper_id, {"stage": "add", "error": "no pdf",
                                    "paper_id": paper_id})
    queued = [{"paper_id": paper_id, "title": "TAPAS"}]
    _arm_with_directory(lab_client.app, tmp_path, [paper_id], queued=queued)

    async def failing_retry(path, pid, bus):
        raise RuntimeError("boom")

    lab_client.app.state.retry_override = failing_retry

    (tmp_path / "3676641.3716025.pdf").write_bytes(fake_pdf_bytes)
    lab_client.get("/api/acquire/status")
    body = lab_client.get("/api/acquire/status").json()
    job_id = body["matched"][0]["job_id"]

    job = _wait_for_job(lab_client, job_id)
    assert job["status"] == "failed"
    assert paper_id in store.list_failures(), "failure record must be kept on re-ingest error"


def test_unmatched_file_is_reported_and_left_byte_identical(lab_client, tmp_path):
    paper_id = "doi:10.1145/3676641.3716025"
    queued = [{"paper_id": paper_id, "title": "TAPAS"}]
    _arm_with_directory(lab_client.app, tmp_path, [paper_id], queued=queued)

    f = tmp_path / "statement.pdf"
    original = b"%PDF-1.5 not a real research paper"
    f.write_bytes(original)

    lab_client.get("/api/acquire/status")
    body = lab_client.get("/api/acquire/status").json()

    assert body["matched"] == []
    assert body["unmatched"] == ["statement.pdf"]
    assert f.exists(), "an unmatched file must be left in place"
    assert f.read_bytes() == original, "an unmatched file must be left byte-identical"


def test_polling_while_disarmed_catches_nothing(lab_client, tmp_path):
    lab_client.app.state.watcher.directory = tmp_path
    (tmp_path / "anything.pdf").write_bytes(b"%PDF-1.5 x")

    body = lab_client.get("/api/acquire/status").json()
    assert body["armed"] is False
    assert body["matched"] == []
    assert body["unmatched"] == []
    assert (tmp_path / "anything.pdf").exists()


def test_an_unreadable_file_does_not_fail_the_request(lab_client, tmp_path, fake_pdf_bytes):
    """One bad catch (its bytes unreadable when the handler gets to it, even
    though the watcher itself already confirmed and identified it) must not
    sink the whole request, and other catches in the same poll must still be
    reported. Simulated by making Path.read_bytes raise for that one file --
    an actual delete-between-polls never reaches the handler at all, because
    ArmedWatcher.poll() itself would simply omit a file gone from
    directory.iterdir() (already covered by test_watcher.py)."""
    from pathlib import Path
    from unittest.mock import patch

    paper_id = "doi:10.1145/3676641.3716025"
    other_id = "arxiv:2501.02600"
    queued = [{"paper_id": paper_id, "title": "TAPAS"},
              {"paper_id": other_id, "title": "Something Else Entirely"}]
    _arm_with_directory(lab_client.app, tmp_path, [paper_id, other_id], queued=queued)

    async def fast_retry(path, pid, bus):
        pass

    lab_client.app.state.retry_override = fast_retry

    bad_name = "3676641.3716025.pdf"
    bad = tmp_path / bad_name
    bad.write_bytes(fake_pdf_bytes)
    good = tmp_path / "2501.02600.pdf"
    good.write_bytes(fake_pdf_bytes)

    # First poll: both are first-sighted only.
    r1 = lab_client.get("/api/acquire/status")
    assert r1.status_code == 200

    original_read_bytes = Path.read_bytes

    def flaky_read_bytes(self):
        if self.name == bad_name:
            raise OSError("simulated vanished/unreadable file")
        return original_read_bytes(self)

    with patch.object(Path, "read_bytes", flaky_read_bytes):
        r2 = lab_client.get("/api/acquire/status")

    assert r2.status_code == 200
    body = r2.json()
    matched_ids = {m["paper_id"] for m in body["matched"]}
    assert other_id in matched_ids
    assert paper_id not in matched_ids
    assert bad_name not in body["unmatched"]


def test_armed_and_seconds_left_still_behave_as_before(lab_client, tmp_path):
    lab_client.app.state.watcher.directory = tmp_path
    lab_client.app.state.watcher.arm(["a"], ttl=600, queued=())
    body = lab_client.get("/api/acquire/status").json()
    assert body["armed"] is True
    assert 0 < body["seconds_left"] <= 600
    assert body["paper_ids"] == ["a"]
