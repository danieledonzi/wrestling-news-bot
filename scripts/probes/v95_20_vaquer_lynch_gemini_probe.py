"""Non-mutating live probe for the production recent-history arbitration path."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from google import genai
from agents import bob, source_body
from agents import menzo_policy_v93_15 as menzo

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=ROOT/"tests/fixtures/v95_20_full_body/vaquer_lynch_raw.json"

def hydrate_runtime(url: str, local_html: str | None) -> dict:
    record={"source_url":url}
    if local_html:
        raw=Path(local_html).read_text(encoding="utf-8")
        _meta,_raw,elements,_removed,diagnostics=bob.extract_elements(url,raw)
        contract=source_body.contract_from_elements(url,elements,diagnostics)
        status="local_html_production_extractor"
    else:
        ok,status=source_body.hydrate(record); contract=record.get("canonical_source_body") if ok else None
    if not source_body.valid_contract(contract):
        raise SystemExit(f"canonical hydration failed for {url}: {status}")
    record["canonical_source_body"]=contract
    return record

def fixture_records() -> tuple[dict,dict]:
    case=json.loads(FIXTURE.read_text(encoding="utf-8"))
    def fixture(record: dict,text: str) -> dict:
        diagnostics={"stage":"extraction_finished","extraction_finished":True,"body_complete":True,"body_complete_reason":"copyright_safe_fixture","clean_element_count":1,"root_text_chars":len(text),"extracted_text_chars":len(text),"root_coverage_ratio":1.0,"structured_article_body_chars":0,"structured_coverage_ratio":None,"truncation_access_markers":[]}
        contract=source_body.contract_from_elements(str(record["source_url"]),[{"type":"text","text":text}],diagnostics)
        return {**record,"canonical_source_body":contract}
    return fixture(case["published"],case["published"]["cleaned_full_text"]),fixture(case["candidate"],case["candidate"]["body_text"])

def arguments() -> argparse.Namespace:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published-url"); parser.add_argument("--candidate-url")
    parser.add_argument("--published-file",help="Optional untracked local HTML for published URL")
    parser.add_argument("--candidate-file",help="Optional untracked local HTML for candidate URL")
    parser.add_argument("--fixture",action="store_true",help="Use the copyright-safe repository smoke fixture")
    args=parser.parse_args()
    if not args.fixture and not (args.published_url and args.candidate_url):
        parser.error("provide both runtime URLs (and optionally local HTML files), or --fixture")
    return args

def main() -> int:
    args=arguments(); key=os.getenv("GEMINI_API_KEY","").strip()
    if not key: raise SystemExit("GEMINI_API_KEY is required; no state was modified")
    published,candidate=fixture_records() if args.fixture else (hydrate_runtime(args.published_url,args.published_file),hydrate_runtime(args.candidate_url,args.candidate_file))
    current=menzo.compact_candidate_record(candidate,"c0"); previous=menzo.compact_published_record(published,"p0")
    print(json.dumps({"canonical_bodies":[{"pair_id":"p0","url":previous["url"],"chars":len(previous["full_body"]),"provenance":published["canonical_source_body"]["provenance"],"coverage":published["canonical_source_body"]["coverage"]},{"pair_id":"c0","url":current["url"],"chars":len(current["full_body"]),"provenance":candidate["canonical_source_body"]["provenance"],"coverage":candidate["canonical_source_body"]["coverage"]}],"prompt_pair_ids":{"current_id":"c0","published_id":"p0"}},ensure_ascii=False,indent=2))
    prompt=menzo.build_recent_history_batch_prompt([current],[previous]); model=menzo.DUPLICATE_BATCH_MODEL
    response=genai.Client(api_key=key).models.generate_content(model=model,contents=prompt); raw=getattr(response,"text","") or ""
    print(json.dumps({"model":model,"raw_response":raw},ensure_ascii=False,indent=2))
    parsed=menzo._parse_gemini_json_text(raw); comparisons,error=menzo.validate_recent_history_batch(parsed,{"c0":current},{"p0":previous})
    decision=comparisons[0]["decision"] if comparisons else "INVALID"
    print(json.dumps({"validated_decision":decision,"validation_error":error},indent=2))
    if error or decision!="DUPLICATE": raise SystemExit("expected real-world decision DUPLICATE")
    return 0

if __name__=="__main__": raise SystemExit(main())
