#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""
Skill Evaluator - Automated discovery and structure checks for skills.

Runs Stage 1 (discovery) checks that can be automated:
- Frontmatter validation
- Description quality analysis
- Structure compliance
- Token budget estimation

Stages 2 (logic) and 3 (edge cases) require LLM interaction - see SKILL.md.

Usage:
    eval_skill.py <skill-folder>
    eval_skill.py <skill-folder> --json   # emit deterministic question records as JSON
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from utils import force_utf8_stdio  # noqa: E402  # pyright: ignore[reportMissingImports]  # resolved at runtime via sys.path.insert above


# Deterministic question bank (id -> dimension, critical, text, violation_example).
# eval_skill.py is the SOLE emitter of these records (see SHARED CONTRACT).
DET_QUESTIONS = {
    "DET-STRUCT-SKILLMD-EXISTS": (
        "Structure", True,
        "Does SKILL.md exist?",
        "The skill folder has no SKILL.md file.",
    ),
    "DET-STRUCT-NO-README": (
        "Structure", False,
        "Is there no README.md inside the skill?",
        "A README.md file exists inside the skill folder.",
    ),
    "DET-STRUCT-NO-CHANGELOG": (
        "Structure", False,
        "Is there no CHANGELOG.md inside the skill?",
        "A CHANGELOG.md file exists inside the skill folder.",
    ),
    "DET-STRUCT-REFS-DEPTH": (
        "Structure", False,
        "Are references nested at most 1 level deep?",
        "A file under references/ is nested more than 1 level deep.",
    ),
    "DET-STRUCT-FRONTMATTER-VALID": (
        "Structure", True,
        "Is the YAML frontmatter present and valid?",
        "SKILL.md has missing, malformed, or non-dict YAML frontmatter.",
    ),
    "DET-DISCOVERY-NAME-VALID": (
        "Discovery", True,
        "Is name kebab-case, <=64 chars, matching the folder?",
        "The name is missing, not kebab-case, too long, or does not match the folder.",
    ),
    "DET-DISCOVERY-DESC-PRESENT": (
        "Discovery", True,
        "Is description present, <=1024 chars, free of angle brackets, and a string (not a YAML list)?",
        "The description is missing, too long, contains angle brackets, or is not a string.",
    ),
    "DET-DISCOVERY-TRIGGERS": (
        "Discovery", False,
        "Does the description contain trigger phrases (e.g. 'Use when ...')?",
        "The description has no trigger phrases like 'Use when ...'.",
    ),
    "DET-DISCOVERY-NEG-TRIGGERS": (
        "Discovery", False,
        "Does the description contain negative triggers (e.g. 'Do NOT use for ...')?",
        "The description has no negative triggers like 'Do NOT use for ...'.",
    ),
    "DET-DISCOVERY-NO-PROCESS-LEAK": (
        "Discovery", False,
        "Is the description free of multi-step process/workflow language?",
        "The description contains multi-step process/workflow language.",
    ),
    "DET-STRUCT-BODY-LENGTH": (
        "Structure", False,
        "Is the SKILL.md body at most 500 lines?",
        "The SKILL.md body exceeds 500 lines.",
    ),
    "DET-COMPLETE-NO-TODO": (
        "Completeness", False,
        "Is the body free of [TODO] placeholders?",
        "The body contains [TODO] placeholders.",
    ),
    "DET-STRUCT-HEADERS": (
        "Structure", False,
        "Does the body have at least 2 section headers?",
        "The body has fewer than 2 section headers.",
    ),
    "DET-STRUCT-MOC": (
        "Structure", False,
        "Is the body a map (not a long prose dump with few section anchors)?",
        "The body is a long prose dump with few section anchors.",
    ),
    "DET-ROBUST-NO-SECRETS": (
        "Robustness", True,
        "Is SKILL.md free of secrets/env/keys (API keys, exported env vars)?",
        "SKILL.md contains secrets, API keys, or exported env vars.",
    ),
    "DET-ROBUST-NO-USERPATHS": (
        "Robustness", False,
        "Is SKILL.md free of user-absolute paths (/home/<user>, /Users/<user>)?",
        "SKILL.md contains user-absolute paths.",
    ),
    "DET-ROBUST-SCRIPTS-NONEMPTY": (
        "Robustness", False,
        "Are all bundled scripts non-empty?",
        "A bundled script file is empty.",
    ),
}


def count_words(text):
    return len(text.split())


def count_lines(text):
    return len(text.strip().splitlines())


def eval_skill(skill_path, json_mode=False):
    skill_path = Path(skill_path).resolve()

    # Local counters instead of globals — safe for repeated calls
    counts = {"passed": 0, "failed": 0, "warned": 0}

    # Deterministic question records (only emitted in --json mode)
    records = []
    records_by_id = {}

    def emit(cid, answer, explanation):
        """Record a deterministic question answer. A later 'no' (0) downgrades a
        prior 'yes' (1) so composite/multi-item checks collapse to one record."""
        dimension, critical, text, violation = DET_QUESTIONS[cid]
        existing = records_by_id.get(cid)
        if existing is not None:
            if answer == 0:
                if existing["answer"] == 1:
                    existing["answer"] = 0
                    existing["explanation"] = explanation
                elif explanation not in existing["explanation"]:
                    existing["explanation"] += "; " + explanation
            return
        rec = {
            "id": cid,
            "dimension": dimension,
            "text": text,
            "violation_example": violation,
            "source": "deterministic",
            "critical": critical,
            "answer": answer,
            "explanation": explanation,
        }
        records.append(rec)
        records_by_id[cid] = rec

    def say(msg):
        if not json_mode:
            print(msg)

    def ok(msg, cid=None):
        counts["passed"] += 1
        say(f"  ✅ {msg}")
        if cid:
            emit(cid, 1, msg)

    def fail(msg, cid=None):
        counts["failed"] += 1
        say(f"  ❌ {msg}")
        if cid:
            emit(cid, 0, msg)

    def warn(msg, cid=None):
        counts["warned"] += 1
        say(f"  ⚠️  {msg}")
        if cid:
            emit(cid, 0, msg)

    def finish(result):
        if json_mode:
            print(json.dumps(records, indent=2))
        return result

    say(f"\n🔍 Evaluating: {skill_path.name}\n")

    # --- Structure checks ---
    say("📁 Structure:")

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        fail("SKILL.md not found", "DET-STRUCT-SKILLMD-EXISTS")
        return finish(False)
    ok("SKILL.md exists", "DET-STRUCT-SKILLMD-EXISTS")

    # Check for forbidden files
    readme = skill_path / "README.md"
    if readme.exists():
        fail("README.md found inside skill (should not exist)", "DET-STRUCT-NO-README")
    else:
        ok("No README.md inside skill", "DET-STRUCT-NO-README")

    changelog = skill_path / "CHANGELOG.md"
    if changelog.exists():
        fail("CHANGELOG.md found inside skill", "DET-STRUCT-NO-CHANGELOG")
    else:
        emit("DET-STRUCT-NO-CHANGELOG", 1, "No CHANGELOG.md inside skill")

    # Check reference depth
    refs_dir = skill_path / "references"
    if refs_dir.exists():
        deep_files = []
        for f in refs_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(refs_dir)
                if len(rel.parts) > 2:
                    deep_files.append(str(rel))
        if deep_files:
            fail(f"References nested too deep (max 1 level): {deep_files[:3]}", "DET-STRUCT-REFS-DEPTH")
        else:
            ok("References depth OK (≤1 level)", "DET-STRUCT-REFS-DEPTH")
    else:
        emit("DET-STRUCT-REFS-DEPTH", 1, "No references/ directory (depth OK)")

    # --- Frontmatter checks ---
    say("\n📋 Frontmatter:")

    content = skill_md.read_text()
    if not content.startswith("---"):
        fail("No YAML frontmatter", "DET-STRUCT-FRONTMATTER-VALID")
        return finish(False)

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        fail("Invalid frontmatter delimiters", "DET-STRUCT-FRONTMATTER-VALID")
        return finish(False)
    ok("Valid frontmatter format", "DET-STRUCT-FRONTMATTER-VALID")

    try:
        fm = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        fail(f"YAML parse error: {e}", "DET-STRUCT-FRONTMATTER-VALID")
        return finish(False)

    if not isinstance(fm, dict):
        fail("Frontmatter is not a dict", "DET-STRUCT-FRONTMATTER-VALID")
        return finish(False)

    # Name
    name = fm.get("name", "")
    if not name:
        fail("Missing 'name'", "DET-DISCOVERY-NAME-VALID")
    elif not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        fail(f"Name '{name}' not valid kebab-case", "DET-DISCOVERY-NAME-VALID")
    elif len(name) > 64:
        fail(f"Name too long ({len(name)} chars, max 64)", "DET-DISCOVERY-NAME-VALID")
    elif name != skill_path.name:
        warn(f"Name '{name}' doesn't match folder '{skill_path.name}'", "DET-DISCOVERY-NAME-VALID")
    else:
        ok(f"Name: {name}", "DET-DISCOVERY-NAME-VALID")

    # Description
    desc = fm.get("description", "")
    if not desc:
        fail("Missing 'description'", "DET-DISCOVERY-DESC-PRESENT")
    elif not isinstance(desc, str):
        fail(f"Description must be a string, not {type(desc).__name__} — likely unquoted [brackets] parsed as a YAML list; wrap the value in quotes or use '>'", "DET-DISCOVERY-DESC-PRESENT")
    else:
        if len(desc) > 1024:
            fail(f"Description too long ({len(desc)} chars, max 1024)", "DET-DISCOVERY-DESC-PRESENT")
        else:
            ok(f"Description length: {len(desc)} chars", "DET-DISCOVERY-DESC-PRESENT")

        if "<" in desc or ">" in desc:
            fail("Description contains angle brackets", "DET-DISCOVERY-DESC-PRESENT")

        # Trigger analysis
        desc_lower = desc.lower()
        has_trigger = any(phrase in desc_lower for phrase in [
            "use when", "use for", "trigger", "use if"
        ])
        if has_trigger:
            ok("Description has trigger phrases", "DET-DISCOVERY-TRIGGERS")
        else:
            warn("Description missing trigger phrases (add 'Use when...')", "DET-DISCOVERY-TRIGGERS")

        has_negative = any(phrase in desc_lower for phrase in [
            "not for", "don't use", "do not use", "not when", "not suitable"
        ])
        if has_negative:
            ok("Description has negative triggers", "DET-DISCOVERY-NEG-TRIGGERS")
        else:
            warn("Consider adding negative triggers ('Do NOT use for...')", "DET-DISCOVERY-NEG-TRIGGERS")

        # Process leak detection
        process_signals = [
            r"then\s+\w+",
            r"first\s+\w+.*then",
            r"step\s+\d",
            r"phase\s+\d",
            r"followed\s+by",
            r"after\s+\w+ing.*\w+",
        ]
        leaked_pattern = next((p for p in process_signals if re.search(p, desc_lower)), None)
        if leaked_pattern:
            warn(f"Description may contain process/workflow (pattern: '{leaked_pattern}'). Agent may skip body!", "DET-DISCOVERY-NO-PROCESS-LEAK")
        else:
            emit("DET-DISCOVERY-NO-PROCESS-LEAK", 1, "No process/workflow language in description")

    # Unexpected keys
    # NOTE: this check has no deterministic contract id — human-only, not in JSON.
    allowed = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
    unexpected = set(fm.keys()) - allowed
    if unexpected:
        warn(f"Unexpected frontmatter keys: {unexpected}")

    # --- Body checks ---
    say("\n📝 Body:")

    body = content[match.end():]
    body_lines = count_lines(body)
    body_words = count_words(body)

    if body_lines > 500:
        fail(f"Body too long: {body_lines} lines (max 500). Move detail to references/", "DET-STRUCT-BODY-LENGTH")
    elif body_lines > 400:
        # Advisory only: still <=500, so the "at most 500 lines?" question is satisfied (answer 1).
        warn(f"Body approaching limit: {body_lines} lines (max 500)")
        emit("DET-STRUCT-BODY-LENGTH", 1, f"Body is {body_lines} lines (<=500, approaching limit)")
    else:
        ok(f"Body size: {body_lines} lines, {body_words} words", "DET-STRUCT-BODY-LENGTH")

    # Check for TODO remnants
    if "[TODO" in body:
        warn("Body contains [TODO] placeholders", "DET-COMPLETE-NO-TODO")
    else:
        emit("DET-COMPLETE-NO-TODO", 1, "No [TODO] placeholders in body")

    # Check for headers
    headers = re.findall(r"^#+\s+.+$", body, re.MULTILINE)
    if len(headers) < 2:
        warn("Body has very few headers - consider adding structure", "DET-STRUCT-HEADERS")
    else:
        ok(f"Body structure: {len(headers)} sections", "DET-STRUCT-HEADERS")

    # MOC heuristic (Principle 3): long body with few section anchors = prose dump, not a map
    if body_lines > 250 and len(headers) < body_lines / 40:
        warn("Body is long with few section anchors — make SKILL.md a map, push detail to references/ (Principle 3, MOC)", "DET-STRUCT-MOC")
    else:
        emit("DET-STRUCT-MOC", 1, "Body reads as a map, not a prose dump")

    # Secret / env / user-path leak detection (Principle 9a): keys belong in references/env, never in SKILL.md
    secret_patterns = [
        (r"(?im)\b(api[_-]?key|secret|passwd|password|access[_-]?key|auth[_-]?token)\s*[:=]\s*\S", "secret assignment"),
        (r"sk-[A-Za-z0-9]{16,}", "API key token"),
        (r"(?m)^\s*export\s+[A-Z][A-Z0-9_]*=", "exported env var"),
    ]
    leaks = [label for pat, label in secret_patterns if re.search(pat, body)]
    if leaks:
        fail(f"SKILL.md leaks secrets/env ({', '.join(leaks)}) — move to references/ (Principle 9a)", "DET-ROBUST-NO-SECRETS")
    else:
        ok("No secrets/env leaked in SKILL.md", "DET-ROBUST-NO-SECRETS")

    if re.search(r"/(?:home|Users)/[a-z][a-zA-Z0-9_-]*/", body):
        warn("SKILL.md has user-absolute paths (/home/<user> or /Users/<user>) — use ~ or a reference (Principle 9a)", "DET-ROBUST-NO-USERPATHS")
    else:
        emit("DET-ROBUST-NO-USERPATHS", 1, "No user-absolute paths in SKILL.md")

    # --- Scripts check ---
    scripts_dir = skill_path / "scripts"
    if scripts_dir.exists():
        say("\n🔧 Scripts:")
        scripts = list(scripts_dir.glob("*.py")) + list(scripts_dir.glob("*.sh"))
        for script in scripts:
            if not script.stat().st_size:
                fail(f"Empty script: {script.name}", "DET-ROBUST-SCRIPTS-NONEMPTY")
            else:
                ok(f"Script: {script.name} ({script.stat().st_size} bytes)", "DET-ROBUST-SCRIPTS-NONEMPTY")
    # Backfill a passing record when there are no scripts to flag (no dir / empty dir)
    if "DET-ROBUST-SCRIPTS-NONEMPTY" not in records_by_id:
        emit("DET-ROBUST-SCRIPTS-NONEMPTY", 1, "No empty scripts (or no scripts present)")

    # --- Summary ---
    say(f"\n{'='*50}")
    total = counts["passed"] + counts["failed"] + counts["warned"]
    score = round((counts["passed"] / total) * 10) if total else 0
    say(f"✅ {counts['passed']} passed | ❌ {counts['failed']} failed | ⚠️  {counts['warned']} warnings")
    say(f"Score: {score}/10")

    if counts["failed"] == 0 and counts["warned"] == 0:
        say("🏆 Skill is clean!")
    elif counts["failed"] == 0:
        say("👍 Skill is valid with minor suggestions")
    else:
        say("🔧 Fix failed checks before packaging")

    return finish(counts["failed"] == 0)


if __name__ == "__main__":
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Skill evaluator (discovery/structure checks)")
    parser.add_argument("skill_folder", help="Path to the skill folder to evaluate")
    parser.add_argument("--json", action="store_true",
                        help="Emit deterministic question records as a JSON array to stdout")
    args = parser.parse_args()
    result = eval_skill(args.skill_folder, json_mode=args.json)
    # Human mode keeps the original exit code (non-zero on any failed/critical check).
    # JSON mode always exits 0 so consumers parse stdout regardless of pass/fail.
    sys.exit(0 if (result or args.json) else 1)
