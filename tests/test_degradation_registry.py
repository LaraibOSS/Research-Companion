"""The degradation registry must stay true to the code.

`scripts/check_degradation_registry.py` runs in CI, but a contributor running
the suite locally should learn immediately that a row has drifted — not at push
time.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "docs" / "DEGRADATION_REGISTRY.json"


def test_registry_is_valid_and_matches_the_code():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_degradation_registry.py")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, (
        "degradation registry has drifted from the code:\n"
        + proc.stdout + proc.stderr
    )


def test_every_documented_feature_toggle_has_a_row():
    """Each opt-in setting changes behaviour when off; that behaviour is exactly
    what the registry exists to state. A new toggle without a row is a silent
    degradation path."""
    from research_companion.settings import DEFAULTS

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    mechanisms = {m["mechanism"] for m in data["mechanisms"]}

    # settings whose "off" state materially changes what the tool reports
    toggles_needing_a_row = {
        "connectors": "connectors_disabled",
        "semantic_overlap": "semantic_overlap_disabled",
        "contact_email": "contact_email_unset",
    }
    for setting, mechanism in toggles_needing_a_row.items():
        assert setting in DEFAULTS, f"{setting} vanished from settings DEFAULTS"
        assert mechanism in mechanisms, (
            f"setting {setting!r} has no degradation-registry row "
            f"(expected {mechanism!r})"
        )


def test_registry_states_the_never_render_clean_principle():
    """The load-bearing rule: a check that did not run is never shown as clean."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    principles = " ".join(data.get("principles", [])).lower()
    assert "never" in principles and "clean" in principles
