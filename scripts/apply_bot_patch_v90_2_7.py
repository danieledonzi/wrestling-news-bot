from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PATCHES = [
    "scripts/apply_bot_patch_v90_2_7_2.py",
    "scripts/apply_bot_patch_v90_2_8.py",
    "scripts/apply_bot_patch_v91.py",
    "scripts/apply_bot_patch_v91_1.py",
    "scripts/apply_bot_patch_v91_6.py",
    "scripts/apply_bot_patch_v91_6_1.py",
    "scripts/apply_bot_patch_v91_6_2.py",
    "scripts/apply_bot_patch_v91_6_3.py",
    "scripts/apply_bot_patch_v91_6_4.py",
]


def main() -> int:
    for patch in PATCHES:
        p = Path(patch)
        if not p.exists():
            raise SystemExit(f"[SOURCE PATCH v91] patch mancante: {patch}")
        print(f"[SOURCE PATCH v91] apply {patch}", flush=True)
        subprocess.run([sys.executable, patch], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
