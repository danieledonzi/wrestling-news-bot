from __future__ import annotations

# Compatibility shim: newsroom_runner imports this wrapper name.
# Before Massy runs, rebuild the report registry from manual_runs so manually
# published reports block Simone even if report_status.json was incomplete.
# Active policy v93.24:
# - factual show news remains publishable before report closure
# - report closes only recap/results duplicates
# - publish_after, usually 06:30, is respected before Simone works reports

from agents.massy_policy_v93_24 import run_massy as _run_massy_v93_24


def run_massy():
    try:
        from agents.report_registry_v93_22 import rebuild_from_manual_runs
        result = rebuild_from_manual_runs()
        print(f"[REPORT REGISTRY v93.22] rebuilt from manual_runs | added={result.get('added')} skipped={result.get('skipped')}", flush=True)
    except Exception as exc:
        print(f"[REPORT REGISTRY v93.22] rebuild warning: {exc}", flush=True)
    return _run_massy_v93_24()


__all__ = ["run_massy"]
