"""Whether a person could act on a failure -- computed in ONE place so the
CLI and the Lab agree on the same queue.

Previously implemented twice (research_companion/cli.py and
research_companion/lab_api.py) and the two copies disagreed on what to do
for a failure record that predates acquire() and carries no `paper_id`
either -- exactly the shape research_companion/lab/__init__.py writes,
{"stage": "add", "error": ...}. This module is the single implementation
both now call.
"""
from __future__ import annotations

from research_companion.acquire.policy import human_can_help


def test_stored_flag_wins_when_an_acquisition_is_recorded():
    """A typed Acquisition was persisted -- read its human_can_help flag
    verbatim, never re-derive it, regardless of what the disk looks like."""
    helpable = {"acquisition": {"obtained": False, "reason": "paywalled",
                                "human_can_help": True, "attempts": [], "source": None}}
    not_helpable = {"acquisition": {"obtained": False, "reason": "source_unavailable",
                                    "human_can_help": False, "attempts": [], "source": None}}
    assert human_can_help(helpable, "doi:a") is True
    assert human_can_help(not_helpable, "doi:a") is False


def test_no_acquisition_and_no_pdf_on_disk_is_helpable(isolated_papergraph_dir):
    info = {"stage": "add", "error": "PDF not found: /tmp/x.pdf", "paper_id": "doi:missing"}
    assert human_can_help(info, "doi:missing") is True


def test_no_acquisition_but_pdf_present_is_not_helpable(isolated_papergraph_dir):
    """A parse/OCR/graph failure on a PDF that IS on disk must not offer the
    'supply the missing file' affordance -- the file isn't missing."""
    from research_companion import store

    store.save_pdf("doi:present", b"%PDF-1.5 x")
    info = {"stage": "extract", "error": "no PDF on disk for doi:present", "paper_id": "doi:present"}
    assert human_can_help(info, "doi:present") is False


def test_no_paper_id_resolves_through_the_key(isolated_papergraph_dir):
    """research_companion/lab/__init__.py writes exactly
    {"stage": "add", "error": ...} -- no paper_id, no acquisition. The
    failure-record key is the only identifier available, so the disk check
    runs against the key itself."""
    from research_companion import store

    info = {"stage": "add", "error": "x"}
    assert human_can_help(info, "doi:no-id") is True

    store.save_pdf("doi:no-id", b"%PDF-1.5 x")
    assert human_can_help(info, "doi:no-id") is False
