from __future__ import annotations

from agents.gemini_diagnostics import build_email_gemini_summary, build_gemini_diagnostics, load_ledger


def gemini_email_summary_24h() -> str:
    records, _warnings = load_ledger()
    return build_email_gemini_summary(build_gemini_diagnostics(records))


if __name__ == "__main__":
    print(gemini_email_summary_24h())


from scripts.daily_editorial_judgment import build_report as build_daily_editorial_judgment, email_summary as daily_editorial_judgment_email_summary, generate_daily_editorial_judgment_outputs, generate_daily_editorial_judgment_report, load_inputs as load_daily_editorial_judgment_inputs


def daily_editorial_judgment_summary_24h() -> str:
    """Compact newsroom summary for the 12:00 daily email body."""
    return daily_editorial_judgment_email_summary(build_daily_editorial_judgment(load_daily_editorial_judgment_inputs()))


def daily_editorial_judgment_attachment_24h() -> str:
    """Generate the markdown/JSON report pair and return the markdown path for email attachment/reference."""
    return str(generate_daily_editorial_judgment_outputs()["markdown"])
