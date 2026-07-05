"""tests/test_packaging.py — Static assertions that pyproject.toml package-data
globs cover every file that currently exists under research_companion/lab/static.

This test does NOT build a wheel; it purely verifies the glob patterns declared
in [tool.setuptools.package-data] are sufficient to match all static assets
that live in the tree today.  It guards against future additions slipping
through without a corresponding glob update.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo / package root
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PACKAGE_ROOT = REPO_ROOT / "research_companion"
STATIC_DIR = PACKAGE_ROOT / "lab" / "static"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pyproject() -> dict:
    """Load pyproject.toml using tomllib (Python 3.11+) or tomli fallback."""
    try:
        import tomllib as _tl
    except ImportError:
        try:
            import tomli as _tl  # type: ignore[no-redef]
        except ImportError:
            pytest.skip("tomllib/tomli not available — skip packaging test")
            return {}  # unreachable but keeps type checker happy
    with open(PYPROJECT, "rb") as f:
        return _tl.load(f)


def _get_package_data_globs() -> list[str]:
    """Return the glob patterns declared for research_companion in pyproject.toml."""
    data = _load_pyproject()
    pkg_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    return pkg_data.get("research_companion", [])


def _walk_static_files() -> list[str]:
    """Return all non-hidden files under lab/static as paths relative to PACKAGE_ROOT."""
    result = []
    for p in STATIC_DIR.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            rel = p.relative_to(PACKAGE_ROOT).as_posix()
            result.append(rel)
    return result


def _any_glob_matches(path: str, globs: list[str]) -> bool:
    """Return True if *any* glob in `globs` matches `path` (fnmatch semantics)."""
    for pat in globs:
        # Support both flat and nested patterns
        if fnmatch.fnmatch(path, pat):
            return True
        # fnmatch doesn't handle ** — expand: treat ** as matching any sub-path
        # by converting "lab/static/js/**/*.js" -> multiple checks
        if "**" in pat:
            # Normalise: split on **
            parts = pat.split("**")
            # Build a regex-like check: prefix must match start, suffix must match end
            prefix = parts[0]
            suffix = parts[-1].lstrip("/")
            if path.startswith(prefix):
                remainder = path[len(prefix):]
                if not suffix or remainder.endswith(suffix) or fnmatch.fnmatch(remainder, f"*{suffix}"):
                    return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pyproject_has_server_extra():
    """pyproject.toml must declare a 'server' extra with fastapi + uvicorn."""
    data = _load_pyproject()
    extras = data.get("project", {}).get("optional-dependencies", {})
    assert "server" in extras, "Missing [server] extra in pyproject.toml"
    server_deps = extras["server"]
    assert any("fastapi" in d for d in server_deps), "server extra must include fastapi"
    assert any("uvicorn" in d for d in server_deps), "server extra must include uvicorn"


def test_pyproject_version_is_0_2_0():
    """pyproject.toml version must be 0.2.0."""
    data = _load_pyproject()
    assert data["project"]["version"] == "0.2.0", (
        f"Expected version 0.2.0, got {data['project']['version']!r}"
    )


def test_pyproject_has_required_classifiers():
    """pyproject.toml must contain the required classifiers for 0.2 Beta release."""
    data = _load_pyproject()
    classifiers = data.get("project", {}).get("classifiers", [])
    required = [
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: MIT License",
        "Topic :: Scientific/Engineering",
        "Intended Audience :: Science/Research",
    ]
    for req in required:
        assert req in classifiers, f"Missing classifier: {req!r}"
    # Must cover 3.10-3.13
    for minor in ("3.10", "3.11", "3.12", "3.13"):
        needle = f"Programming Language :: Python :: {minor}"
        assert needle in classifiers, f"Missing classifier: {needle!r}"


def test_static_assets_covered_by_package_data_globs():
    """Every file under lab/static must be matched by at least one package-data glob.

    This is a forward-looking guard: if a new static file is added without a
    matching glob, this test will fail before it can silently be omitted from
    the wheel.
    """
    globs = _get_package_data_globs()
    assert globs, "No package-data globs found for research_companion"

    static_files = _walk_static_files()
    assert static_files, f"No files found under {STATIC_DIR}"

    uncovered = [f for f in static_files if not _any_glob_matches(f, globs)]

    if uncovered:
        msg = (
            f"{len(uncovered)} file(s) under lab/static are NOT covered by "
            f"[tool.setuptools.package-data] globs in pyproject.toml:\n"
            + "\n".join(f"  {f}" for f in sorted(uncovered))
            + "\n\nAdd the missing pattern(s) to pyproject.toml."
        )
        pytest.fail(msg)


def test_index_html_covered():
    """lab/static/index.html must specifically be covered by a package-data glob."""
    globs = _get_package_data_globs()
    assert _any_glob_matches("lab/static/index.html", globs), (
        "lab/static/index.html is not covered by any package-data glob"
    )


def test_vendor_js_covered():
    """lab/static/vendor/vis-network.min.js must be covered by a package-data glob."""
    globs = _get_package_data_globs()
    assert _any_glob_matches("lab/static/vendor/vis-network.min.js", globs), (
        "lab/static/vendor/vis-network.min.js is not covered by any package-data glob"
    )
