"""Preview or atomically install the approved fallback order in a runtime .env."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import stat
import tempfile

LITE = "gemini-3.5-flash-lite"
CHAIN_KEYS = {
    "GEMINI_MODEL_CHAIN", "BOB_GEMINI_MODEL_CHAIN", "BOB_PREMIUM_MODEL_CHAIN",
    "BOB_STANDARD_MODEL_CHAIN", "NEWS_GEMINI_MODEL_CHAIN", "GEMINI_NEWS_MODEL_CHAIN",
    "NEWS_TITLE_GEMINI_MODEL_CHAIN", "REPORT_GEMINI_MODEL_CHAIN",
    "GEMINI_REPORT_MODEL_CHAIN", "ALFRED_QUOTE_RESOLVER_MODEL_CHAIN",
}


def migrate(text: str) -> tuple[str, list[str]]:
    changed, lines = [], []
    for line in text.splitlines(keepends=True):
        key, sep, value = line.partition("=")
        name = key.strip().removeprefix("export ").strip()
        if sep and name in CHAIN_KEYS:
            values = shlex.split(value, comments=True)
            chain = [v.strip() for v in values[0].split(",") if v.strip()] if values else []
            if len(chain) > 1 and chain[0] != LITE:
                updated = [chain[0], LITE] + [v for v in chain[1:] if v != LITE]
                if updated != chain:
                    ending = "\n" if line.endswith("\n") else ""
                    line = key + "=" + ",".join(updated) + ending
                    changed.append(name)
        lines.append(line)
    return "".join(lines), changed


def install(path: Path, *, apply: bool = False) -> list[str]:
    original = path.read_text()
    updated, changed = migrate(original)
    if apply and changed:
        metadata = path.stat()
        fd, temp = tempfile.mkstemp(prefix=".owtv-env-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, stat.S_IMODE(metadata.st_mode))
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changed = install(args.env_file, apply=args.apply)
    print(("Updated: " if args.apply else "Would update: ") + (", ".join(changed) or "none"))
