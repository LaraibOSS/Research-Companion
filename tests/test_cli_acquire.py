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
        cli.main(["acquire", "--all"])
    assert set(tried) == {"doi:a", "doi:b"}
