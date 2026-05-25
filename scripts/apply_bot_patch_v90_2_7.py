from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PATCHES = [
    "scripts/apply_bot_patch_v90_2_7_2.py",
    "scripts/apply_bot_patch_v90_2_8.py",
]


def main() -> int:
    for patch in PATCHES:
        p = Path(patch)
        if not p.exists():
            raise SystemExit(f"[SOURCE PATCH v90.2.8] patch mancante: {patch}")
        print(f"[SOURCE PATCH v90.2.8] apply {patch}", flush=True)
        subprocess.run([sys.executable, patch], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
