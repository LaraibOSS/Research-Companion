"""Settings management for research_companion.

Handles:
- Secret API key management via .env file (never in JSON)
- User preferences persisted in config.json["settings"]
- os.environ mirroring for live config changes

Security rules:
- Secrets only ever in .env file + os.environ
- All secrets masked in every API response
- Secrets are never logged or printed
- Empty-string value for a key -> SettingsError (client must send null to delete)
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECRET_KEYS: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "hf_token": "HF_TOKEN",
    "ncbi_api_key": "NCBI_API_KEY",
}

DEFAULTS: dict[str, Any] = {
    "provider": "anthropic",
    "model": None,
    "theme": "dark",
    "accent": "blue",
    "density": "comfortable",
    "k_sections": 6,
    "char_budget": 8000,
    "embed_model": "sentence-transformers/all-MiniLM-L6-v2",
    "auto_add_citations": True,
    "connectors": [],
    "semantic_overlap": False,
    "semantic_overlap_allow_remote": False,
    "semantic_overlap_threshold": 0.83,
}

_VALID_PROVIDERS = {"anthropic", "openai"}
_VALID_THEMES = {"dark", "light"}
_VALID_ACCENTS = {"blue", "teal", "violet"}
_VALID_DENSITIES = {"comfortable", "compact"}

# All settable fields (excluding "keys" which is handled separately)
_SETTABLE_FIELDS = set(DEFAULTS.keys())


# ---------------------------------------------------------------------------
# SettingsError
# ---------------------------------------------------------------------------

class SettingsError(ValueError):
    """Raised for invalid settings values."""


# ---------------------------------------------------------------------------
# env_file_path
# ---------------------------------------------------------------------------

def env_file_path() -> Path:
    """Return root_dir()/.env — API keys are GLOBAL across workspaces."""
    from research_companion.store import root_dir
    return root_dir() / ".env"


# ---------------------------------------------------------------------------
# read_env_file
# ---------------------------------------------------------------------------

def read_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse a .env file and return a dict of KEY -> value.

    Tolerates:
    - Quoted values (single or double quotes stripped)
    - Comment lines (# at start)
    - Blank lines
    - Inline comments are NOT stripped (values are taken as-is after the =)
    """
    if path is None:
        path = env_file_path()
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in text.splitlines():
        # Strip leading/trailing whitespace
        stripped = line.strip()
        # Skip blank lines and comment lines
        if not stripped or stripped.startswith("#"):
            continue
        # Parse KEY=VALUE
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip enclosing quotes
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# load_env_file
# ---------------------------------------------------------------------------

def load_env_file(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Parse .env file and set os.environ for keys not already set (unless override=True).

    Returns the parsed dict (even for keys not set due to override rules).
    Missing files are silently ignored.
    """
    parsed = read_env_file(path)
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return parsed


# ---------------------------------------------------------------------------
# write_env_keys
# ---------------------------------------------------------------------------

def write_env_keys(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Merge-write key updates to a .env file, preserving unrelated lines/comments.

    - updates[key] = str  -> write/update that line
    - updates[key] = None -> delete that line
    - os.chmod 0o600 is best-effort (no-op semantics on Windows; no exception raised)

    Lines that don't correspond to updated keys are preserved verbatim (including comments).
    """
    if path is None:
        path = env_file_path()

    # Ensure parent directory exists
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    # Read existing lines
    existing_lines: list[str] = []
    if path.exists():
        with contextlib.suppress(OSError):
            existing_lines = path.read_text(encoding="utf-8").splitlines()

    # Track which update keys have been applied
    applied: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        # Detect if this line defines a key in updates
        if stripped and not stripped.startswith("#") and "=" in stripped:
            line_key = stripped.partition("=")[0].strip()
            if line_key in updates:
                val = updates[line_key]
                applied.add(line_key)
                if val is None:
                    # Delete: skip this line
                    continue
                else:
                    # Update value
                    new_lines.append(f"{line_key}={val}")
                    continue
        new_lines.append(line)

    # Append any new keys not found in existing file
    for key, val in updates.items():
        if key not in applied and val is not None:
            new_lines.append(f"{key}={val}")

    # Write
    try:
        content = "\n".join(new_lines)
        if new_lines:
            content += "\n"
        path.write_text(content, encoding="utf-8")
    except OSError:
        return

    # Best-effort chmod 0o600 (no-op on Windows)
    with contextlib.suppress(OSError, NotImplementedError):
        path.chmod(0o600)


# ---------------------------------------------------------------------------
# mask_secret
# ---------------------------------------------------------------------------

def mask_secret(value: str) -> str:
    """Mask a secret value: '****' + last 4 chars; just '****' if len < 8."""
    if len(value) < 8:
        return "****"
    return "****" + value[-4:]


# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------

def get_settings() -> dict:
    """Return current settings merged from DEFAULTS <- env <- root settings.json.

    Settings are GLOBAL (root-level) — they apply across all workspaces.
    provider/model honor RESEARCH_COMPANION_PROVIDER / RESEARCH_COMPANION_MODEL when
    the user has not saved an explicit choice — otherwise the UI reports the wrong
    active provider (and checks the wrong API key) on env-configured installs.
    Keys block shows presence/masking from os.environ.
    """
    from research_companion.store import load_root_settings

    saved = load_root_settings()

    # Merge: DEFAULTS <- env <- saved
    result: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        result[key] = saved.get(key, default)
    if "provider" not in saved:
        env_provider = os.environ.get("RESEARCH_COMPANION_PROVIDER", "").strip().lower()
        if env_provider in _VALID_PROVIDERS:
            result["provider"] = env_provider
    if "model" not in saved:
        env_model = os.environ.get("RESEARCH_COMPANION_MODEL", "").strip()
        if env_model:
            result["model"] = env_model

    # Build keys block
    keys_block: dict[str, dict] = {}
    for name, env_var in SECRET_KEYS.items():
        raw = os.environ.get(env_var)
        if raw:
            keys_block[name] = {"set": True, "masked": mask_secret(raw)}
        else:
            keys_block[name] = {"set": False, "masked": None}

    result["keys"] = keys_block
    return result


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------

def update_settings(patch: dict, *, env_path: Path | None = None) -> dict:
    """Validate and apply a settings patch.

    Validation rules:
    - provider must be in {anthropic, openai}
    - theme must be in {dark, light}
    - accent must be in {blue, teal, violet}
    - density must be in {comfortable, compact}
    - 1 <= k_sections <= 20
    - 1000 <= char_budget <= 50000
    - semantic_overlap / semantic_overlap_allow_remote must be booleans
    - 0.0 <= semantic_overlap_threshold <= 1.0
    - Unknown top-level fields -> SettingsError
    - patch["keys"][name] = "" -> SettingsError (use null to delete)

    Side effects:
    - Non-secrets written to config.json["settings"]
    - provider/model mirrored to RESEARCH_COMPANION_PROVIDER / RESEARCH_COMPANION_MODEL
    - model = None -> removes RESEARCH_COMPANION_MODEL from os.environ
    - keys[name] = str -> write_env_keys + os.environ[env_var] = value
    - keys[name] = None -> delete from file + os.environ.pop

    Returns get_settings().
    """
    from research_companion.store import load_root_settings, save_root_settings

    # Separate "keys" from regular fields
    keys_patch = patch.get("keys")
    regular_patch = {k: v for k, v in patch.items() if k != "keys"}

    # Validate unknown top-level fields
    for field in regular_patch:
        if field not in _SETTABLE_FIELDS:
            raise SettingsError(f"Unknown settings field: {field!r}")

    # Validate individual fields
    if "provider" in regular_patch and regular_patch["provider"] not in _VALID_PROVIDERS:
        raise SettingsError(
            f"provider must be one of {sorted(_VALID_PROVIDERS)}, "
            f"got {regular_patch['provider']!r}"
        )

    if "theme" in regular_patch and regular_patch["theme"] not in _VALID_THEMES:
        raise SettingsError(
            f"theme must be one of {sorted(_VALID_THEMES)}, "
            f"got {regular_patch['theme']!r}"
        )

    if "accent" in regular_patch and regular_patch["accent"] not in _VALID_ACCENTS:
        raise SettingsError(
            f"accent must be one of {sorted(_VALID_ACCENTS)}, "
            f"got {regular_patch['accent']!r}"
        )

    if "density" in regular_patch and regular_patch["density"] not in _VALID_DENSITIES:
        raise SettingsError(
            f"density must be one of {sorted(_VALID_DENSITIES)}, "
            f"got {regular_patch['density']!r}"
        )

    if "auto_add_citations" in regular_patch:
        v = regular_patch["auto_add_citations"]
        if not isinstance(v, bool):
            raise SettingsError(f"auto_add_citations must be a boolean, got {v!r}")

    if "connectors" in regular_patch:
        from research_companion.connectors import VALID_CONNECTORS
        v = regular_patch["connectors"]
        if not isinstance(v, list) or any(x not in VALID_CONNECTORS for x in v):
            raise SettingsError(
                f"connectors must be a list of {sorted(VALID_CONNECTORS)}, got {v!r}")

    for bool_field in ("semantic_overlap", "semantic_overlap_allow_remote"):
        if bool_field in regular_patch:
            v = regular_patch[bool_field]
            if not isinstance(v, bool):
                raise SettingsError(f"{bool_field} must be a boolean, got {v!r}")

    if "semantic_overlap_threshold" in regular_patch:
        v = regular_patch["semantic_overlap_threshold"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
            raise SettingsError(
                f"semantic_overlap_threshold must be a number in [0, 1], got {v!r}")

    if "k_sections" in regular_patch:
        v = regular_patch["k_sections"]
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 20):
            raise SettingsError(f"k_sections must be between 1 and 20, got {v!r}")

    if "char_budget" in regular_patch:
        v = regular_patch["char_budget"]
        if not isinstance(v, int) or isinstance(v, bool) or not (1000 <= v <= 50000):
            raise SettingsError(f"char_budget must be between 1000 and 50000, got {v!r}")

    # Validate keys patch (before writing anything)
    if keys_patch is not None:
        for name, value in keys_patch.items():
            if name not in SECRET_KEYS:
                raise SettingsError(f"Unknown key name: {name!r}")
            if value == "":
                raise SettingsError(
                    f"Empty string is not allowed for key {name!r}. "
                    "Send null to delete the key."
                )

    # --- All validation passed; now apply changes ---

    # Apply regular fields to the GLOBAL root settings.json
    if regular_patch:
        s = load_root_settings()
        s.update(regular_patch)
        save_root_settings(s)

    # Mirror provider/model to os.environ
    if "provider" in regular_patch:
        os.environ["RESEARCH_COMPANION_PROVIDER"] = regular_patch["provider"]

    if "model" in regular_patch:
        model_val = regular_patch["model"]
        if model_val is None:
            os.environ.pop("RESEARCH_COMPANION_MODEL", None)
        else:
            os.environ["RESEARCH_COMPANION_MODEL"] = model_val

    # Apply keys patch
    if keys_patch is not None:
        env_updates: dict[str, str | None] = {}
        for name, value in keys_patch.items():
            env_var = SECRET_KEYS[name]
            if value is None:
                # Delete
                os.environ.pop(env_var, None)
                env_updates[env_var] = None
            else:
                # Set
                os.environ[env_var] = value
                env_updates[env_var] = value
        write_env_keys(env_updates, path=env_path)

    return get_settings()
