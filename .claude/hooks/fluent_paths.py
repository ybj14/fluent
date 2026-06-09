"""
Fluent path resolution — supports dual-mode (clone vs plugin install)
with per-target-language progress separation.

Data directory resolution precedence:
  1. $FLUENT_DATA_DIR if set (absolutized) — base dir (before language subdirectory)
  2. $CLAUDE_PROJECT_DIR/data if that dir holds _active.json (post-migration)
     OR learner-profile.json (pre-migration / clone mode)
  3. ./data if ./data/_active.json or ./data/learner-profile.json exists (clone mode, in-repo cwd)
  4. ~/.claue/fluent-data (plugin-mode fallback)

Once the base is resolved, the active language is read from _active.json
and appended as a subdirectory (e.g. ~/.claue/fluent-data/mongolian/).

Pure resolvers (data_dir / plugin_root / backups_dir) do not create directories.
Call ensure_data_dir() before writing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path

ACTIVE_FILE = "_active.json"

DB_FILES = [
    "learner-profile.json",
    "progress-db.json",
    "mistakes-db.json",
    "mastery-db.json",
    "spaced-repetition.json",
    "session-log.json",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(language_name: str) -> str:
    """Normalize a language name to a filesystem-safe directory slug.

    Examples: 'Mongolian' -> 'mongolian',
              'Brazilian Portuguese' -> 'brazilian-portuguese'.
    """
    s = language_name.strip().lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


def _base_data_dir() -> Path:
    """Resolve the BASE data directory (before language subdirectory).

    Uses the same 4-step logic as the original data_dir(), but stops
    one level up — the language subdirectory is appended later by data_dir().
    """
    env = os.environ.get("FLUENT_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()

    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project:
        candidate = (Path(project) / "data").resolve()
        if (candidate / ACTIVE_FILE).exists() or (candidate / "learner-profile.json").exists():
            return candidate

    cwd_data = (Path.cwd() / "data").resolve()
    if (cwd_data / ACTIVE_FILE).exists() or (cwd_data / "learner-profile.json").exists():
        return cwd_data

    return (Path.home() / ".claude" / "fluent-data").resolve()


def _read_active_language(base: Path) -> str | None:
    """Read the active language slug from _active.json. Returns None if missing."""
    active_path = base / ACTIVE_FILE
    if active_path.exists():
        try:
            with open(active_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("active_language")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _needs_migration(base: Path) -> bool:
    """Detect old flat structure: has learner-profile.json directly in base,
    but no _active.json."""
    return (
        (base / "learner-profile.json").exists()
        and not (base / ACTIVE_FILE).exists()
    )


def _infer_language_from_profile(base: Path) -> str | None:
    """Read target_language from a flat learner-profile.json and return its slug."""
    profile_path = base / "learner-profile.json"
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile = json.load(f)
        raw = profile.get("learner", {}).get("target_language", "")
        return slugify(raw) if raw else None
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def migrate_flat_to_per_language(base: Path, lang_slug: str) -> None:
    """Move 6 DB files + .backups + loose backup files from flat structure
    into a language subdirectory.  Idempotent — safe to call multiple times.

    _active.json is written LAST as a commit flag.
    """
    lang_dir = base / lang_slug
    lang_dir.mkdir(parents=True, exist_ok=True)

    for fname in DB_FILES:
        src = base / fname
        if src.exists():
            shutil.move(str(src), str(lang_dir / fname))

    # Move backups directory if it exists
    backup_src = base / ".backups"
    if backup_src.exists() and not (lang_dir / ".backups").exists():
        shutil.move(str(backup_src), str(lang_dir / ".backups"))

    # Move loose .backup-* files that validate-data.py may have created
    for bak in base.glob("*.backup-*"):
        shutil.move(str(bak), str(lang_dir / bak.name))

    # Commit flag — written last so a crash mid-migration is recoverable
    active_path = base / ACTIVE_FILE
    with open(active_path, 'w', encoding='utf-8') as f:
        json.dump({"active_language": lang_slug, "version": 1}, f, indent=2)
        f.write('\n')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_active_language(language_name: str) -> str:
    """Set the active language and return its slug.

    Writes _active.json in the base data directory.
    Clears the data_dir LRU cache so subsequent calls pick up the change.
    Does NOT create the language subdirectory (ensure_data_dir handles that).
    """
    lang_slug = slugify(language_name)
    base = _base_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    active_path = base / ACTIVE_FILE
    tmp_path = active_path.with_suffix('.json.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump({"active_language": lang_slug, "version": 1}, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.rename(str(tmp_path), str(active_path))
    # Clear cached data_dir so next call resolves fresh
    data_dir.cache_clear()
    return lang_slug


def list_languages() -> list[str]:
    """List all language slugs that have a learner-profile.json in their subdirectory."""
    base = _base_data_dir()
    if not base.exists():
        return []
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "learner-profile.json").exists()
        and not d.name.startswith('.')
    )


@lru_cache(maxsize=1)
def data_dir() -> Path:
    """Resolve the runtime data directory, including language subdirectory.

    Auto-migrates old flat structure on first encounter.
    Returns bare base if no active language (brand-new install before /fluent-setup).
    """
    base = _base_data_dir()

    # Auto-migrate old flat structure on first encounter
    if _needs_migration(base):
        lang_slug = _infer_language_from_profile(base)
        if lang_slug:
            migrate_flat_to_per_language(base, lang_slug)

    # Read active language
    active = _read_active_language(base)

    if active:
        return base / active

    # No active language set and no flat structure to migrate.
    # Brand-new install — return base; fluent-setup will call set_active_language.
    return base


def ensure_data_dir() -> Path:
    """Resolve the data directory and create it if missing. Call before writing."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache(maxsize=1)
def plugin_root() -> Path:
    """Resolve the plugin/repo root directory."""
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def backups_dir() -> Path:
    """Resolve the backups directory. Always nested inside data_dir to avoid collisions
    when the fallback ~/.claude/fluent-data is used (the parent ~/.claude/ is shared
    across plugins)."""
    return data_dir() / ".backups"


def ensure_backups_dir() -> Path:
    """Resolve the backups directory and create it if missing."""
    b = backups_dir()
    b.mkdir(parents=True, exist_ok=True)
    return b
