#!/usr/bin/env python3
"""Validate and summarize P1.3-native canonical operational lifecycles."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT = Path("state/newsroom/canonical_event_ledger.jsonl")
ATTEMPT_EVENTS = {"model_attempt_started", "model_attempt_completed", "model_attempt_failed"}


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    by_model: Counter[str] = Counter(); by_role: Counter[str] = Counter()
    warnings: Counter[str] = Counter(); blockers: Counter[str] = Counter()
    warning_articles=set(); blocker_articles=set()
    requests=defaultdict(list); attempts=defaultdict(list)
    identity=[]; lifecycle=[]; invariant=[]
    for pos,row in enumerate(rows):
        kind=row.get("event_type"); lrq=row.get("logical_request_id")
        native=isinstance(lrq,str) and lrq.startswith("lrq_")
        if native: requests[lrq].append((pos,row))
        if kind in ATTEMPT_EVENTS:
            counts[kind]+=1
            if not native: # historical rows are not subject to P1.3 completeness
                continue
            aid=row.get("attempt_id"); number=row.get("attempt_number")
            if not aid: identity.append(f"row {pos+1}: attempt without attempt_id")
            if not isinstance(number,int) or isinstance(number,bool) or number < 1:
                identity.append(f"row {pos+1}: invalid attempt_number")
            if aid: attempts[aid].append((pos,row))
            if kind == "model_attempt_started":
                by_model[str(row.get("model_name") or "unknown")]+=1
                by_role[str(row.get("model_role") or "unknown")]+=1
        if kind == "model_attempt_avoided" and native:
            if any(k in row for k in ("attempt_id","attempt_number","latency_ms")):
                identity.append(f"row {pos+1}: avoided request has attempt identity/latency")
        if kind == "fallback_started" and native and (not row.get("fallback_from") or not row.get("fallback_to")):
            lifecycle.append(f"row {pos+1}: fallback missing models")
        if kind in {"warning_recorded","blocker_recorded"}:
            target=warnings if kind=="warning_recorded" else blockers
            articles=warning_articles if kind=="warning_recorded" else blocker_articles
            target[str(row.get("reason_code") or "")]+=1
            if row.get("run_id") and row.get("content_id"): articles.add((row["run_id"],row["content_id"]))
            required = (row.get("run_id"), row.get("content_id"), row.get("correlation_id"), row.get("reason_code"))
            if not all(required):
                identity.append(f"row {pos+1}: {kind} missing identity/code")
            elif row["correlation_id"] != "corr_" + hashlib.sha256(
                    f"{row['run_id']}\0{row['content_id']}".encode()).hexdigest():
                identity.append(f"row {pos+1}: {kind} correlation mismatch")
    for aid, events in attempts.items():
        identities={(r.get("logical_request_id"),r.get("attempt_number"),r.get("model_name"),r.get("model_role")) for _,r in events}
        if len(identities)!=1: identity.append(f"attempt {aid}: lifecycle identity mismatch")
        kinds=[r.get("event_type") for _,r in events]
        if kinds.count("model_attempt_started") != 1: lifecycle.append(f"attempt {aid}: requires exactly one started event")
        outcomes=set(kinds)&{"model_attempt_completed","model_attempt_failed"}
        if len(outcomes)!=1: lifecycle.append(f"attempt {aid}: requires exactly one terminal outcome")
    successful=first=recovered=terminal=avoided=0
    for lrq,events in requests.items():
        ordered=sorted(events); rs=[r for _,r in ordered]; concrete=[r for r in rs if r.get("event_type") in ATTEMPT_EVENTS]
        starts=[r for r in concrete if r.get("event_type")=="model_attempt_started"]
        numbers=[r.get("attempt_number") for r in starts]
        if numbers != list(range(1, len(numbers) + 1)):
            identity.append(f"request {lrq}: attempt numbers must be contiguous 1..N")
        creations=sum(r.get("event_type")=="logical_ai_request_created" for r in rs)
        if creations != 1:
            lifecycle.append(f"request {lrq}: requires exactly one logical_ai_request_created")
        completed=[(p,r) for p,r in ordered if r.get("event_type")=="model_attempt_completed"]
        failed=[(p,r) for p,r in ordered if r.get("event_type")=="model_attempt_failed"]
        if completed: successful+=1
        if completed and not failed and len(starts)==1: first+=1
        if completed and any(not r.get("error_terminal") and p < completed[-1][0] for p,r in failed): recovered+=1
        if not completed and any(r.get("error_terminal") is True for _,r in failed): terminal+=1
        avoided_rows=[r for r in rs if r.get("event_type")=="model_attempt_avoided"]
        if avoided_rows and not concrete: avoided+=1
        for p,r in failed:
            later=[x for q,x in ordered if q>p]
            later_path=any(x.get("event_type") in ATTEMPT_EVENTS|{"fallback_started","repair_started"} for x in later)
            if r.get("error_terminal") is False and not later_path: lifecycle.append(f"request {lrq}: nonterminal failure has no later path")
            if r.get("error_terminal") is True and any(x.get("event_type")=="model_attempt_started" for x in later): lifecycle.append(f"request {lrq}: attempt after terminal failure")
        if completed:
            last_success=max(p for p,_ in completed)
            if any(p>last_success and r.get("event_type")=="model_attempt_started" for p,r in ordered): lifecycle.append(f"request {lrq}: attempt after success")
    c=lambda k: sum(1 for r in rows if r.get("event_type")==k)
    result={"rows_inspected":len(rows),"logical_requests":len(requests),"logical_requests_successful":successful,
      "logical_requests_first_attempt_success":first,"logical_requests_recovered":recovered,
      "logical_requests_terminal_failed":terminal,"logical_requests_avoided":avoided,
      "model_attempts":c("model_attempt_started"),"model_attempts_started":c("model_attempt_started"),
      "model_attempts_completed":c("model_attempt_completed"),"model_attempts_failed":c("model_attempt_failed"),
      "failed_attempts_terminal":sum(r.get("event_type")=="model_attempt_failed" and r.get("error_terminal") is True for r in rows),
      "failed_attempts_nonterminal":sum(r.get("event_type")=="model_attempt_failed" and r.get("error_terminal") is False for r in rows),
      "fallbacks_started":c("fallback_started"),"repairs_started":c("repair_started"),
      "attempts_by_model_name":dict(sorted(by_model.items())),"attempts_by_model_role":dict(sorted(by_role.items())),
      "warning_occurrences":sum(warnings.values()),"warning_articles_distinct":len(warning_articles),"warning_occurrences_by_code":dict(sorted(warnings.items())),
      "blocker_occurrences":sum(blockers.values()),"blocker_articles_distinct":len(blocker_articles),"blocker_occurrences_by_code":dict(sorted(blockers.items())),
      "publication_attempts":c("publication_attempted"),"publication_successes":c("publication_completed"),"publication_failures":c("publication_failed"),"publication_already_present":c("publication_already_present"),
      "report_published":c("report_published"),"report_non_error_skips":sum(r.get("agent")=="Simone" and r.get("status") in {"skipped","avoided"} for r in rows),"report_failures":sum(r.get("agent")=="Simone" and r.get("event_type")=="stage_failed" for r in rows),
      "invariant_errors":invariant,"identity_errors":identity,"lifecycle_errors":lifecycle}
    return result


def load(path: Path) -> tuple[list[dict[str,Any]],list[str]]:
    rows=[]; errors=[]
    if not path.exists(): return rows,[f"ledger not found: {path}"]
    for no,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        try:
            row=json.loads(line)
            if isinstance(row,dict): rows.append(row)
            else: errors.append(f"row {no}: not an object")
        except Exception: errors.append(f"row {no}: invalid JSON")
    return rows,errors


def main(argv=None)->int:
    p=argparse.ArgumentParser(); p.add_argument("path",nargs="?",type=Path,default=DEFAULT); ns=p.parse_args(argv)
    rows,parse_errors=load(ns.path); result=analyze(rows); result["invariant_errors"]=parse_errors+result["invariant_errors"]
    print(json.dumps(result,indent=2,sort_keys=True))
    return 1 if any(result[k] for k in ("invariant_errors","identity_errors","lifecycle_errors")) else 0
if __name__=="__main__": raise SystemExit(main())
