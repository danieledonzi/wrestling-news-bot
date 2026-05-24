from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PATCH_CHAIN = [
    "scripts/apply_bot_patch_v90_1.py",
    "scripts/apply_bot_patch_v90_1_review_fix.py",
    "scripts/apply_bot_patch_v90_1_1.py",
    "scripts/apply_bot_patch_v90_1_2.py",
    "scripts/apply_bot_patch_v90_1_3.py",
    "scripts/apply_bot_patch_v90_2.py",
    "scripts/apply_bot_patch_v90_2_1.py",
    "scripts/apply_bot_patch_v90_2_2.py",
    "scripts/apply_bot_patch_v90_2_3.py",
    "scripts/apply_bot_patch_v90_2_3_1.py",
    "scripts/apply_bot_patch_v90_2_4.py",
    "scripts/apply_bot_patch_v90_2_4_1.py",
    "scripts/apply_bot_patch_v90_2_4_2.py",
    "scripts/apply_bot_patch_v90_2_5.py",
    "scripts/apply_bot_patch_v90_2_5_1.py",
    "scripts/apply_bot_patch_v90_2_5_2.py",
    "scripts/apply_bot_patch_v90_2_5_3.py",
    "scripts/apply_bot_patch_v90_2_5_3_1.py",
    "scripts/apply_bot_patch_v90_2_5_4.py",
    "scripts/apply_bot_patch_v90_2_5_4_1.py",
]

REQUIRED_MARKERS = [
    "v90.2.1: report dedupe protection",
    "v90.2.2: report flow tuning",
    "v90.2.3: social embed quote positioning",
    "v90.2.3.1: inline image dict normalization",
    "v90.2.4: offline pending hard-skip guard",
    "v90.2.4.1 report hard title",
    "v90.2.4.2 report casing guard",
    "v90.2.5 processed URL hard-skip",
    "v90.2.5.1 processed skip recorder",
    "v90.2.5.2 processed competitive guard",
    "v90.2.5.3 SNME event and publish processed guards",
    "v90.2.5.3.1 tighten SNME and publish guards",
    "v90.2.5.4 event registry",
    "v90.2.5.4.1 event registry report key",
]


def run_patch(path: str) -> None:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[v90.2.6] patch mancante: {path}")
    print(f"[v90.2.6] apply {path}", flush=True)
    subprocess.run([sys.executable, path], check=True)


def verify_source() -> None:
    text = Path("bot.py").read_text(encoding="utf-8")
    missing = [m for m in REQUIRED_MARKERS if m not in text]
    if missing:
        raise SystemExit("[v90.2.6] marker mancanti dopo runtime chain: " + ", ".join(missing))
    print("[SOURCE CONSOLIDATION v90.2.6] bot.py contiene la chain runtime consolidata fino a v90.2.5.4.1", flush=True)


def main() -> int:
    print("[v90.2.6] runtime patch chain consolidata: start", flush=True)
    for patch in PATCH_CHAIN:
        run_patch(patch)
    verify_source()
    print("[v90.2.6] runtime patch chain consolidata: ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
