"""Tests for the deterministic reproducibility checker."""
from __future__ import annotations

from research_companion.reproducibility import assess_reproducibility


class TestLinks:
    def test_detects_code_link(self):
        r = assess_reproducibility("Code at https://github.com/acme/repo for details.")
        assert r["code_links"] == ["https://github.com/acme/repo"]

    def test_detects_data_link(self):
        r = assess_reproducibility("Data on https://zenodo.org/record/12345 archive.")
        assert any("zenodo.org" in u for u in r["data_links"])

    def test_dedups_repeated_links(self):
        t = "https://github.com/a/b and again https://github.com/a/b"
        r = assess_reproducibility(t)
        assert r["code_links"] == ["https://github.com/a/b"]

    def test_no_links(self):
        r = assess_reproducibility("A purely theoretical paper with no artifacts.")
        assert r["code_links"] == [] and r["data_links"] == []

    def test_links_found_in_references(self):
        r = assess_reproducibility(
            "See our repo.", references=[{"title": "https://github.com/x/y dataset"}])
        assert r["code_links"] == ["https://github.com/x/y"]


class TestStatementsAndSignals:
    def test_availability_statement(self):
        assert assess_reproducibility(
            "Our code is publicly available.")["has_availability_statement"]

    def test_method_signals(self):
        t = ("We tuned hyperparameters with learning rate 1e-3 and batch size 32 "
             "on an A100 GPU, fixing the random seed.")
        sig = assess_reproducibility(t)["signals"]
        assert sig["hyperparameters"] and sig["training_details"]
        assert sig["compute"] and sig["random_seed"]

    def test_checklists(self):
        r = assess_reproducibility("We followed PRISMA and include a model card.")
        assert "PRISMA" in r["checklists"] and "model_card" in r["checklists"]


class TestLevel:
    def test_high_when_code_data_and_statement(self):
        t = ("Our code is available at https://github.com/a/b and data at "
             "https://zenodo.org/record/9. We report hyperparameters and the GPU used.")
        r = assess_reproducibility(t)
        assert r["level"] == "high"
        assert r["missing"] == [] or "code" not in " ".join(r["missing"]).lower()

    def test_low_when_nothing(self):
        r = assess_reproducibility("Abstract-only theoretical note.")
        assert r["level"] == "low"
        assert len(r["missing"]) == 4

    def test_medium_when_partial(self):
        r = assess_reproducibility("Code available at https://github.com/a/b.")
        assert r["level"] == "medium"

    def test_empty_input(self):
        r = assess_reproducibility("")
        assert r["level"] == "low"
