"""Community/governance files required for a contributable public repo."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_community_files_exist():
    for rel in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                ".github/CODEOWNERS", ".github/PULL_REQUEST_TEMPLATE.md",
                ".github/ISSUE_TEMPLATE/bug_report.yml",
                ".github/ISSUE_TEMPLATE/feature_request.yml",
                ".github/ISSUE_TEMPLATE/config.yml",
                ".github/dependabot.yml"):
        assert (REPO_ROOT / rel).exists(), f"missing {rel}"


def test_contributing_documents_the_three_gates():
    text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for cmd in ("python -m pytest -q", "node --test tests/js/*.test.mjs",
                "ruff check research_companion tests examples"):
        assert cmd in text, f"CONTRIBUTING.md missing gate: {cmd}"


def test_codeowners_assigns_maintainer():
    assert "@Hasan-Laraib" in (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")


def test_security_md_points_to_private_reporting():
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "security advisories" in text or "report a vulnerability" in text


def test_security_md_states_precise_version_status():
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "| Version" in text or "|Version" in text, "SECURITY.md needs a version-status table"
    assert "0.5.14" in text and "0.7.1" in text, "must disclose PyPI 0.5.14 vs source 0.7.1"
    assert "legacy" in text.lower() or "not equivalent" in text.lower()


def test_dependabot_covers_pip_and_actions():
    text = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "pip" in text and "github-actions" in text
