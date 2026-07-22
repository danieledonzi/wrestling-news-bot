#!/usr/bin/env python3
"""Measurement-only Gemini 3.1/3.5 Flash-Lite benchmark.

Production modules are imported lazily only for pure prompt construction/validation.
No production runner, persistence helper, publisher, or WordPress API is invoked.
"""
from __future__ import annotations

import argparse, copy, csv, hashlib, json, math, os, random, re, statistics, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PRICING_FILE = Path(__file__).with_name("gemini_35_flash_lite_pricing.json")
SCHEMA = "v95.15"
DEFAULT_MODELS = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite")
FORBIDDEN = (("state",), ("artifacts", "newsroom"), ("reports",), ("published",), ("published_html_review",))
SELF_FILES = {"candidate_inventory.json", "proposed_manifest.json", "frozen_manifest.json", "metrics.json", "run_manifest.json", "benchmark_report.json", "answer_key.json", "review_template.csv"}
BOB_DIMS = ("fidelity_1_5", "completeness_1_5", "natural_italian_1_5", "title_quality_1_5", "wrestling_terminology_1_5", "quote_and_name_preservation_1_5", "structure_preservation_1_5")
SEVERITY_DIMS = ("hallucination_severity_0_3", "omission_severity_0_3")
MENZO_DIMS = ("duplicate_decision_correct", "survivor_correct", "material_update_correct", "unique_story_lost")
ALL_REVIEW_DIMS = BOB_DIMS + SEVERITY_DIMS + MENZO_DIMS
BAD_TERMS = ("partita", "gara", "gioco", "rilascio", "pensione", "pulito")
BOB_STRATA = ("hard_news", "contract_or_roster", "quote_or_interview", "business", "post_show", "soft_but_published")
SIMONE_STRATA = ("WWE", "NXT", "AEW", "TNA", "PLE_PPV", "multi_batch")
MENZO_STRATA = ("same_run_duplicate", "same_run_distinct", "recent_history_duplicate", "material_update", "already_published", "survivor_required", "lyra_equivalent")


def utc_now() -> str: return datetime.now(timezone.utc).isoformat()
def sha(text: str) -> str: return hashlib.sha256(text.encode("utf-8")).hexdigest()
def canonical(value: Any) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")

def under(path: Path, parent: Path) -> bool:
    try: path.resolve().relative_to(parent.resolve()); return True
    except ValueError: return False

def safe_output(path: Path) -> Path:
    result=path.expanduser().resolve()
    if under(result, ROOT):
        parts=result.relative_to(ROOT).parts
        for denied in FORBIDDEN:
            if tuple(parts[:len(denied)]) == denied: raise ValueError("forbidden production output root: %s" % result)
    return result

def substantive(value: Any) -> bool:
    if not isinstance(value, str): return False
    words=re.findall(r"[A-Za-zÀ-ÿ0-9']+", re.sub(r"https?://\S+|<[^>]+>", " ", value))
    return len(words)>=12 and len(" ".join(words))>=80

def language_hint(text: str) -> str:
    low=" "+re.sub(r"[^a-zà-ÿ]+"," ",text.lower())+" "
    it=sum(low.count(" "+x+" ") for x in ("che","della","sono","contro","dopo","titolo"))
    en=sum(low.count(" "+x+" ") for x in ("the","that","with","against","after","title"))
    return "it" if it>en else "en" if en else "unknown"

def source_field(payload: Dict[str,Any], task: str) -> Tuple[Optional[str],Optional[str]]:
    if task=="simone":
        blocks=payload.get("blocks")
        if isinstance(blocks,list) and blocks and all(isinstance(x,dict) for x in blocks) and any(substantive(x.get("text")) for x in blocks): return "blocks", canonical(blocks)
        return None,None
    if task=="menzo":
        scope=str(payload.get("scope") or "same_run")
        groups=[payload.get("current_records"),payload.get("published_records")] if scope=="recent_history" else [payload.get("records")]
        records=[r for group in groups if isinstance(group,list) for r in group]
        if not records or any(not isinstance(r,dict) for r in records): return None,None
        if scope=="recent_history" and (not isinstance(payload.get("current_records"),list) or not isinstance(payload.get("published_records"),list) or not payload["current_records"] or not payload["published_records"]): return None,None
        if any(not any(substantive(r.get(k)) for k in ("summary","description","excerpt","body_excerpt","source_text")) for r in records): return None,None
        return "records", canonical(records)
    # Only explicit original/source fields. Generic body_html/final HTML is never authority.
    for key in ("raw_html","source_html","original_html","source_text","original_text","extracted_text"):
        value=payload.get(key)
        if substantive(value) and language_hint(value)!="it": return key,value
    return None,None

def classify(payload: Dict[str,Any]) -> Optional[str]:
    kind=str(payload.get("task") or payload.get("kind") or payload.get("type") or "").lower()
    if kind in {"menzo","duplicate","cluster"}: return "menzo"
    if kind in {"simone","report","recap"}: return "simone"
    if kind in {"bob","news","article"}: return "bob"
    if isinstance(payload.get("blocks"),list): return "simone"
    if isinstance(payload.get("records"),list) or isinstance(payload.get("current_records"),list): return "menzo"
    if any(k in payload for k in ("raw_html","source_html","original_html","source_text","original_text","extracted_text")): return "bob"
    return None

def has_source_material(payload: Any, task: str) -> bool:
    return isinstance(payload,dict) and source_field(payload,task)[0] is not None

def json_objects(value: Any) -> Iterator[Dict[str,Any]]:
    if isinstance(value,dict):
        yield value
        for child in value.values(): yield from json_objects(child)
    elif isinstance(value,list):
        for child in value: yield from json_objects(child)

def infer_tags(payload: Dict[str,Any], task: str) -> List[str]:
    blob=canonical(payload).lower(); explicit=payload.get("strata") if isinstance(payload.get("strata"),list) else []
    tags=[str(x) for x in explicit]
    if task=="bob":
        rules=(("contract_or_roster",("contract","roster","released")),("quote_or_interview",("interview","said","blockquote")),("business",("ratings","revenue","business")),("post_show",("results","recap","after raw")),("soft_but_published",("soft_but_published",)))
        for tag,needles in rules:
            if any(x in blob for x in needles): tags.append(tag)
        if not set(tags)&set(BOB_STRATA): tags.append("hard_news")
        for tag,needle in (("official_title","championship"),("match_stipulation"," match"),("release_lexicon","release"),("retirement_or_cleared","retire"),("long_quotes","said"),("proper_name_casing","wwe"),("structured_blocks","<h"),("embed_or_table","<table"),("known_translation_risk","cleared")):
            if needle in blob: tags.append(tag)
    elif task=="simone":
        for tag in ("WWE","NXT","AEW","TNA"):
            if tag.lower() in blob: tags.append(tag)
        if any(x in blob for x in ("ple","ppv","pay per view")): tags.append("PLE_PPV")
        # Mirrors production minimum batch size, while explicit fixture strata may force it.
        if len(payload.get("blocks") or [])>24: tags.append("multi_batch")
    else:
        scope=str(payload.get("scope") or "same_run")
        tags.append("recent_history_duplicate" if scope=="recent_history" else "same_run_duplicate")
    return sorted(set(tags))

def _provenance(payload: Dict[str,Any], path: Path, field: str, material: str) -> Dict[str,str]:
    declared=str(payload.get("source_material_provenance") or payload.get("provenance") or "")
    trusted=declared or ("explicit_%s" % field)
    return {"source_provenance":trusted,"source_material_field":field,"source_language":language_hint(material),"source_material_hash":sha(material),"selection_reason":"explicit substantive original/source material in %s"%field,"source_artifact":str(path.resolve())}

def stratified_select(items: List[Dict[str,Any]], task: str, limit: int) -> List[Dict[str,Any]]:
    strata=BOB_STRATA if task=="bob" else SIMONE_STRATA if task=="simone" else MENZO_STRATA
    ordered=sorted(items,key=lambda x:(x["source_material_hash"],x["source_artifact"]))
    selected=[]; used=set()
    for stratum in strata:
        for item in ordered:
            if stratum in item["tags"] and item["source_material_hash"] not in used:
                selected.append(item); used.add(item["source_material_hash"]); break
    # Fill only with source-backed cases carrying a recognized task stratum/risk tag.
    for item in ordered:
        if len(selected)>=limit: break
        if item["source_material_hash"] not in used and (set(item["tags"])&set(strata)):
            selected.append(item); used.add(item["source_material_hash"])
    return selected[:limit]

def discover(artifact_root: Path, output_root: Path) -> Dict[str,Any]:
    root=artifact_root.resolve(); out=safe_output(output_root); inventory=[]; seen=set()
    model_bench=(ROOT/"artifacts/model_benchmarks").resolve()
    for path in sorted(root.rglob("*.json")):
        if not path.is_file() or path.is_symlink() or under(path,out) or under(path,model_bench) or path.name in SELF_FILES or "blind_review" in path.parts: continue
        try: data=json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        for payload in json_objects(data):
            task=classify(payload)
            if not task: continue
            field,material=source_field(payload,task)
            if not field or not material: continue
            prov=_provenance(payload,path,field,material); key=(task,prov["source_material_hash"])
            if key in seen: continue
            seen.add(key); inventory.append(dict(prov,task=task,tags=infer_tags(payload,task),payload=payload))
    targets={"bob":30,"simone":6,"menzo":15}; cases=[]; coverage={}
    for task in ("bob","simone","menzo"):
        chosen=stratified_select([x for x in inventory if x["task"]==task],task,targets[task])
        strata=BOB_STRATA if task=="bob" else SIMONE_STRATA if task=="simone" else MENZO_STRATA
        covered=sorted(s for s in strata if any(s in x["tags"] for x in chosen))
        coverage[task]={"available":len(chosen),"target":targets[task],"missing":max(0,targets[task]-len(chosen)),"covered_strata":covered,"missing_strata":[s for s in strata if s not in covered]}
        for i,item in enumerate(chosen,1):
            cases.append({"case_id":"%s-%03d"%(task,i),"task":task,"source_artifact":item["source_artifact"],"tags":item["tags"],"critical":bool(item["payload"].get("critical")),"payload":item["payload"],"expected":item["payload"].get("expected"),**{k:item[k] for k in ("source_provenance","source_material_field","source_language","source_material_hash","selection_reason")}})
    manifest={"schema_version":SCHEMA,"created_at":"reproducible","frozen":False,"coverage":coverage,"cases":cases}
    out.mkdir(parents=True,exist_ok=True); write_json(out/"candidate_inventory.json",{"schema_version":SCHEMA,"candidates":inventory}); write_json(out/"proposed_manifest.json",manifest)
    return manifest

def validate_manifest(path: Path, require_frozen: bool=False) -> Dict[str,Any]:
    data=json.loads(path.read_text(encoding="utf-8")); errors=[]; ids=set()
    if data.get("schema_version")!=SCHEMA: errors.append("schema_version")
    if not isinstance(data.get("cases"),list) or not data["cases"]: errors.append("non-empty cases required")
    for case in data.get("cases") or []:
        cid=case.get("case_id")
        if not cid or cid in ids:
            errors.append("invalid/duplicate case_id")
        else:
            ids.add(cid)
        if case.get("task") not in {"bob","simone","menzo"} or not has_source_material(case.get("payload"),case.get("task")): errors.append("%s lacks authoritative source"%cid)
    if require_frozen and data.get("frozen") is not True: errors.append("manifest must be frozen")
    if errors: raise ValueError("invalid manifest: "+"; ".join(errors))
    return data

def capture_simone(source_title: str, blocks: List[Dict[str,Any]], title: str) -> List[Dict[str,Any]]:
    import modules.report_workshop_v92 as report
    original=report.generate_json; captured=[]
    def fake(prompt: str,*args: Any,**kwargs: Any) -> Tuple[Dict[str,Any],str]:
        found=re.search(r"BLOCCHI JSON:\s*(\[.*\])\s*$",prompt,re.S); items=json.loads(found.group(1)) if found else []
        captured.append({"prompt":prompt,"indexes":[int(x["i"]) for x in items]})
        return {"items":[{"i":int(x["i"]),"text":str(x.get("text") or "capture")} for x in items]},"capture-only"
    report.generate_json=fake
    try: report.translate_report_blocks(source_title,copy.deepcopy(blocks),title)
    finally: report.generate_json=original
    total=len(captured)
    for i,x in enumerate(captured,1): x.update(batch_index=i,batch_total=total)
    return captured

def prepare_case(case: Dict[str,Any]) -> List[Dict[str,Any]]:
    payload=copy.deepcopy(case["payload"]); task=case["task"]
    if task=="bob":
        import agents.bob as bob
        import agents.bob_policy_v93_15  # installs authoritative guardrails
        raw=payload.get("raw_html") or payload.get("source_html") or payload.get("original_html") or "<article><p>%s</p></article>"%(payload.get("source_text") or payload.get("original_text") or payload.get("extracted_text"))
        meta,_raw,elements,_removed,_diag=bob.extract_elements(payload.get("source_url") or "artifact://benchmark",raw)
        render=copy.deepcopy(elements); units=bob.build_translation_units(render)
        prompt=bob.build_translation_prompt(payload,meta,units)
        return [{"prompt":prompt,"batch_index":1,"batch_total":1,"context":{"source":payload,"elements":render,"units":units}}]
    if task=="simone":
        captures=capture_simone(str(payload.get("source_title") or "Report"),payload["blocks"],str(payload.get("deterministic_title") or "Report"))
        return [{"prompt":x["prompt"],"batch_index":x["batch_index"],"batch_total":x["batch_total"],"context":{"source":payload,"indexes":x["indexes"]}} for x in captures]
    import agents.menzo_policy_v93_15 as m
    scope=str(payload.get("scope") or "same_run")
    if scope=="recent_history":
        current=[m.compact_candidate_record(x,"c%d"%i) for i,x in enumerate(copy.deepcopy(payload["current_records"]))]
        published=[m.compact_published_record(x,"p%d"%i) for i,x in enumerate(copy.deepcopy(payload["published_records"]))]
        prompt=m.build_recent_history_batch_prompt(current,published); context={"scope":scope,"current":current,"published":published,"expected":case.get("expected")}
    else:
        records=[m.compact_candidate_record(x,"c%d"%i) for i,x in enumerate(copy.deepcopy(payload["records"]))]
        prompt=m.build_same_run_batch_prompt(records); context={"scope":"same_run","records":records,"expected":case.get("expected")}
    return [{"prompt":prompt,"batch_index":1,"batch_total":1,"context":context}]

def parse_raw(raw: str) -> Tuple[Dict[str,Any],bool]:
    cleaned=re.sub(r"^```(?:json)?|```$","",raw.strip(),flags=re.I).strip()
    try: data=json.loads(cleaned); return (data,isinstance(data,dict))
    except Exception: return ({},False)

def menzo_diagnostics(parsed: Dict[str,Any],context: Dict[str,Any]) -> Tuple[Any,Dict[str,Any]]:
    import agents.menzo_policy_v93_15 as m
    expected=context.get("expected") or {}; diag={"overlapping_groups":0,"groups_discarding_all":0,"survivor_outside_payload":0,"unique_story_lost":0,"generic_material_updates":0,"expected_passed":True}
    if context["scope"]=="same_run":
        ids={x["id"] for x in context["records"]}; groups,error=m.validate_same_run_batch(parsed,ids)
        raw_groups=parsed.get("duplicate_groups") if isinstance(parsed.get("duplicate_groups"),list) else []
        seen=set()
        for g in raw_groups:
            if not isinstance(g,dict): continue
            members={str(g.get("keep_id") or ""),*[str(x) for x in g.get("discard_ids") or []]}
            if seen&members: diag["overlapping_groups"]+=1
            seen|=members
            if str(g.get("keep_id") or "") not in ids: diag["survivor_outside_payload"]+=1
            if not g.get("keep_id") or g.get("keep_id") in (g.get("discard_ids") or []): diag["groups_discarding_all"]+=1
        uniques=set(expected.get("unique_ids") or []); diag["unique_story_lost"]=len(uniques&seen)
        wanted=expected.get("duplicate_groups") or []
        if groups is not None:
            normalized={(g["keep_id"],tuple(sorted(g["discard_ids"]))) for g in groups}; required={(g["keep_id"],tuple(sorted(g["discard_ids"]))) for g in wanted}; diag["expected_passed"]=required.issubset(normalized) and not diag["unique_story_lost"]
        else: diag["expected_passed"]=False
        diag.update(validation_error=error,missing_survivors=int(groups is None and bool(raw_groups)),structured_output_valid=groups is not None)
        return groups if groups is not None else parsed,diag
    cur={x["id"]:x for x in context["current"]}; pub={x["id"]:x for x in context["published"]}; matches,error=m.validate_recent_history_batch(parsed,cur,pub)
    raw=parsed.get("matches") if isinstance(parsed.get("matches"),list) else []
    for item in raw:
        if not isinstance(item,dict): continue
        if item.get("current_id") not in cur or item.get("published_id") not in pub: diag["survivor_outside_payload"]+=1
        if str(item.get("decision") or "").upper()=="MATERIAL_UPDATE" and not m.material_update_is_grounded(str(item.get("new_fact") or ""),cur.get(item.get("current_id"),{}),pub.get(item.get("published_id"),{})): diag["generic_material_updates"]+=1
    wanted=expected.get("matches") or []
    if matches is not None:
        actual={(x["current_id"],x["published_id"],x["decision"]):x for x in matches}
        expected_checks=[]
        for item in wanted:
            key=(item["current_id"],item["published_id"],item["decision"])
            check=key in actual
            expected_fact=str(item.get("new_fact_contains") or "").strip()
            if check and expected_fact:
                # Ignore harmless glue-word/word-order differences while requiring the
                # meaningful expected material fact to be represented.
                expected_tokens={x for x in re.findall(r"[a-z0-9]+",expected_fact.lower()) if len(x)>2 and x not in {"the","and","for","with","from","that","this"}}
                actual_tokens={x for x in re.findall(r"[a-z0-9]+",str(actual[key].get("new_fact") or "").lower()) if len(x)>2 and x not in {"the","and","for","with","from","that","this"}}
                check=bool(expected_tokens) and len(expected_tokens&actual_tokens)/len(expected_tokens)>=0.8
            expected_checks.append(check)
        diag["expected_passed"]=all(expected_checks)
        blocked={x["current_id"] for x in matches}; diag["unique_story_lost"]=len(set(expected.get("unmatched_current_ids") or [])&blocked)
    else: diag["expected_passed"]=False
    diag.update(validation_error=error,missing_survivors=0,structured_output_valid=matches is not None)
    return matches if matches is not None else parsed,diag

def validate_output(task: str,raw: str,context: Dict[str,Any]) -> Tuple[Any,Dict[str,Any]]:
    data,json_ok=parse_raw(raw); diag={"json_valid":json_ok,"protected_term_violations":[x for x in BAD_TERMS if re.search(r"\b%s\b"%x,raw,re.I)]}
    if task=="menzo":
        parsed,md=menzo_diagnostics(data,context); diag.update(md); return parsed,diag
    if task=="bob":
        import agents.bob as bob
        import agents.bob_policy_v93_15 as policy
        parsed=bob.parse_bob_json(raw); translations=parsed.get("translations") if isinstance(parsed.get("translations"),dict) else {}; expected={x["id"] for x in context["units"]}; actual=set(translations)
        diag.update(missing_ids=sorted(expected-actual),foreign_ids=sorted(actual-expected))
        try: rendered=bob.render_body(copy.deepcopy(context["elements"]),translations); post,changes=policy.postprocess_body(rendered); parsed.update(rendered_body=rendered,postprocessed_body=post,postprocess_changes=changes); render=True
        except Exception as exc: render=False; diag["render_error"]=str(exc)
        diag["structured_output_valid"]=json_ok and bool(parsed.get("title_it")) and bool(parsed.get("excerpt_it")) and not diag["missing_ids"] and not diag["foreign_ids"] and render
        return parsed,diag
    items=data.get("items") if isinstance(data.get("items"),list) else []; expected=context["indexes"]
    valid_items=[x for x in items if isinstance(x,dict) and type(x.get("i")) is int]
    indexes=[x["i"] for x in valid_items]
    empty_text_indexes=sorted({x["i"] for x in valid_items if x["i"] in expected and (not isinstance(x.get("text"),str) or not x["text"].strip())})
    missing_indexes=sorted((set(expected)-set(indexes))|set(empty_text_indexes))
    diag.update(missing_indexes=missing_indexes,empty_text_indexes=empty_text_indexes,invented_indexes=sorted(set(indexes)-set(expected)),duplicate_indexes=len(indexes)!=len(set(indexes)),malformed_items=len(items)-len(valid_items)); diag["structured_output_valid"]=json_ok and not diag["missing_indexes"] and not diag["invented_indexes"] and not diag["duplicate_indexes"] and not diag["malformed_items"]
    return data,diag

def run_benchmark(manifest_path: Path,output_root: Path,models: Sequence[str],repetitions: int=1,repeat_all: bool=False,client: Any=None) -> List[Dict[str,Any]]:
    manifest=validate_manifest(manifest_path,True); out=safe_output(output_root); key=os.getenv("GEMINI_API_KEY","").strip()
    if client is None:
        if not key: raise RuntimeError("GEMINI_API_KEY is required; no calls were made")
        from google import genai
        client=genai.Client(api_key=key)
    out.mkdir(parents=True,exist_ok=True); pricing=json.loads(PRICING_FILE.read_text())
    from agents.gemini_ledger import calculate_estimated_cost,extract_actual_model,extract_usage_metadata
    metrics=[]; order=0
    for ci,case in enumerate(manifest["cases"]):
        prepared=prepare_case(case); comparison_id=case["case_id"]
        for pi,p in enumerate(prepared,1):
            prompt_id="%s-p%02d"%(comparison_id,pi); prompt=p["prompt"]; prompt_hash=sha(prompt); prompt_path=out/"prompts"/(prompt_id+".txt"); prompt_path.parent.mkdir(parents=True,exist_ok=True); prompt_path.write_text(prompt,encoding="utf-8")
            reps=repetitions if repeat_all or case.get("critical") else 1
            for rep in range(1,reps+1):
                sequence=list(models) if (ci+pi+rep)%2==0 else list(reversed(models))
                for model in sequence:
                    order+=1; stem="%s-r%d-%s"%(prompt_id,rep,sha(model)[:8]); raw_path=out/"raw"/(stem+".txt"); parsed_path=out/"parsed"/(stem+".json")
                    row={"case_id":case["case_id"],"comparison_id":comparison_id,"task":case["task"],"model_requested":model,"actual_model":None,"repetition":rep,"call_order":order,"prompt_id":prompt_id,"batch_index":p["batch_index"],"batch_total":p["batch_total"],"prompt_hash":prompt_hash,"input_hash":sha(canonical(case["payload"])),"prompt_path":str(prompt_path.relative_to(out)),"latency_ms":None,"status":"failed","error":None,"raw_response_path":str(raw_path.relative_to(out)),"parsed_output_path":str(parsed_path.relative_to(out)),"structured_output_valid":False,"repair_required":False,"source":case["payload"],"expected":case.get("expected"),"critical":bool(case.get("critical"))}
                    try:
                        start=time.perf_counter(); response=client.models.generate_content(model=model,contents=prompt); row["latency_ms"]=round((time.perf_counter()-start)*1000,3); raw=str(getattr(response,"text","") or ""); raw_path.parent.mkdir(parents=True,exist_ok=True); raw_path.write_text(raw,encoding="utf-8")
                        parsed,diag=validate_output(case["task"],raw,p["context"]); write_json(parsed_path,{"parsed":parsed,"diagnostics":diag}); usage=extract_usage_metadata(response); row.update(usage); row.update(calculate_estimated_cost(usage,model,pricing)); row.update(actual_model=extract_actual_model(response),status="ok",structured_output_valid=bool(diag["structured_output_valid"]),diagnostics=diag)
                    except Exception as exc:
                        row["error"]="%s: %s"%(type(exc).__name__,exc); row.update({k:None for k in ("input_tokens","output_tokens","thinking_tokens","cached_input_tokens","total_tokens","estimated_input_cost","estimated_output_cost","estimated_thinking_cost","estimated_cost")})
                    metrics.append(row); write_json(out/"metrics.json",metrics)
    write_json(out/"run_manifest.json",{"schema_version":SCHEMA,"models":list(models),"source_manifest":manifest,"completed_at":utc_now()}); return metrics

def _sanitized_source(row: Dict[str,Any]) -> Dict[str,Any]:
    forbidden_prefixes=("historical_","wp_","translated_","previous_","final_translation_","final_translated_","final_answer_","model_","pricing_","price_","token_","expected_","estimated_cost")
    forbidden_exact={"model","models","actual_model","price","pricing","prices","token","tokens","expected","final_answer","final_html","final_title_it","final_content_it","final_text_it","final_translation","final_translated_answer"}
    def sanitize(value: Any) -> Any:
        if isinstance(value,dict):
            return {key:sanitize(child) for key,child in value.items() if str(key).lower() not in forbidden_exact and not str(key).lower().startswith(forbidden_prefixes)}
        if isinstance(value,list): return [sanitize(child) for child in value]
        return copy.deepcopy(value)
    return sanitize(row.get("source") or {})

def menzo_applicable_dimensions(source: Dict[str,Any]) -> List[str]:
    expected=source.get("expected") if isinstance(source.get("expected"),dict) else {}
    scope=str(source.get("scope") or "same_run")
    applicable=["duplicate_decision_correct","unique_story_lost"]
    if scope=="same_run" and expected.get("duplicate_groups"): applicable.append("survivor_correct")
    if scope=="recent_history" and any(str(x.get("decision") or "").upper()=="MATERIAL_UPDATE" for x in expected.get("matches",[]) if isinstance(x,dict)): applicable.append("material_update_correct")
    return applicable

def recompose(metrics: List[Dict[str,Any]],case_id: str,model: str) -> Dict[str,Any]:
    rows=sorted([x for x in metrics if x["comparison_id"]==case_id and x["model_requested"]==model and x["repetition"]==1],key=lambda x:x["batch_index"])
    total=max([int(x.get("batch_total") or 1) for x in rows] or [1]); valid=len(rows)==total and all(x.get("status")=="ok" and x.get("structured_output_valid") for x in rows) and {x["batch_index"] for x in rows}==set(range(1,total+1)); items=[]; errors=[]
    for row in rows:
        if row.get("status")!="ok" or not row.get("structured_output_valid"): errors.append({"batch_index":row.get("batch_index"),"status":row.get("status"),"error":row.get("error"),"valid":row.get("structured_output_valid")}); continue
        path=Path(row.get("_run_root") or ".")/row["parsed_output_path"]
        if not path.exists():
            valid=False; errors.append({"batch_index":row.get("batch_index"),"status":"missing","error":"parsed output missing","valid":False}); continue
        data=json.loads(path.read_text()); parsed=data.get("parsed") or {}; items.extend(parsed.get("items") or [])
    return {"items":sorted(items,key=lambda x:x.get("i",0)),"complete_report_valid":valid,"batch_total":total,"missing_or_invalid_batches":errors}

def blind_run(run_root: Path,seed: int) -> Path:
    metrics=json.loads((run_root/"metrics.json").read_text()); models=json.loads((run_root/"run_manifest.json").read_text())["models"]; blind=run_root/"blind_review"; rng=random.Random(seed); answer={"seed":seed,"comparisons":{}}; rows=[]
    for case_id in sorted({x["comparison_id"] for x in metrics}):
        cm=[x for x in metrics if x["comparison_id"]==case_id]; task=cm[0]["task"]; labels=["A","B"]; shuffled=list(models); rng.shuffle(shuffled); mapping=dict(zip(labels,shuffled)); answer["comparisons"][case_id]={"task":task,"labels":mapping}
        case_dir=blind/"cases"/case_id; case_dir.mkdir(parents=True,exist_ok=True); write_json(case_dir/"source.json",_sanitized_source(cm[0]))
        for label in labels:
            model=mapping[label]
            if task=="simone":
                enriched=[dict(x,_run_root=str(run_root)) for x in metrics]; output=recompose(enriched,case_id,model)
            else:
                candidates=[x for x in cm if x["model_requested"]==model and x["repetition"]==1]; row=candidates[0] if candidates else None
                if row and row.get("status")=="ok" and (run_root/row["parsed_output_path"]).exists():
                    artifact=json.loads((run_root/row["parsed_output_path"]).read_text()); parsed=artifact.get("parsed") or {}
                    output={"status":"ok","output":parsed} if row.get("structured_output_valid") else {"status":"invalid_output","output":parsed}
                else: output={"status":"failed","error":row.get("error") if row else "missing output"}
            write_json(case_dir/("output_%s.json"%label),output)
        record={"comparison_id":case_id,"case_id":cm[0]["case_id"],"task":task,"preferred_output":"","review_notes":""}
        if task=="menzo": applicable=set(menzo_applicable_dimensions(cm[0].get("source") or {}))
        elif task=="simone": applicable=set(BOB_DIMS+SEVERITY_DIMS)-{"title_quality_1_5"}
        else: applicable=set(BOB_DIMS+SEVERITY_DIMS)
        answer["comparisons"][case_id]["applicable_dimensions"]=sorted(applicable)
        for label in labels:
            for dim in ALL_REVIEW_DIMS: record["%s_%s"%(label,dim)]="" if dim in applicable else "NA"
        rows.append(record)
    fields=["comparison_id","case_id","task"]
    for label in ("A","B"):
        fields += ["%s_%s"%(label,x) for x in ALL_REVIEW_DIMS]
    fields += ["preferred_output","review_notes"]
    blind.mkdir(parents=True,exist_ok=True)
    with (blind/"review_template.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    write_json(run_root/"benchmark_internal/answer_key.json",answer); (blind/"review_instructions.md").write_text("One row per comparison. Fill only blank score cells for both A and B, then choose exactly A, B, or TIE. Never edit cells prefilled with NA: NA means that dimension does not apply to that comparison. Internal model mappings are not included in this reviewer package.\n",encoding="utf-8"); return blind

def _number(value: str,low: float,high: float) -> float:
    try: number=float(value)
    except Exception: raise ValueError("missing required numeric review score")
    if not math.isfinite(number): raise ValueError("review score must be finite")
    if number<low or number>high: raise ValueError("review score out of range")
    return number

def parse_reviews(path: Path,answer: Optional[Dict[str,Any]]=None) -> List[Dict[str,Any]]:
    with path.open(encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
    if not rows: raise ValueError("empty review CSV")
    seen=set(); comparisons=(answer or {}).get("comparisons",{})
    for row in rows:
        cid=row.get("comparison_id") or ""
        if not cid or cid in seen: raise ValueError("duplicated preference/comparison")
        seen.add(cid); pref=(row.get("preferred_output") or "").strip().upper()
        if pref not in {"A","B","TIE"}: raise ValueError("preference must be A, B, or TIE")
        if answer is not None:
            if cid not in comparisons:
                continue
            mapping=comparisons.get(cid,{}).get("labels",{});
            if set(mapping)!={"A","B"} or len(set(mapping.values()))!=2: raise ValueError("invalid answer-key mapping")
            comparison=comparisons.get(cid,{})
            explicit_applicability="applicable_dimensions" in comparison
            dims=ALL_REVIEW_DIMS if explicit_applicability else MENZO_DIMS if row.get("task")=="menzo" else BOB_DIMS+SEVERITY_DIMS
            applicable=set(comparison["applicable_dimensions"]) if explicit_applicability else set(dims)
            for label in ("A","B"):
                if label not in mapping: raise ValueError("label absent from answer key")
                for dim in dims:
                    value=(row.get("%s_%s"%(label,dim)) or "").strip().upper()
                    if dim not in applicable:
                        if value!="NA": raise ValueError("inapplicable review dimension must be NA")
                        continue
                    if value=="NA": raise ValueError("applicable review dimension cannot be NA")
                    _number(value,0,1 if dim in MENZO_DIMS else 3 if dim in SEVERITY_DIMS else 5)
    if answer is not None:
        expected_ids=set(comparisons)
        if seen!=expected_ids:
            missing=sorted(expected_ids-seen); unexpected=sorted(seen-expected_ids)
            raise ValueError("review coverage mismatch: missing=%s unexpected=%s"%(missing,unexpected))
    return rows

def p95(values: List[float]) -> Optional[float]:
    return sorted(values)[max(0,math.ceil(.95*len(values))-1)] if values else None

def stability(rows: List[Dict[str,Any]]) -> Optional[float]:
    grouped={}
    for x in rows:
        if x.get("status")!="ok": continue
        grouped.setdefault((x["comparison_id"],x["prompt_id"],x["model_requested"]),[]).append(x)
    scores=[]
    for vals in grouped.values():
        if len(vals)<2: continue
        signatures=[]
        for x in sorted(vals,key=lambda r:r["repetition"]):
            path=Path(x["_run_root"])/x["parsed_output_path"]
            signatures.append(sha(canonical(json.loads(path.read_text()).get("parsed"))) if path.exists() else "missing")
        scores.append(1.0 if len(set(signatures))==1 else 0.0)
    return statistics.mean(scores) if scores else None

def gate_translation(s: Dict[str,Any]) -> str:
    if not s.get("cases"): return "NEEDS_MORE_DATA"
    if s["candidate"]["severe_hallucinations"] or s["candidate"]["severe_omissions"] or s["critical_protected_term_regressions"]: return "REJECT"
    if s["candidate"]["structured_output_rate"]<s["baseline"]["structured_output_rate"] or s["candidate"]["repair_rate"]>s["baseline"]["repair_rate"]: return "KEEP_BASELINE"
    return "PROMOTE" if s["better_or_equal_rate"]>=.8 and s["loss_rate"]<=.1 else "KEEP_BASELINE"
def gate_menzo(s: Dict[str,Any]) -> str:
    if not s.get("cases"): return "NEEDS_MORE_DATA"
    fatal=("unique_stories_lost","missing_survivors","survivor_outside_payload","overlapping_groups","groups_discarding_all","generic_material_updates")
    if any(s["candidate"].get(x,0) for x in fatal) or s["candidate"].get("critical_expected_rate",0)<1: return "REJECT"
    if s["candidate"].get("human_unique_story_losses",0)>0: return "REJECT"
    for key in ("human_critical_duplicate_decision_accuracy","human_survivor_accuracy","human_material_update_accuracy"):
        value=s["candidate"].get(key)
        if value is not None and value<1: return "KEEP_BASELINE"
    if s["candidate"]["structured_output_rate"]<s["baseline"]["structured_output_rate"]: return "KEEP_BASELINE"
    return "PROMOTE"
def report_run(run_root: Path,reviews_path: Path) -> Dict[str,Any]:
    if not reviews_path.is_absolute() and not reviews_path.exists(): reviews_path=run_root/reviews_path
    run_manifest=json.loads((run_root/"run_manifest.json").read_text()); models=run_manifest.get("models")
    if not isinstance(models,list) or len(models)!=2 or len(set(models))!=2: raise ValueError("run manifest must declare two distinct models")
    baseline_model,candidate_model=models
    metrics=json.loads((run_root/"metrics.json").read_text()); metrics=[dict(x,_run_root=str(run_root)) for x in metrics]; answer=json.loads((run_root/"benchmark_internal/answer_key.json").read_text()); reviews=parse_reviews(reviews_path,answer); result={"schema_version":SCHEMA,"created_at":utc_now(),"baseline_model":baseline_model,"candidate_model":candidate_model,"agents":{}}
    for task in ("bob","simone","menzo"):
        rr=[x for x in reviews if x["task"]==task]; mm=[x for x in metrics if x["task"]==task]; cases=len(rr); wins=ties=losses=0; human={m:{d:[] for d in (MENZO_DIMS if task=="menzo" else BOB_DIMS+SEVERITY_DIMS)} for m in models}; critical_duplicate={m:[] for m in models}
        for review in rr:
            mapping=answer["comparisons"][review["comparison_id"]]["labels"]; pref=review["preferred_output"].upper()
            if pref=="TIE": ties+=1
            elif mapping[pref]==candidate_model: wins+=1
            else: losses+=1
            for label,model in mapping.items():
                for dim in human[model]:
                    value=review["%s_%s"%(label,dim)].strip().upper()
                    if value!="NA": human[model][dim].append(float(value))
                if task=="menzo" and review["%s_duplicate_decision_correct"%label].strip().upper()!="NA":
                    source=next((x.get("source") or {} for x in mm if x["comparison_id"]==review["comparison_id"]),{})
                    if bool(source.get("critical")) or any(x.get("critical") for x in mm if x["comparison_id"]==review["comparison_id"]): critical_duplicate[model].append(float(review["%s_duplicate_decision_correct"%label]))
        model_stats={}
        for model in models:
            rows=[x for x in mm if x["model_requested"]==model]; calls=len(rows); diags=[x.get("diagnostics") or {} for x in rows]; lat=[float(x["latency_ms"]) for x in rows if x.get("latency_ms") is not None]; toks=[float(x["total_tokens"]) for x in rows if x.get("total_tokens") is not None]; costs=[float(x["estimated_cost"]) for x in rows if x.get("estimated_cost") is not None]; scores={d:(statistics.mean(v) if v else None) for d,v in human[model].items()}; review_dims=[d for d in scores if d not in SEVERITY_DIMS and d not in MENZO_DIMS]
            composite_values=[scores[d] for d in review_dims if scores[d] is not None]
            stat={"calls":calls,"failed_calls":sum(x.get("status")!="ok" for x in rows),"structured_output_rate":sum(bool(x.get("structured_output_valid")) for x in rows)/max(1,calls),"repair_rate":sum(bool(x.get("repair_required")) for x in rows)/max(1,calls),"protected_term_violations":sum(len(d.get("protected_term_violations") or []) for d in diags),"critical_protected_term_violations":sum(len((x.get("diagnostics") or {}).get("protected_term_violations") or []) for x in rows if x.get("critical")),"missing_blocks_or_indexes":sum(len(d.get("missing_ids") or d.get("missing_indexes") or []) for d in diags),"mean_scores":scores,"composite_mean":statistics.mean(composite_values) if composite_values else None,"severe_hallucinations":sum(v>=3 for v in human[model].get("hallucination_severity_0_3",[])),"severe_omissions":sum(v>=3 for v in human[model].get("omission_severity_0_3",[])),"mean_tokens":statistics.mean(toks) if toks else None,"mean_latency_ms":statistics.mean(lat) if lat else None,"p95_latency_ms":p95(lat),"mean_cost":statistics.mean(costs) if costs else None,"total_cost":sum(costs),"repetition_stability":stability(rows)}
            if task=="simone":
                stat["complete_report_valid_rate"]=sum(recompose(metrics,x["comparison_id"],model)["complete_report_valid"] for x in rr)/max(1,cases)
            if task=="menzo":
                for key in ("unique_story_lost","missing_survivors","survivor_outside_payload","overlapping_groups","groups_discarding_all","generic_material_updates"): stat[key]=sum(int(d.get(key) or 0) for d in diags)
                critical=[d for x,d in zip(rows,diags) if x.get("critical")]; stat["critical_expected_rate"]=sum(bool(d.get("expected_passed")) for d in critical)/max(1,len(critical))
                stat["human_duplicate_decision_accuracy"]=statistics.mean(human[model]["duplicate_decision_correct"]) if human[model]["duplicate_decision_correct"] else None
                stat["human_critical_duplicate_decision_accuracy"]=statistics.mean(critical_duplicate[model]) if critical_duplicate[model] else None
                stat["human_survivor_accuracy"]=statistics.mean(human[model]["survivor_correct"]) if human[model]["survivor_correct"] else None
                stat["human_material_update_accuracy"]=statistics.mean(human[model]["material_update_correct"]) if human[model]["material_update_correct"] else None
                stat["human_unique_story_losses"]=sum(human[model]["unique_story_lost"])
            model_stats[model]=stat
        rate=lambda n:n/cases if cases else 0.0
        stats={"cases":cases,"wins":wins,"ties":ties,"losses":losses,"win_rate":rate(wins),"tie_rate":rate(ties),"loss_rate":rate(losses),"better_or_equal_rate":rate(wins+ties),"baseline":model_stats[baseline_model],"candidate":model_stats[candidate_model]}
        assert all(0<=stats[x]<=1 for x in ("win_rate","tie_rate","loss_rate","better_or_equal_rate"))
        stats["critical_protected_term_regressions"]=max(0,stats["candidate"]["critical_protected_term_violations"]-stats["baseline"]["critical_protected_term_violations"])
        stats["decision"]=gate_menzo(stats) if task=="menzo" else gate_translation(stats); result["agents"][task]=stats
    write_json(run_root/"benchmark_report.json",result); lines=["# Gemini benchmark",""]
    for task,s in result["agents"].items(): lines += ["## "+task.title(),"","**Decision: %s**"%s["decision"],"","Cases %d; W/T/L %d/%d/%d."%(s["cases"],s["wins"],s["ties"],s["losses"]),""]
    (run_root/"benchmark_report.md").write_text("\n".join(lines),encoding="utf-8"); return result

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Measurement-only Gemini Flash-Lite benchmark"); sub=p.add_subparsers(dest="command",required=True)
    q=sub.add_parser("discover"); q.add_argument("--artifact-root",type=Path,required=True); q.add_argument("--output-root",type=Path,required=True)
    q=sub.add_parser("validate"); q.add_argument("--manifest",type=Path,required=True); q.add_argument("--require-frozen",action="store_true")
    q=sub.add_parser("run"); q.add_argument("--manifest",type=Path,required=True); q.add_argument("--output-root",type=Path,required=True); q.add_argument("--models",nargs=2,default=DEFAULT_MODELS); q.add_argument("--repetitions",type=int,choices=(1,2),default=1); q.add_argument("--repeat-all",action="store_true")
    q=sub.add_parser("blind"); q.add_argument("--run-root",type=Path,required=True); q.add_argument("--seed",type=int,default=9515)
    q=sub.add_parser("report"); q.add_argument("--run-root",type=Path,required=True); q.add_argument("--reviews",type=Path,required=True); return p
def main(argv: Optional[Sequence[str]]=None) -> int:
    a=parser().parse_args(argv)
    try:
        if a.command=="discover": print(json.dumps(discover(a.artifact_root,a.output_root)["coverage"],indent=2))
        elif a.command=="validate": d=validate_manifest(a.manifest,a.require_frozen); print("valid %s cases=%d frozen=%s"%(SCHEMA,len(d["cases"]),d.get("frozen")))
        elif a.command=="run": run_benchmark(a.manifest,a.output_root,a.models,a.repetitions,a.repeat_all)
        elif a.command=="blind": print(blind_run(a.run_root,a.seed))
        else: report_run(a.run_root,a.reviews)
        return 0
    except Exception as exc: print("error: %s"%exc,file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
