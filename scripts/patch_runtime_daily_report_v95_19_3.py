#!/usr/bin/env python3
"""Safely align the external VPS daily-email runner with canonical metrics.

The scheduled runner lives outside the git checkout at /opt/owtv/send_daily_report.py.
This tool applies a narrow, idempotent text migration and fails closed when the
expected v95.16a anchors are not present.
"""
from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path("/opt/owtv/send_daily_report.py")
PATCH_MARKER = "SINTESI EDITORIALE AUTOREVOLE"


class PatchError(RuntimeError):
    pass


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(text: str) -> tuple[str, list[str]]:
    if PATCH_MARKER in text and "repository_report.daily_editorial_judgment_body_section" in text:
        return text, ["already_patched"]

    changes: list[str] = []

    old_summary = "    daily_judgment_summary = daily_judgment_body_summary(daily_judgment_error)\n"
    new_summary = '''    if (\n        repository_report is not None\n        and daily_judgment_json\n        and daily_judgment_json.exists()\n    ):\n        daily_judgment_summary = (\n            repository_report.daily_editorial_judgment_body_section(\n                daily_judgment_json,\n                daily_judgment_error,\n            ).strip()\n        )\n    else:\n        daily_judgment_summary = daily_judgment_body_summary(daily_judgment_error)\n'''
    text = _replace_once(text, old_summary, new_summary, "canonical judgment helper")
    changes.append("canonical_judgment_helper")

    extraction_pattern = re.compile(
        r'^    ed_news = extract_line\(editorial_report, "- News pubblicate dal Publisher:"\)\n'
        r'^    ed_reports = extract_line\(editorial_report, "- Report show pubblicati da Simone:"\)\n'
        r'^    ed_html = extract_line\(editorial_report, "- HTML finali rilevati nel periodo:"\)\n'
        r'^    ed_fp = extract_line\(editorial_report, "- Duplicati footprint rilevati da Menzo:"\)\n'
        r'^    ed_fingerprint = extract_line\(editorial_report, "- Duplicati fingerprint rilevati da Menzo:"\)\n'
        r'^    ed_warn = extract_line\(editorial_report, "- Warning Alfred:"\)\n'
        r'^    ed_block = extract_line\(editorial_report, "- Blocker Alfred:"\)\n'
        r'^    ed_ratio = extract_line\(editorial_report, "- Rapporto selected finale / candidati MenzoAI:"\)\n',
        flags=re.MULTILINE,
    )
    text, count = extraction_pattern.subn("", text, count=1)
    if count != 1:
        raise PatchError(f"legacy editorial extraction: expected one block, found {count}")
    changes.append("remove_legacy_editorial_extraction")

    legacy_body = '''SINTESI EDITORIALE
{ed_news}
{ed_reports}
{ed_html}
{ed_fp}
{ed_fingerprint}
{ed_warn}
{ed_block}
{ed_ratio}
'''
    authoritative_body = '''SINTESI EDITORIALE AUTOREVOLE
{daily_judgment_summary}
'''
    text = _replace_once(text, legacy_body, authoritative_body, "legacy editorial email section")
    changes.append("replace_legacy_editorial_email_section")

    duplicate_judgment = '''DAILY EDITORIAL JUDGMENT
{daily_judgment_summary}

'''
    text = _replace_once(text, duplicate_judgment, "", "duplicate judgment email section")
    changes.append("remove_duplicate_judgment_section")

    old_note = (
        "L'audit editoriale v1.1 non usa AI aggiuntiva. Serve a monitorare selezione MenzoAI, "
        "distribuzione editoriale, report show, warning Alfred, duplicati e campioni consigliati per revisione umana."
    )
    new_note = (
        "L'audit editoriale v1.1 resta allegato come diagnostica legacy. "
        "La sintesi nel corpo usa le metriche canoniche del Daily Editorial Judgment."
    )
    text = _replace_once(text, old_note, new_note, "legacy audit note")
    changes.append("clarify_legacy_attachment_note")

    return text, changes


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate that the migration can be applied without writing")
    mode.add_argument("--apply", action="store_true", help="Back up and patch the runtime runner")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    path: Path = args.path
    if not path.is_file():
        raise SystemExit(f"runtime runner not found: {path}")

    original = path.read_text(encoding="utf-8")
    try:
        patched, changes = transform(original)
    except PatchError as exc:
        raise SystemExit(f"patch check failed: {exc}") from exc

    if changes == ["already_patched"]:
        print(f"already_patched={path}")
        return 0

    print("changes=" + ",".join(changes))
    if args.check:
        print(f"mode=check path={path}")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.pre_v95_19_3_{stamp}")
    shutil.copy2(path, backup)
    path.write_text(patched, encoding="utf-8")
    print(f"backup={backup}")
    print(f"mode=applied path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
