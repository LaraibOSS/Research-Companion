"""Resolution and the queue belong on the CLI too.

find-pdf existed only in the Lab UI -- no CLI, no MCP tool -- so a skill or a
script could not recover a paper.
"""
from __future__ import annotations

from unittest.mock import patch

from research_companion.acquire import AcquireReason, Acquisition


def test_acquire_retries_one_paper(capsys):
    from research_companion import cli
    with patch("research_companion.cli.acquire",
               return_value=(b"%PDF-1.5 x", Acquisition(True, None))):
        rc = cli.main(["acquire", "doi:10.1145/3732941"])
    assert rc == 0
    assert "doi:10.1145/3732941" in capsys.readouterr().out


def test_acquire_reports_the_cause_when_it_fails(capsys):
    from research_companion import cli
    with patch("research_companion.cli.acquire",
               return_value=(None, Acquisition(False, AcquireReason.BLOCKED_BY_HOST))):
        rc = cli.main(["acquire", "doi:10.1145/3732941"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocks automated downloads" in out
    assert "no PDF on disk" not in out


def test_list_shows_only_papers_a_person_can_help_with(capsys):
    from research_companion import cli, store
    store.record_failure("doi:a", {"stage": "add", "error": "x", "paper_id": "doi:a",
                                   "acquisition": {"obtained": False,
                                                   "reason": "blocked_by_host",
                                                   "human_can_help": True,
                                                   "attempts": [], "source": None}})
    store.record_failure("doi:b", {"stage": "add", "error": "x", "paper_id": "doi:b",
                                   "acquisition": {"obtained": False,
                                                   "reason": "source_unavailable",
                                                   "human_can_help": False,
                                                   "attempts": [], "source": None}})
    cli.main(["acquire", "--list"])
    out = capsys.readouterr().out
    assert "doi:a" in out
    assert "doi:b" not in out


def test_all_walks_every_recoverable_paper():
    from research_companion import cli, store
    for pid in ("doi:a", "doi:b"):
        store.record_failure(pid, {"stage": "add", "error": "x", "paper_id": pid,
                                   "acquisition": {"obtained": False,
                                                   "reason": "paywalled",
                                                   "human_can_help": True,
                                                   "attempts": [], "source": None}})
    tried = []
    with patch("research_companion.cli.acquire",
               side_effect=lambda m, **k: (tried.append(m.paper_id),
                                           (None, Acquisition(False, AcquireReason.PAYWALLED)))[1]):
        rc = cli.main(["acquire", "--all"])
    assert set(tried) == {"doi:a", "doi:b"}
    assert rc == 1  # every paper in the walk failed to acquire


def test_all_returns_zero_when_every_paper_is_acquired():
    from research_companion import cli, store
    for pid in ("doi:a", "doi:b"):
        store.record_failure(pid, {"stage": "add", "error": "x", "paper_id": pid,
                                   "acquisition": {"obtained": False,
                                                   "reason": "paywalled",
                                                   "human_can_help": True,
                                                   "attempts": [], "source": None}})
    with patch("research_companion.cli.acquire",
               return_value=(b"%PDF-1.5 x", Acquisition(True, None))):
        rc = cli.main(["acquire", "--all"])
    assert rc == 0


def test_list_says_nothing_waiting_when_the_queue_is_empty(capsys):
    from research_companion import cli
    rc = cli.main(["acquire", "--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing waiting" in out


def test_all_says_nothing_to_retry_when_the_queue_is_empty(capsys):
    from research_companion import cli
    rc = cli.main(["acquire", "--all"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing to retry" in out


def test_bare_acquire_with_no_target_errors(capsys):
    from research_companion import cli
    rc = cli.main(["acquire"])
    assert rc == 1
    assert "paper_id" in capsys.readouterr().err


def test_list_applies_the_no_acquisition_disk_fallback(capsys):
    """A failure record with no 'acquisition' key at all -- the shape
    research_companion/lab/__init__.py writes -- is still selected or
    excluded correctly through the shared policy.human_can_help, pinning
    the CLI's wiring to it rather than to a local re-implementation."""
    from research_companion import cli, store

    store.record_failure("doi:no-acq-missing", {"stage": "add", "error": "x",
                                                 "paper_id": "doi:no-acq-missing"})
    store.record_failure("doi:no-acq-present", {"stage": "extract", "error": "x",
                                                 "paper_id": "doi:no-acq-present"})
    store.save_pdf("doi:no-acq-present", b"%PDF-1.5 x")

    cli.main(["acquire", "--list"])
    out = capsys.readouterr().out
    assert "doi:no-acq-missing" in out
    assert "doi:no-acq-present" not in out
