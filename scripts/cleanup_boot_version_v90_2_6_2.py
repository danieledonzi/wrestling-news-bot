from __future__ import annotations

import re
from pathlib import Path

MARK = "# v90.2.6.2 clean consolidated boot/version"
VERSION = "v90_2_6_2_clean_consolidated_source"

BOOT_PATTERNS = (
    "[BOOT v88",
    "[BOOT v89",
    "[BOOT v90.1",
    "[BOOT v90.2",
    "[MODEL v90.2.2]",
    "[SPOILER v90.1.3]",
)

FINAL_BLOCK = f'''

{MARK}
BOT_VERSION = "{VERSION}"
BOT_VERSION_FULL = f"{{BOT_VERSION}} ({{GIT_SHA_SHORT}})"
print("[BOOT v90.2.6.2] Source consolidato attivo: chain fino a v90.2.5.4.1", flush=True)
'''


def mute_historic_boot_prints(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    muted = 0
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("print(") and any(token in line for token in BOOT_PATTERNS):
            indent = line[: len(line) - len(stripped)]
            out.append(indent + "# muted by v90.2.6.2: " + stripped)
            muted += 1
        else:
            out.append(line)
    print(f"[v90.2.6.2] boot print storici silenziati: {muted}")
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def remove_existing_final_block(text: str) -> str:
    # Keep the script idempotent if a previous workflow run already inserted the block.
    pattern = re.compile(
        r"\n\n# v90\.2\.6\.2 clean consolidated boot/version\n"
        r"BOT_VERSION = \"v90_2_6_2_clean_consolidated_source\"\n"
        r"BOT_VERSION_FULL = f\"\{BOT_VERSION\} \(\{GIT_SHA_SHORT\}\)\"\n"
        r"print\(\"\[BOOT v90\.2\.6\.2\] Source consolidato attivo: chain fino a v90\.2\.5\.4\.1\", flush=True\)\n",
        re.M,
    )
    return pattern.sub("", text)


def insert_final_block(text: str) -> str:
    text = remove_existing_final_block(text)
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[v90.2.6.2] entrypoint marker not found")
    return text.replace(needle, FINAL_BLOCK + needle, 1)


def main() -> int:
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    original = text
    text = mute_historic_boot_prints(text)
    text = insert_final_block(text)
    if text == original:
        print("[v90.2.6.2] nessuna modifica necessaria")
        return 0
    p.write_text(text, encoding="utf-8")
    print("[v90.2.6.2] bot.py aggiornato: boot storici silenziati e versione finale impostata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
