from pathlib import Path
import runpy


def _run_patch(path_str, label):
    script = Path(path_str)
    if not script.exists():
        raise SystemExit(f"{label} script missing")
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
    print(f"[{label}] applied")


def main():
    text = Path("bot.py").read_text(encoding="utf-8")
    if "v88.2: editorial performance guards" not in text:
        raise SystemExit("v88.2 base missing")
    print("[SOURCE v88.2] bot.py gia aggiornato")
    _run_patch("scripts/apply_bot_patch_v88_3.py", "SOURCE v88.3")
    _run_patch("scripts/apply_bot_patch_v88_3_1.py", "SOURCE v88.3.1")
    _run_patch("scripts/apply_bot_patch_v88_4.py", "SOURCE v88.4")
    _run_patch("scripts/apply_bot_patch_v88_4_1.py", "SOURCE v88.4.1")
    _run_patch("scripts/apply_bot_patch_v88_4_2.py", "SOURCE v88.4.2")
    _run_patch("scripts/apply_bot_patch_v88_4_2_1.py", "SOURCE v88.4.2.1")
    _run_patch("scripts/apply_bot_patch_v89.py", "SOURCE v89")


if __name__ == "__main__":
    main()
    raise SystemExit(0)
