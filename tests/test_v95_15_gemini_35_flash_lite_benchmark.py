import csv, importlib.util, json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]; TOOL_PATH=ROOT/"tools/gemini_35_flash_lite_benchmark.py"; FIX=ROOT/"tests/fixtures/v95_15_model_benchmark"
def load_tool():
    spec=importlib.util.spec_from_file_location("v9515",TOOL_PATH); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
@pytest.fixture
def tool(): return load_tool()
@pytest.fixture
def manifest(tmp_path,tool):
    out=tmp_path/"discovery"; tool.discover(FIX,out); p=out/"proposed_manifest.json"; d=json.loads(p.read_text()); d["frozen"]=True; p.write_text(json.dumps(d)); return p

def case(name):
    p=json.loads((FIX/name).read_text()); return {"case_id":"x","task":p["task"],"payload":p,"expected":p.get("expected"),"critical":p.get("critical",False)}

def valid_output(prompt):
    if '"duplicate_groups"' in prompt:
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same central fact"}]}
    if '"matches"' in prompt:
        return {"matches":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","reason":"same fact"},{"current_id":"c1","published_id":"p0","decision":"MATERIAL_UPDATE","new_fact":"officially changed match date to Sunday in Boston","reason":"date and location changed"}]}
    if "BLOCCHI JSON:" in prompt:
        import re
        items=json.loads(re.search(r"BLOCCHI JSON:\s*(\[.*\])\s*$",prompt,re.S).group(1)); return {"items":[{"i":x["i"],"text":"Traduzione %s"%x["i"]} for x in items]}
    ids=[x["id"] for x in json.loads(prompt.split("BLOCCHI DA TRADURRE:\n",1)[1])]
    return {"title_it":"Titolo","excerpt_it":"Sommario","translations":{x:"Traduzione" for x in ids}}
class Response:
    model_version="versioned-alias"; usage_metadata={"prompt_token_count":100,"candidates_token_count":20,"thoughts_token_count":5,"total_token_count":125}
    def __init__(self,text): self.text=text
class Models:
    def __init__(self,fail=False): self.calls=[]; self.fail=fail
    def generate_content(self,**kwargs):
        self.calls.append(kwargs)
        if self.fail: raise RuntimeError("offline fake failure")
        return Response(json.dumps(valid_output(kwargs["contents"])))
class Client:
    def __init__(self,fail=False): self.models=Models(fail)

def test_import_no_effects(tool,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path); before=list(tmp_path.iterdir()); load_tool(); assert list(tmp_path.iterdir())==before
@pytest.mark.parametrize("p",["state/x","artifacts/newsroom/x","reports/x","published/x","published_html_review/x"])
def test_forbidden_output(tool,p):
    with pytest.raises(ValueError): tool.safe_output(ROOT/p)
def test_discovery_provenance_repeatable_and_excludes_self(tool,tmp_path):
    out=tmp_path/"inside"; first=tool.discover(FIX,out); second=tool.discover(FIX,out)
    assert first==second
    assert all(x.get("source_provenance") and x.get("source_material_hash") and x.get("selection_reason") for x in first["cases"])
    assert not any(str(out) in x["source_artifact"] for x in second["cases"])
def test_plain_markdown_and_final_html_rejected(tool,tmp_path):
    (tmp_path/"diagnostic.md").write_text("the "*200)
    (tmp_path/"final.json").write_text(json.dumps({"task":"bob","final_html":"<p>"+"testo italiano della notizia "*30+"</p>"}))
    out=tmp_path/"out"; result=tool.discover(tmp_path,out); assert result["cases"]==[]
def test_malformed_menzo_rejected(tool):
    assert not tool.has_source_material({"scope":"same_run","records":[None]},"menzo")
    assert not tool.has_source_material({"scope":"same_run","records":[]},"menzo")
def test_authoritative_same_run_prompt(tool):
    prompt=tool.prepare_case(case("menzo.json"))[0]["prompt"]
    assert "duplicate_groups" in prompt and "keep_id" in prompt
    assert '"decision":"DUPLICATE|DISTINCT"' not in prompt
def test_authoritative_recent_prompt(tool):
    prompt=tool.prepare_case(case("menzo_recent.json"))[0]["prompt"]
    assert all(x in prompt for x in ("matches","current_id","published_id"))
    assert "DISTINCT_STORY" not in prompt
def test_old_simple_helpers_not_referenced():
    source=TOOL_PATH.read_text(); assert "build_simple_" not in source and "parse_same_run_duplicate_result" not in source

def test_valid_survivor(tool):
    p=tool.prepare_case(case("menzo.json"))[0]; parsed,diag=tool.validate_output("menzo",json.dumps(valid_output(p["prompt"])),p["context"]); assert diag["structured_output_valid"] and parsed[0]["keep_id"]=="c0"
def test_survivor_outside_payload(tool):
    p=tool.prepare_case(case("menzo.json"))[0]; _,d=tool.validate_output("menzo",json.dumps({"duplicate_groups":[{"keep_id":"c9","discard_ids":["c1"]}]}),p["context"]); assert d["survivor_outside_payload"]==1 and not d["structured_output_valid"]
def test_overlapping_groups(tool):
    p=tool.prepare_case(case("menzo.json"))[0]; raw={"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"]},{"keep_id":"c1","discard_ids":["c2"]}]}; _,d=tool.validate_output("menzo",json.dumps(raw),p["context"]); assert d["overlapping_groups"]==1 and not d["structured_output_valid"]
def test_unique_story_loss(tool):
    p=tool.prepare_case(case("menzo.json"))[0]; raw={"duplicate_groups":[{"keep_id":"c0","discard_ids":["c2"]}]}; _,d=tool.validate_output("menzo",json.dumps(raw),p["context"]); assert d["unique_story_lost"]==1
def test_generic_material_update_rejected(tool):
    p=tool.prepare_case(case("menzo_recent.json"))[0]; raw={"matches":[{"current_id":"c1","published_id":"p0","decision":"MATERIAL_UPDATE","new_fact":"new details","reason":"update"}]}; _,d=tool.validate_output("menzo",json.dumps(raw),p["context"]); assert d["generic_material_updates"]==1 and not d["structured_output_valid"]

def test_run_metrics_prompt_audit_and_pricing_key(tool,manifest,tmp_path):
    client=Client(); rows=tool.run_benchmark(manifest,tmp_path/"run",tool.DEFAULT_MODELS,client=client)
    assert all(all(k in x for k in ("comparison_id","prompt_id","batch_index","batch_total")) for x in rows)
    assert all((tmp_path/"run"/x["prompt_path"]).exists() for x in rows)
    assert all(x.get("pricing_model_key")==x["model_requested"] for x in rows)
    assert all(set(c)=={"model","contents"} for c in client.models.calls)
def test_missing_key_no_output(tool,manifest,tmp_path,monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY",raising=False)
    with pytest.raises(RuntimeError): tool.run_benchmark(manifest,tmp_path/"run",tool.DEFAULT_MODELS)
    assert not (tmp_path/"run").exists()
def test_failed_calls_remain(tool,manifest,tmp_path):
    rows=tool.run_benchmark(manifest,tmp_path/"run",tool.DEFAULT_MODELS,client=Client(True)); assert rows and all(x["status"]=="failed" for x in rows)

def make_multibatch_manifest(tmp_path,tool):
    payload={"task":"simone","critical":True,"source_title":"WWE PLE","deterministic_title":"Report WWE PLE","strata":["WWE","PLE_PPV","multi_batch"],"blocks":[{"type":"paragraph","text":("The complete wrestling show segment preserved every match result, quotation, name and number for this authoritative source report block number %d. "%i)*2} for i in range(25)]}
    p=tmp_path/"m.json"; p.write_text(json.dumps({"schema_version":"v95.15","frozen":True,"cases":[{"case_id":"simone-001","task":"simone","critical":True,"payload":payload}]})); return p
def test_simone_multibatch_recomposes_only_a_b(tool,tmp_path,monkeypatch):
    import modules.report_workshop_v92 as report
    monkeypatch.setattr(report,"REPORT_TRANSLATION_BATCH_SIZE",8)
    run=tmp_path/"run"; tool.run_benchmark(make_multibatch_manifest(tmp_path,tool),run,tool.DEFAULT_MODELS,client=Client()); tool.blind_run(run,9515)
    files={p.name for p in (run/"blind_review/cases/simone-001").iterdir()}; assert files=={"source.json","output_A.json","output_B.json"}
    assert json.loads((run/"blind_review/cases/simone-001/output_A.json").read_text())["complete_report_valid"]
def test_incomplete_simone_invalid(tool):
    metrics=[{"comparison_id":"s","model_requested":"m","repetition":1,"batch_index":1,"batch_total":2,"status":"ok","structured_output_valid":True,"parsed_output_path":"x"}]
    assert not tool.recompose(metrics,"s","m")["complete_report_valid"]

def setup_blind(tool,tmp_path,failed=False):
    run=tmp_path/"run"; run.mkdir(); source={"task":"bob","source_text":"The authoritative source article contains enough English words to provide common material for blind fidelity review and includes names and numbers from the wrestling story."}
    metrics=[]
    for model,suffix in zip(tool.DEFAULT_MODELS,("a","b")):
        path="parsed/%s.json"%suffix; (run/"parsed").mkdir(exist_ok=True); tool.write_json(run/path,{"parsed":{"title_it":suffix},"diagnostics":{}})
        metrics.append({"case_id":"bob-001","comparison_id":"bob-001","task":"bob","model_requested":model,"repetition":1,"batch_index":1,"batch_total":1,"status":"failed" if failed and suffix=="b" else "ok","error":"boom" if failed and suffix=="b" else None,"structured_output_valid":suffix=="a" or not failed,"parsed_output_path":path,"source":source,"critical":True,"diagnostics":{"protected_term_violations":[]},"repair_required":False,"latency_ms":1,"total_tokens":10,"estimated_cost":"0.01","prompt_id":"p"})
    tool.write_json(run/"metrics.json",metrics); tool.write_json(run/"run_manifest.json",{"models":list(tool.DEFAULT_MODELS)}); tool.blind_run(run,9515); return run
def complete_review(tool,run,preference="A",candidate_bad_term=False):
    template=run/"blind_review/review_template.csv"; rows=list(csv.DictReader(template.open())); row=rows[0]; row["preferred_output"]=preference
    for label in ("A","B"):
        for d in tool.BOB_DIMS: row[label+"_"+d]="4" if label=="A" else "2"
        for d in tool.SEVERITY_DIMS: row[label+"_"+d]="0"
    out=run/"blind_review/review_completed.csv"
    with out.open("w",newline="") as f: w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerow(row)
    return out

def test_blind_contains_source_and_hides_identity(tool,tmp_path):
    run=setup_blind(tool,tmp_path); case_dir=run/"blind_review/cases/bob-001"; assert "authoritative source" in (case_dir/"source.json").read_text(); visible="".join(p.read_text() for p in case_dir.iterdir()); assert "gemini-" not in visible and "estimated_cost" not in visible
def test_blind_outputs_remove_correctness_leakage_but_metrics_keep_it(tool,manifest,tmp_path):
    run=tmp_path/"run"; tool.run_benchmark(manifest,run,tool.DEFAULT_MODELS,client=Client()); tool.blind_run(run,9515)
    forbidden=("diagnostics","expected_passed","unique_story_lost","generic_material_updates","validation_error","structured_output_valid")
    visible="".join(p.read_text() for p in (run/"blind_review/cases").rglob("output_*.json"))
    assert not any(term in visible for term in forbidden)
    internal=(run/"metrics.json").read_text()
    assert all(term in internal for term in ("diagnostics","expected_passed","structured_output_valid"))
def test_blank_preference_rejected(tool,tmp_path):
    run=setup_blind(tool,tmp_path); path=complete_review(tool,run,"")
    with pytest.raises(ValueError,match="preference"): tool.report_run(run,path)
def test_duplicate_preference_rejected(tool,tmp_path):
    run=setup_blind(tool,tmp_path); path=complete_review(tool,run); text=path.read_text(); path.write_text(text+text.splitlines()[-1]+"\n")
    with pytest.raises(ValueError,match="duplicated"): tool.report_run(run,path)
def test_one_preference_once_rates_bounded_and_scores_attributed(tool,tmp_path):
    run=setup_blind(tool,tmp_path); review=complete_review(tool,run,"A"); report=tool.report_run(run,review); s=report["agents"]["bob"]
    assert s["wins"]+s["ties"]+s["losses"]==1 and all(0<=s[x]<=1 for x in ("win_rate","tie_rate","loss_rate","better_or_equal_rate"))
    mapping=json.loads((run/"blind_review/answer_key.json").read_text())["comparisons"]["bob-001"]["labels"]
    assert s["baseline" if mapping["A"]==tool.DEFAULT_MODELS[0] else "candidate"]["mean_scores"]["fidelity_1_5"]==4
def test_critical_term_regression_gate(tool):
    s={"cases":1,"better_or_equal_rate":1,"loss_rate":0,"critical_protected_term_regressions":1,"baseline":{"severe_hallucinations":0,"severe_omissions":0,"structured_output_rate":1,"repair_rate":0},"candidate":{"severe_hallucinations":0,"severe_omissions":0,"structured_output_rate":1,"repair_rate":0}}
    assert tool.gate_translation(s)=="REJECT"
def test_menzo_fatal_gate(tool):
    base={"structured_output_rate":1}; cand={"structured_output_rate":1,"critical_expected_rate":1,"unique_stories_lost":1,"missing_survivors":0,"survivor_outside_payload":0,"overlapping_groups":0,"groups_discarding_all":0,"generic_material_updates":0}
    assert tool.gate_menzo({"cases":1,"baseline":base,"candidate":cand})=="REJECT"
def test_repetition_stability(tool,tmp_path):
    run=tmp_path; tool.write_json(run/"a.json",{"parsed":{"x":1}}); rows=[{"comparison_id":"x","prompt_id":"p","model_requested":"m","status":"ok","repetition":1,"parsed_output_path":"a.json","_run_root":str(run)},{"comparison_id":"x","prompt_id":"p","model_requested":"m","status":"ok","repetition":2,"parsed_output_path":"a.json","_run_root":str(run)}]; assert tool.stability(rows)==1
def test_failed_call_visible_in_blind_and_report(tool,tmp_path):
    run=setup_blind(tool,tmp_path,True); visible=json.loads((run/"blind_review/cases/bob-001/output_A.json").read_text()); other=json.loads((run/"blind_review/cases/bob-001/output_B.json").read_text()); assert "failed" in {visible.get("status"),other.get("status")}
    report=tool.report_run(run,complete_review(tool,run)); assert report["agents"]["bob"]["candidate"]["failed_calls"]+report["agents"]["bob"]["baseline"]["failed_calls"]==1
def complete_menzo_reviews(tool,run,candidate_duplicate=1,candidate_unique_loss=0):
    answer=json.loads((run/"blind_review/answer_key.json").read_text()); rows=list(csv.DictReader((run/"blind_review/review_template.csv").open()))
    for row in rows:
        row["preferred_output"]="TIE"; mapping=answer["comparisons"][row["comparison_id"]]["labels"]
        for label,model in mapping.items():
            for dim in tool.MENZO_DIMS:
                key=label+"_"+dim
                if row[key]=="NA": continue
                row[key]="1" if dim!="unique_story_lost" else "0"
            if model==tool.DEFAULT_MODELS[1]:
                row[label+"_duplicate_decision_correct"]=str(candidate_duplicate)
                row[label+"_unique_story_lost"]=str(candidate_unique_loss)
    path=run/"blind_review/review_completed.csv"
    with path.open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    return path
def test_menzo_human_error_blocks_promotion_when_automatic_metrics_pass(tool,manifest,tmp_path):
    data=json.loads(manifest.read_text()); data["cases"]=[x for x in data["cases"] if x["task"]=="menzo"]; manifest.write_text(json.dumps(data))
    run=tmp_path/"run"; tool.run_benchmark(manifest,run,tool.DEFAULT_MODELS,client=Client()); tool.blind_run(run,9515)
    report=tool.report_run(run,complete_menzo_reviews(tool,run,candidate_duplicate=0)); candidate=report["agents"]["menzo"]["candidate"]
    assert candidate["critical_expected_rate"]==1 and candidate["human_critical_duplicate_decision_accuracy"]<1
    assert report["agents"]["menzo"]["decision"]!="PROMOTE"
def test_menzo_human_unique_story_loss_rejects(tool,manifest,tmp_path):
    data=json.loads(manifest.read_text()); data["cases"]=[x for x in data["cases"] if x["task"]=="menzo"]; manifest.write_text(json.dumps(data))
    run=tmp_path/"run"; tool.run_benchmark(manifest,run,tool.DEFAULT_MODELS,client=Client()); tool.blind_run(run,9515)
    report=tool.report_run(run,complete_menzo_reviews(tool,run,candidate_unique_loss=1))
    assert report["agents"]["menzo"]["candidate"]["human_unique_story_losses"]>0 and report["agents"]["menzo"]["decision"]=="REJECT"
def test_expected_material_fact_tolerates_wording_but_rejects_different_fact(tool):
    prepared=tool.prepare_case(case("menzo_recent.json"))[0]
    good=valid_output(prepared["prompt"]); _,good_diag=tool.validate_output("menzo",json.dumps(good),prepared["context"])
    assert good_diag["structured_output_valid"] and good_diag["expected_passed"]
    different={"matches":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","reason":"same"},{"current_id":"c1","published_id":"p0","decision":"MATERIAL_UPDATE","new_fact":"officially changed match location to Boston after Chicago cancellation","reason":"location"}]}
    _,different_diag=tool.validate_output("menzo",json.dumps(different),prepared["context"])
    assert different_diag["structured_output_valid"] and not different_diag["expected_passed"]
    automatic={"cases":1,"baseline":{"structured_output_rate":1},"candidate":{"structured_output_rate":1,"critical_expected_rate":0,"human_unique_story_losses":0,"unique_stories_lost":0,"missing_survivors":0,"survivor_outside_payload":0,"overlapping_groups":0,"groups_discarding_all":0,"generic_material_updates":0}}
    assert tool.gate_menzo(automatic)=="REJECT"
def test_report_uses_models_from_run_manifest(tool,tmp_path):
    run=setup_blind(tool,tmp_path); custom=["baseline-custom","candidate-custom"]
    metrics=json.loads((run/"metrics.json").read_text())
    for row,model in zip(metrics,custom): row["model_requested"]=model
    tool.write_json(run/"metrics.json",metrics); tool.write_json(run/"run_manifest.json",{"models":custom}); tool.blind_run(run,9515)
    report=tool.report_run(run,complete_review(tool,run,"TIE"))
    assert report["baseline_model"]==custom[0] and report["candidate_model"]==custom[1]
def test_python39_compatible_syntax(): assert "match " not in "\n".join(x.lstrip() for x in TOOL_PATH.read_text().splitlines() if x.lstrip().startswith("match "))
