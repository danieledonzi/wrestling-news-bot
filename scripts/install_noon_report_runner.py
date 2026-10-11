"""Install a thin launcher for the existing noon cron, preserving its schedule.

Default VPS layout only; configurable destinations support offline validation.
"""
from __future__ import annotations

import argparse
import py_compile
from datetime import datetime, timezone
from pathlib import Path


def install(root: Path, target: Path, *, python: Path | None = None) -> Path | None:
    python = python or root / ".venv/bin/python"
    content = (f"#!{python}\n"
        '"""OWTV versioned noon reporting launcher; schedule and SMTP config unchanged."""\n'
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from scripts.daily_report_email import main\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n")
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return None
    backup = None
    if target.exists():
        backup = target.with_name(target.name + datetime.now(timezone.utc).strftime(".backup_%Y%m%d_%H%M%S_%f"))
        backup.write_bytes(target.read_bytes())
        backup.chmod(target.stat().st_mode)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    py_compile.compile(str(temporary), doraise=True)
    temporary.chmod(0o755)
    temporary.replace(target)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target", type=Path, default=Path("/opt/owtv/send_daily_report.py"))
    args = parser.parse_args()
    backup = install(args.root.resolve(), args.target)
    print(f"Versioned noon launcher installed; previous launcher backup: {backup or 'unchanged'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
