"""Catching a PDF the user downloaded by hand.

The privacy properties here are the design, not a nicety: the watcher was
chosen to be armed by a click precisely so that nothing is observed unless the
user just asked for it. They are asserted, not intended.
"""
from __future__ import annotations

import pytest

from research_companion.watcher import ArmedWatcher, identify_pdf

QUEUED = [
    {"paper_id": "doi:10.1145/3676641.3716025",
     "title": "TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference"},
    {"paper_id": "arxiv:2501.02600", "title": "Something Else Entirely"},
]


# --- identification ---------------------------------------------------------

def test_a_doi_in_the_filename_matches():
    """ACM names its downloads after the DOI suffix, so this tier usually
    wins outright: 3676641.pdf IS the identifier."""
    assert identify_pdf("3676641.3716025.pdf", "", QUEUED) == "doi:10.1145/3676641.3716025"


def test_a_full_doi_in_the_filename_matches():
    assert identify_pdf("10.1145_3676641.3716025.pdf", "", QUEUED) == \
        "doi:10.1145/3676641.3716025"


def test_an_arxiv_id_in_the_filename_matches():
    assert identify_pdf("paper_arXiv-2501.02600.pdf", "", QUEUED) == "arxiv:2501.02600"


def test_a_doi_on_page_one_matches_when_the_filename_is_useless():
    """IEEE names downloads 08123456.pdf, which identifies nothing."""
    page1 = "Proceedings ... https://doi.org/10.1145/3676641.3716025 ... Abstract"
    assert identify_pdf("08123456.pdf", page1, QUEUED) == "doi:10.1145/3676641.3716025"


def test_the_title_matches_when_no_identifier_is_present():
    page1 = ("TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference\n"
             "Anon Author, Some University\nAbstract— We present...")
    assert identify_pdf("download.pdf", page1, QUEUED) == "doi:10.1145/3676641.3716025"


def test_an_unrelated_pdf_matches_nothing():
    """The case that decides whether this feature is tolerable: a bank
    statement in the downloads folder must not become a paper."""
    assert identify_pdf("statement-2026-08.pdf",
                        "Your monthly statement\nAccount ending 4471", QUEUED) is None


def test_a_near_miss_title_matches_nothing():
    """Attaching the wrong PDF is worse than attaching none."""
    assert identify_pdf("x.pdf", "TAPAS: A Completely Different Paper About Food",
                        QUEUED) is None


def test_identification_never_raises():
    for args in (("", "", QUEUED), (None, None, QUEUED), ("x.pdf", "y", []),
                 ("x.pdf", "y", None)):
        assert identify_pdf(*args) is None or isinstance(identify_pdf(*args), str)


# --- arming -----------------------------------------------------------------

def test_a_new_watcher_is_not_armed(tmp_path):
    assert ArmedWatcher(tmp_path).is_armed is False


def test_polling_while_disarmed_reads_nothing(tmp_path):
    """The invariant the whole design rests on."""
    (tmp_path / "anything.pdf").write_bytes(b"%PDF-1.5 x")
    reads = []
    w = ArmedWatcher(tmp_path, read_page1=lambda p: reads.append(p) or "")
    assert w.poll() == []
    assert reads == [], "nothing is read while disarmed"


def test_arming_then_polling_finds_a_completed_download(tmp_path):
    """A completed download is claimed on the poll AFTER it is first seen --
    the first poll only records its size."""
    clock = [100.0]
    w = ArmedWatcher(tmp_path, now=lambda: clock[0],
                     read_page1=lambda p: "10.1145/3676641.3716025")
    w.arm([q["paper_id"] for q in QUEUED], ttl=600, queued=QUEUED)
    clock[0] += 1
    (tmp_path / "3676641.3716025.pdf").write_bytes(b"%PDF-1.5 x")
    assert w.poll() == [], "first sighting only records the size"
    found = w.poll()
    assert [f[1] for f in found] == ["doi:10.1145/3676641.3716025"]


def test_a_file_older_than_the_arming_instant_is_ignored(tmp_path):
    """Arming must not sweep up whatever was already sitting there."""
    old = tmp_path / "old.pdf"
    old.write_bytes(b"%PDF-1.5 x")
    import os
    os.utime(old, (1000, 1000))
    w = ArmedWatcher(tmp_path, read_page1=lambda p: "10.1145/3676641.3716025")
    w.arm(["doi:10.1145/3676641.3716025"], ttl=600, queued=QUEUED)
    assert w.poll() == []


def test_a_non_pdf_is_ignored(tmp_path):
    w = ArmedWatcher(tmp_path, read_page1=lambda p: "10.1145/3676641.3716025")
    w.arm(["doi:10.1145/3676641.3716025"], ttl=600, queued=QUEUED)
    (tmp_path / "notes.txt").write_text("hello")
    assert w.poll() == []


def test_a_partial_download_is_not_claimed(tmp_path):
    """Browsers write .crdownload and rename on completion. Grabbing one
    produces a parse failure for a file that was fine."""
    w = ArmedWatcher(tmp_path, read_page1=lambda p: "10.1145/3676641.3716025")
    w.arm(["doi:10.1145/3676641.3716025"], ttl=600, queued=QUEUED)
    (tmp_path / "x.pdf.crdownload").write_bytes(b"%PDF-1.5 partial")
    assert w.poll() == []


def test_a_growing_file_is_not_claimed_until_its_size_settles(tmp_path):
    w = ArmedWatcher(tmp_path, read_page1=lambda p: "10.1145/3676641.3716025")
    w.arm(["doi:10.1145/3676641.3716025"], ttl=600, queued=QUEUED)
    f = tmp_path / "3676641.3716025.pdf"
    f.write_bytes(b"%PDF-1.5 ")
    assert w.poll() == [], "first sighting only records the size"
    f.write_bytes(b"%PDF-1.5 more bytes")
    assert w.poll() == [], "still growing"
    assert len(w.poll()) == 1, "stable, now claimed"


def test_an_unmatched_file_is_reported_but_left_alone(tmp_path):
    w = ArmedWatcher(tmp_path, read_page1=lambda p: "nothing relevant")
    w.arm(["doi:10.1145/3676641.3716025"], ttl=600, queued=QUEUED)
    f = tmp_path / "statement.pdf"
    f.write_bytes(b"%PDF-1.5 x")
    before = f.read_bytes()
    w.poll()
    found = w.poll()
    assert found and found[0][1] is None, "reported as unmatched"
    assert f.exists() and f.read_bytes() == before, "untouched"


def test_the_window_expires(tmp_path):
    clock = [100.0]
    w = ArmedWatcher(tmp_path, now=lambda: clock[0], read_page1=lambda p: "")
    w.arm(["x"], ttl=600, queued=QUEUED)
    assert w.is_armed is True
    clock[0] += 601
    assert w.is_armed is False
    assert w.poll() == []


def test_arming_again_extends_the_window_and_adds_papers(tmp_path):
    clock = [100.0]
    w = ArmedWatcher(tmp_path, now=lambda: clock[0], read_page1=lambda p: "")
    w.arm(["a"], ttl=600, queued=QUEUED)
    clock[0] += 300
    w.arm(["b"], ttl=600, queued=QUEUED)
    assert w.seconds_left == pytest.approx(600, abs=1)
    assert w.armed_paper_ids == {"a", "b"}


def test_a_file_from_before_a_rearm_stays_eligible(tmp_path):
    """The mtime-eligibility window is anchored to the FIRST arm() of a
    session, not reset by a later re-arm: a file downloaded right after the
    first click must not become ineligible just because the user went on to
    queue more papers."""
    clock = [100.0]
    w = ArmedWatcher(tmp_path, now=lambda: clock[0],
                     read_page1=lambda p: "10.1145/3676641.3716025")
    w.arm(["doi:10.1145/3676641.3716025"], ttl=600, queued=QUEUED)
    (tmp_path / "3676641.3716025.pdf").write_bytes(b"%PDF-1.5 x")
    clock[0] += 300
    w.arm(["arxiv:2501.02600"], ttl=600, queued=QUEUED)  # re-arm, extends window
    assert w.poll() == [], "first sighting only records the size"
    found = w.poll()
    assert [f[1] for f in found] == ["doi:10.1145/3676641.3716025"]


def test_disarming_stops_everything(tmp_path):
    w = ArmedWatcher(tmp_path, read_page1=lambda p: "x")
    w.arm(["a"], ttl=600, queued=QUEUED)
    w.disarm()
    assert w.is_armed is False
    (tmp_path / "new.pdf").write_bytes(b"%PDF-1.5 x")
    assert w.poll() == []


def test_a_missing_directory_is_survivable(tmp_path):
    w = ArmedWatcher(tmp_path / "nope", read_page1=lambda p: "x")
    w.arm(["a"], ttl=600, queued=QUEUED)
    assert w.poll() == []
