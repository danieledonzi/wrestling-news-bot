from pathlib import Path

MARK = "# v91.5.2 final safe print recursion guard"
CODE = r'''

# v91.5.2 final safe print recursion guard
V91_5_2_ENABLED = os.getenv("V91_5_2_ENABLED", "1").lower() not in {"0", "false", "no", "off"}

try:
    _PREV_V9152_PRINT = print
except Exception:
    _PREV_V9152_PRINT = None

_V9152_PRINT_BUSY = False


def v9152_safe_print(*args, **kwargs):
    """Outermost print guard.

    Several historical versions wrap print/stdout for master-log capture. After many stacked
    patches, that chain can recurse through stream.flush(). This final guard avoids the
    wrapper chain and writes deterministically to real stdout plus logs/master_log.log.
    """
    global _V9152_PRINT_BUSY
    if not V91_5_2_ENABLED:
        if _PREV_V9152_PRINT:
            return _PREV_V9152_PRINT(*args, **kwargs)
        return None
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    try:
        msg = sep.join(str(a) for a in args) + end
    except Exception:
        msg = " ".join(repr(a) for a in args) + end
    if _V9152_PRINT_BUSY:
        try:
            sys.__stdout__.write(msg)
            sys.__stdout__.flush()
        except Exception:
            pass
        return None
    _V9152_PRINT_BUSY = True
    try:
        try:
            sys.__stdout__.write(msg)
            sys.__stdout__.flush()
        except Exception:
            pass
        try:
            Path("logs").mkdir(parents=True, exist_ok=True)
            with Path("logs/master_log.log").open("a", encoding="utf-8") as fh:
                fh.write(msg)
        except Exception:
            pass
    finally:
        _V9152_PRINT_BUSY = False
    return None


if V91_5_2_ENABLED:
    print = v9152_safe_print
    print("[BOOT v91.5.2] Final safe print recursion guard attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.5.2] bot.py gia aggiornato")
        return 0
    if "# v91.5.1 final strict publish return guard" not in text:
        raise SystemExit("[SOURCE PATCH v91.5.2] base v91.5.1 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.5.2] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.5.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
