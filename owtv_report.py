from __future__ import annotations

from agents.gemini_diagnostics import (
    build_gemini_diagnostics,
    load_ledger,
    render_gemini_diagnostics_markdown,
)


def render_gemini_detailed_ledger_24h() -> str:
    records, warnings = load_ledger()
    markdown = render_gemini_diagnostics_markdown(build_gemini_diagnostics(records))
    if warnings:
        markdown += "\n### Gemini ledger warnings\n" + "\n".join(f"- {w}" for w in warnings[:10]) + "\n"
    return markdown


if __name__ == "__main__":
    print(render_gemini_detailed_ledger_24h())
