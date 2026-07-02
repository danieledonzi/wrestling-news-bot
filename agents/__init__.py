"""OpenWrestlingTV Virtual Newsroom agents.

Temporary v95.6 trial default:
- keep Bob standard chain unchanged;
- make Bob premium start from gemini-3.1-flash-lite;
- keep gemini-3.5-flash as the first fallback.

The trial only fills missing environment variables. Explicit .env/workflow
settings still take precedence.
"""

from __future__ import annotations

import os

os.environ.setdefault("OWTV_BOB_31_FIRST_35_FALLBACK_TRIAL", "1")
os.environ.setdefault(
    "BOB_PREMIUM_MODEL_CHAIN",
    "gemini-3.1-flash-lite,gemini-3.5-flash,gemini-2.5-flash-lite,gemini-2.5-flash",
)
