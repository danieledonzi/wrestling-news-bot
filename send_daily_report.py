from __future__ import annotations

from agents.gemini_diagnostics import build_email_gemini_summary, build_gemini_diagnostics, load_ledger


def gemini_email_summary_24h() -> str:
    records, _warnings = load_ledger()
    return build_email_gemini_summary(build_gemini_diagnostics(records))


if __name__ == "__main__":
    print(gemini_email_summary_24h())
