from pathlib import Path
import runpy


def main():
    text = Path("bot.py").read_text(encoding="utf-8")
    if "v88.2: editorial performance guards" not in text:
        raise SystemExit("v88.2 base missing")
    print("[SOURCE v88.2] bot.py gia aggiornato")
    script = Path("scripts/apply_bot_patch_v88_3.py")
    if not script.exists():
        raise SystemExit("v88.3 script missing")
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
    print("[SOURCE v88.3] applied from v88.2 step")


if __name__ == "__main__":
    main()
    raise SystemExit(0)
