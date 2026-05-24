from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from apply_runtime_chain_v90_2_6 import PATCH_CHAIN, REQUIRED_MARKERS

CONSOLIDATION_MARK = "v90.2.6.1 true source consolidation"


def source_has_all_markers() -> bool:
    text = Path("bot.py").read_text(encoding="utf-8")
    return all(marker in text for marker in REQUIRED_MARKERS)


def run_patch_chain() -> None:
    for patch in PATCH_CHAIN:
        p = Path(patch)
        if not p.exists():
            raise SystemExit(f"[v90.2.6.1] patch mancante: {patch}")
        print(f"[v90.2.6.1] apply {patch}", flush=True)
        subprocess.run([sys.executable, patch], check=True)


def write_consolidation_marker() -> None:
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if CONSOLIDATION_MARK in text:
        return
    marker = f'\n\n# {CONSOLIDATION_MARK}\n'
    needle = '\n\nif __name__ == "__main__":\n'
    if needle in text:
        text = text.replace(needle, marker + needle, 1)
    else:
        text += marker
    p.write_text(text, encoding="utf-8")


def verify() -> None:
    text = Path("bot.py").read_text(encoding="utf-8")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in text]
    if missing:
        raise SystemExit("[v90.2.6.1] marker mancanti dopo consolidamento: " + ", ".join(missing))
    subprocess.run([sys.executable, "-m", "py_compile", "bot.py"], check=True)
    print("[SOURCE CONSOLIDATION v90.2.6.1] bot.py consolidato e compilabile", flush=True)


def main() -> int:
    if source_has_all_markers():
        print("[v90.2.6.1] bot.py gia consolidato: skip patch chain", flush=True)
        write_consolidation_marker()
        verify()
        return 0

    print("[v90.2.6.1] bot.py non consolidato: applico patch chain una tantum", flush=True)
    run_patch_chain()
    write_consolidation_marker()
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
