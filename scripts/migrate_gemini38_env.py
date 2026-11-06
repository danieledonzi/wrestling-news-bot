"""Preview or atomically migrate deprecated Gemini 2.5 Pro in effective chain env keys.

Historical prices, old ledgers and non-chain settings are never modified.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import tempfile
from pathlib import Path

OLD = "gemini-2.5-pro"
NEW = "gemini-3.8-flash"
CHAIN_KEYS = {
    "GEMINI_MODEL_CHAIN", "BOB_GEMINI_MODEL_CHAIN", "BOB_PREMIUM_MODEL_CHAIN",
    "BOB_STANDARD_MODEL_CHAIN", "NEWS_GEMINI_MODEL_CHAIN", "GEMINI_NEWS_MODEL_CHAIN",
    "NEWS_TITLE_GEMINI_MODEL_CHAIN", "REPORT_GEMINI_MODEL_CHAIN",
    "GEMINI_REPORT_MODEL_CHAIN", "ALFRED_QUOTE_RESOLVER_MODEL_CHAIN",
    "MENZO_DUPLICATE_ARBITRATION_MODEL_CHAIN", "V90_2_2_TRANSLATE_REPORT_CHAIN",
}


def migrate(text: str) -> tuple[str, list[str]]:
    changed = []
    lines = []
    for line in text.splitlines(keepends=True):
        head, sep, value = line.partition("=")
        key = head.strip().removeprefix("export ").strip()
        if not sep or key not in CHAIN_KEYS:
            lines.append(line)
            continue
        suffix = "\r\n" if value.endswith("\r\n") else "\n" if value.endswith("\n") else ""
        plain = value[:-len(suffix)] if suffix else value
        prefix = plain[:len(plain) - len(plain.lstrip())]
        raw = plain[len(prefix):]
        quote = raw[0] if raw[:1] in ("'", '"') else ""
        if quote:
            stop = raw.find(quote, 1)
            if stop == -1:
                lines.append(line)
                continue
            chain, trail = raw[1:stop], raw[stop + 1:]
        else:
            chain, mark, tail = raw.partition("#")
            # The separator belongs to the comment, not to the model list.
            trail = chain[len(chain.rstrip()):] + mark + tail if mark else ""
        terms = [s.strip() for s in chain.strip().split(",") if s.strip()]
        if OLD not in terms:
            lines.append(line)
            continue
        unique = []
        for value_id in terms:
            candidate = NEW if value_id == OLD else value_id
            if candidate not in unique:
                unique.append(candidate)
        updated = head + "=" + prefix + quote + ",".join(unique) + quote + trail + suffix
        lines.append(updated)
        changed.append(key)
    return "".join(lines), changed


def install(path: Path, *, apply: bool = False) -> tuple[list[str], Path | None]:
    original = path.read_bytes()
    new_text, changed = migrate(original.decode("utf-8"))
    if not changed or not apply:
        return changed, None
    before = path.stat()
    backup = path.with_name(path.name + ".pre-gemini38.bak")
    if backup.exists():
        if backup.read_bytes() != original:
            raise RuntimeError("Backup already exists and differs; aborting")
    else:
        shutil.copy2(path, backup)
    fd, tmp = tempfile.mkstemp(prefix=".owtv-gemini38-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            # Atomic replacement must retain service-account ownership when
            # the migration is invoked by a privileged deployment user.
            os.fchown(out.fileno(), before.st_uid, before.st_gid)
            os.fchmod(out.fileno(), stat.S_IMODE(before.st_mode))
            out.write(new_text.encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return changed, backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    keys, backup = install(args.env_file, apply=args.apply)
    print(("Applied" if args.apply else "Preview") + ": " + (", ".join(keys) if keys else "nothing to change"))
    if backup is not None:
        print("Backup: " + str(backup))
