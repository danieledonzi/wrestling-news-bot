#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def load_dotenv_minimal(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def model_name(model: object) -> str:
    return str(getattr(model, "name", None) or getattr(model, "model", None) or model)


def interesting(names: Iterable[str]) -> list[str]:
    needles = ("gemini-3", "flash", "3.5")
    return sorted({name for name in names if any(needle in name.lower() for needle in needles)})


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    load_dotenv_minimal(root / ".env")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY assente: impossibile interrogare l'elenco modelli Gemini.")
        return 0
    try:
        from google import genai
    except Exception as exc:
        print(f"google-genai non disponibile: {exc}")
        return 0
    try:
        client = genai.Client(api_key=api_key)
        names = interesting(model_name(model) for model in client.models.list())
    except Exception as exc:
        print(f"Errore durante il recupero modelli Gemini: {exc}")
        return 0
    if not names:
        print("Nessun modello trovato contenente gemini-3, flash o 3.5.")
        return 0
    for name in names:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
