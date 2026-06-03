from __future__ import annotations

# Compatibility shim: newsroom_runner imports this wrapper name.
# The active Massy policy lives in v93.21 and adds:
# - manually published reports block Simone
# - present/published reports suppress episode news
# - Menzo hard-skip memory
# - old-news hard skip

from agents.massy_policy_v93_21 import run_massy

__all__ = ["run_massy"]
