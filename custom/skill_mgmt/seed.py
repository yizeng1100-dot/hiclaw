"""Seed skills from custom/skill_examples/ into the database on startup.

Scans for .md files with YAML frontmatter, creates or updates skills
that don't yet exist in the database. Associated script files referenced
in the frontmatter `scripts:` field are also imported.

This module uses raw sqlite3 to avoid async/engine issues.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

# Directory containing skill .md files and their associated scripts
SKILL_EXAMPLES_DIR = Path(__file__).parent.parent / "skill_examples"


def _get_db_path() -> str:
    persistence_dir = os.environ.get("OH_PERSISTENCE_DIR", str(Path.home() / ".openhands"))
    return str(Path(persistence_dir) / "openhands.db")


def _parse_frontmatter(content: str) -> dict:
    """Simple YAML frontmatter parser (no PyYAML dependency)."""
    match = re.match(r"^---\s*\n([\s\S]*?)\n---", content)
    if not match:
        return {}

    yaml_str = match.group(1)
    result: dict = {}
    current_key = None
    current_list: list | None = None

    for line in yaml_str.split("\n"):
        # List item
        if re.match(r"^\s*-\s+", line) and current_key:
            val = re.sub(r"^\s*-\s+", "", line).strip().strip('"').strip("'")
            if current_list is not None:
                current_list.append(val)
            continue

        # Key-value pair
        kv = re.match(r"^(\w[\w_]*):\s*(.*)", line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip().strip('"').strip("'")

            # Save previous list
            if current_list is not None and current_key:
                result[current_key] = current_list

            if val == "":
                # Start of a list or empty value
                current_key = key
                current_list = []
            else:
                result[key] = val
                current_key = key
                current_list = None

    # Don't forget the last list
    if current_list is not None and current_key:
        result[current_key] = current_list

    return result


def seed_skills() -> int:
    """Import skills from skill_examples/ into the database.

    Returns the number of skills created (skips existing ones).
    """
    if not SKILL_EXAMPLES_DIR.is_dir():
        _logger.debug(f"Skill examples directory not found: {SKILL_EXAMPLES_DIR}")
        return 0

    db_path = _get_db_path()
    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        # Ensure tables exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS managed_skill (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                category TEXT,
                skill_type TEXT NOT NULL DEFAULT 'knowledge',
                triggers TEXT,
                tags TEXT,
                is_global INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                current_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS skill_version (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL REFERENCES managed_skill(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                changelog TEXT,
                performance_notes TEXT,
                is_current INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS skill_script (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL REFERENCES managed_skill(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                language TEXT,
                content TEXT NOT NULL,
                description TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        created = 0
        # Recursively scan all subdirectories for .md skill files
        md_files = sorted(SKILL_EXAMPLES_DIR.glob("**/*.md"))

        for md_path in md_files:
            content = md_path.read_text(encoding="utf-8")
            meta = _parse_frontmatter(content)
            name = meta.get("name")
            if not name:
                _logger.warning(f"Skipping {md_path.name}: no 'name' in frontmatter")
                continue

            # Check if skill already exists
            cur.execute("SELECT id FROM managed_skill WHERE name = ?", (name,))
            if cur.fetchone():
                _logger.debug(f"Skill '{name}' already exists, skipping")
                continue

            now = datetime.now(timezone.utc).isoformat()
            skill_id = uuid4().hex

            triggers = meta.get("triggers", [])
            tags = meta.get("tags", [])
            description = meta.get("description", "")
            category = meta.get("category", "")
            skill_type = meta.get("type", "knowledge")

            cur.execute(
                """INSERT INTO managed_skill
                   (id, name, description, category, skill_type, triggers, tags,
                    is_global, is_active, current_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?)""",
                (
                    skill_id, name, description, category, skill_type,
                    json.dumps(triggers, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False),
                    now, now,
                ),
            )

            # Create version
            ver_id = uuid4().hex
            cur.execute(
                """INSERT INTO skill_version
                   (id, skill_id, version, content, changelog, is_current, created_at)
                   VALUES (?, ?, 1, ?, 'Initial version (auto-seeded)', 1, ?)""",
                (ver_id, skill_id, content, now),
            )

            # Import associated scripts
            script_files = meta.get("scripts", [])
            if isinstance(script_files, str):
                script_files = [script_files]
            for script_name in script_files:
                script_path = SKILL_EXAMPLES_DIR / script_name
                if script_path.is_file():
                    script_content = script_path.read_text(encoding="utf-8")
                    ext = script_path.suffix.lstrip(".")
                    lang_map = {
                        "py": "python", "sh": "bash", "js": "javascript",
                        "ts": "typescript", "go": "go", "rs": "rust",
                    }
                    lang = lang_map.get(ext, ext)
                    script_id = uuid4().hex
                    cur.execute(
                        """INSERT INTO skill_script
                           (id, skill_id, filename, language, content, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (script_id, skill_id, script_name, lang, script_content, now, now),
                    )
                    _logger.info(f"  Seeded script: {script_name}")
                else:
                    _logger.warning(f"  Script not found: {script_path}")

            created += 1
            _logger.info(f"Seeded skill: {name} (triggers={triggers})")

        conn.commit()
        if created > 0:
            _logger.info(f"Skill seed complete: {created} new skill(s) created")
        return created

    except Exception as e:
        _logger.warning(f"Skill seed failed: {e}", exc_info=True)
        conn.rollback()
        return 0
    finally:
        conn.close()
