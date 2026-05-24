from __future__ import annotations

from pathlib import Path

MARK = "v90.2.6.2 cleanup boot version"
FINAL_BOOT = 'print("[BOOT v90.2.6.2] Source consolidato attivo: chain fino a v90.2.5.4.1")'

NOISY_BOOT_TOKENS = (
    '[BOOT v88.',
    '[BOOT v89',
    '[BOOT v90.1',
    '[BOOT v90.2',
    '[MODEL v90.2.2]',
    '[SPOILER v90.1.3]',
)


def silence_noisy_boot_lines(text: str) -> str:
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('print(') and any(token in stripped for token in NOISY_BOOT_TOKENS):
            indent = line[: len(line) - len(stripped)]
            out.append(indent + 'if os.getenv("V90_2_6_2_VERBOSE_BOOT", "0").lower() in {"1", "true", "yes", "on"}:')
            out.append(indent + '    ' + stripped)
        else:
            out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def set_final_version(text: str) -> str:
    marker_code = f'''\n\n# {MARK}\nBOT_VERSION = "v90_2_6_2_cleanup_boot_version"\nBOT_VERSION_FULL = f"{{BOT_VERSION}} ({{GIT_SHA_SHORT}})"\n{FINAL_BOOT}\n'''
    if MARK in text:
        return text
    needle = '\n\nif __name__ == "__main__":\n'
    if needle in text:
        return text.replace(needle, marker_code + needle, 1)
    return text + marker_code


def main() -> int:
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    before = text
    text = silence_noisy_boot_lines(text)
    text = set_final_version(text)
    if text != before:
        p.write_text(text, encoding="utf-8")
        print("[v90.2.6.2] boot/version cleanup applicato")
    else:
        print("[v90.2.6.2] boot/version cleanup gia applicato")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
