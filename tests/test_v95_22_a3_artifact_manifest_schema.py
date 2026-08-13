"""Mutation-heavy regression suite for v95.22 A3 artifact manifest contract."""
import copy, json, subprocess, sys
from pathlib import Path
import pytest
from scripts.validate_artifact_manifest_schema import EXPECTED, validate
ROOT=Path(__file__).resolve().parents[1]
SCHEMA=ROOT/'config/artifact_manifest_schema_v1.json'; DOC=ROOT/'docs/runtime/OWTV_ARTIFACT_MANIFEST_SCHEMA_V1.md'; A2=ROOT/'config/event_schema_v1.json'
@pytest.fixture
def bundle(): return json.loads(SCHEMA.read_text()),DOC.read_text(),json.loads(A2.read_text())
def errors(bundle,markdown=False): return validate(bundle[0],bundle[1] if markdown else None,bundle[2])
def inventory(d,path): return next(x for x in d['legacy_artifact_inventory'] if x['path_or_pattern']==path)
def test_happy_path_validator_cli():
 p=subprocess.run([sys.executable,str(ROOT/'scripts/validate_artifact_manifest_schema.py'),str(SCHEMA)],cwd=ROOT,text=True,capture_output=True); assert p.returncode==0,p.stderr; assert 'A2 compatible' in p.stdout
def test_json_markdown_sync(bundle): assert errors(bundle,True)==[]
def test_closed_envelope(bundle): bundle[0]['examples'][0]['manifest']['content']='forbidden'; assert any('closed envelope' in x for x in errors(bundle))
def test_missing_mandatory_field(bundle): del bundle[0]['examples'][0]['manifest']['artifact_id']; assert any('missing mandatory' in x for x in errors(bundle))
@pytest.mark.parametrize('key',['artifact_types','storage_classes','persistence_classes','mutation_modes','retention_modes','semantic_roles','authority_purposes','authority_levels','formats'])
def test_duplicate_enum(bundle,key): bundle[0]['taxonomies'][key].append(bundle[0]['taxonomies'][key][0]); assert errors(bundle)
@pytest.mark.parametrize('field,value',[('artifact_type','ad_hoc_bob'),('storage_class','disk'),('persistence_class','forever'),('mutation_mode','update'),('format','yaml')])
def test_invalid_example_taxonomy(bundle,field,value): bundle[0]['examples'][0]['manifest'][field]=value; assert errors(bundle)
def test_invalid_retention_mode(bundle): bundle[0]['examples'][0]['manifest']['retention_policy']['mode']='forever'; assert errors(bundle)
def test_bounded_count_without_max_items(bundle): bundle[0]['examples'][0]['manifest']['retention_policy']={'mode':'bounded_count','value_source':'code_default'}; assert any('max_items' in x for x in errors(bundle))
def test_bounded_time_without_max_age_days(bundle): bundle[0]['examples'][0]['manifest']['retention_policy']={'mode':'bounded_time','value_source':'code_default'}; assert any('max_age_days' in x for x in errors(bundle))
@pytest.mark.parametrize('path',['/tmp/artifact.json','../artifact.json','x/../../artifact.json','C:/artifact.json'])
def test_unsafe_paths(bundle,path): bundle[0]['examples'][0]['manifest']['path']=path; assert any('unsafe path' in x for x in errors(bundle))
def test_invalid_sha256(bundle): bundle[0]['examples'][0]['manifest']['sha256']='ABC'; assert any('SHA-256' in x for x in errors(bundle))
def test_negative_size_bytes(bundle): bundle[0]['examples'][0]['manifest']['size_bytes']=-1; assert any('non-negative' in x for x in errors(bundle))
def test_invalid_producer_agent(bundle): bundle[0]['examples'][0]['manifest']['producer_agent']='Codex'; assert any('producer agent' in x for x in errors(bundle))
def test_invalid_producer_stage(bundle): bundle[0]['examples'][0]['manifest']['producer_stage']='storage'; assert any('producer stage' in x for x in errors(bundle))
def test_a2_relation_drift(bundle): bundle[2]['artifact_refs_contract']['relation_values'].append('context'); assert any('relation drift' in x for x in errors(bundle))
def test_a2_embed_content_drift(bundle): bundle[2]['artifact_refs_contract']['embed_content']=True; assert any('embed_content' in x for x in errors(bundle))
def test_identity_naming_incompatibility_with_a2(bundle): bundle[0]['identity_links'][0]='execution_id'; assert any('identity naming' in x for x in errors(bundle))
def test_artifact_id_not_path_identity(bundle): bundle[0]['examples'][0]['manifest']['artifact_id']=bundle[0]['examples'][0]['manifest']['path']; assert any('artifact_id' in x for x in errors(bundle))
def test_artifact_id_contract_cannot_be_weakened(bundle): bundle[0]['envelope']['artifact_id_semantics']['not_equivalent_to'].remove('path'); assert any('identity semantics' in x for x in errors(bundle))
def test_master_log_not_append_only(bundle): inventory(bundle[0],'state/newsroom/master_log.jsonl')['mutation_mode']='append_only'; assert any('master_log' in x for x in errors(bundle))
def test_gemini_ledger_not_bounded_rewrite(bundle): inventory(bundle[0],'state/newsroom/gemini_call_ledger.jsonl')['mutation_mode']='bounded_rewrite'; assert any('Gemini ledger' in x for x in errors(bundle))
def test_gemini_latest_not_ledger(bundle): inventory(bundle[0],'artifacts/newsroom/gemini_call_ledger_latest.json')['artifact_type']='ledger'; assert any('Gemini latest' in x for x in errors(bundle))
@pytest.mark.parametrize('path',['artifacts/newsroom/bob_articles.json','artifacts/newsroom/alfred_review.json','artifacts/newsroom/publisher_result.json','review_packages/**/translated.html'])
def test_intermediate_or_metadata_not_final_material(bundle,path): inventory(bundle[0],path)['authority_claims'].append({'purpose':'final_published_material','level':'authoritative'}); assert any('falsely promoted' in x for x in errors(bundle))
def test_master_log_tail_not_primary(bundle): inventory(bundle[0],'artifacts/newsroom/master_log_tail.jsonl')['authority_claims']=[{'purpose':'pipeline_observability','level':'authoritative'}]; assert any('promoted above' in x for x in errors(bundle))
def test_missing_required_inventory_family(bundle): bundle[0]['legacy_artifact_inventory']=[x for x in bundle[0]['legacy_artifact_inventory'] if x['path_or_pattern']!='state/newsroom/master_log.jsonl']; assert any('missing required' in x for x in errors(bundle))
def test_invalid_evidence_basis(bundle): bundle[0]['legacy_artifact_inventory'][0]['evidence_basis']='assumed'; assert errors(bundle)
def test_invalid_lifecycle_status(bundle): bundle[0]['legacy_artifact_inventory'][0]['lifecycle_status']='deprecated'; assert errors(bundle)
def test_schema_version_false_claims(bundle):
 for x in bundle[0]['legacy_artifact_inventory']: x['artifact_schema_status']='known'
 assert any('false claim' in x for x in errors(bundle))
def test_purpose_scoped_authority_rejects_boolean(bundle): bundle[0]['examples'][0]['manifest']['authority_claims']={'authoritative':True}; assert errors(bundle)
def test_stale_markdown_inventory_row(bundle): bundle=(bundle[0],bundle[1].replace('artifacts/newsroom/jarvis_status.json','artifacts/newsroom/stale.json',1),bundle[2]); assert any('Markdown inventory' in x for x in errors(bundle,True))
def test_note_only_markdown_drift(bundle): bundle=(bundle[0],bundle[1].replace('Fixed-path newsroom snapshot atomically replaced by the runner.','Changed note',1),bundle[2]); assert any('Markdown inventory' in x for x in errors(bundle,True))
def test_duplicate_markdown_inventory_row(bundle):
 line=next(x for x in bundle[1].splitlines() if x.startswith('| artifacts/newsroom/jarvis_status.json ')); bundle=(bundle[0],bundle[1].replace(line,line+'\n'+line,1),bundle[2]); assert any('Markdown inventory' in x for x in errors(bundle,True))
def test_markdown_taxonomy_bidirectional_drift(bundle): bundle=(bundle[0],bundle[1].replace('| snapshot |','| stale_snapshot |',1),bundle[2]); assert errors(bundle,True)  # marker/table semantic marker remains immutable JSON; inventory/table catches stale rows if relevant
def test_python39_syntax_compatibility():
 for p in [ROOT/'scripts/validate_artifact_manifest_schema.py',Path(__file__)]:
  r=subprocess.run([sys.executable,'-m','py_compile',str(p)],capture_output=True,text=True); assert r.returncode==0,r.stderr
def test_phase1_scope_cannot_be_enabled(bundle): bundle[0]['phase_boundary']['creates_artifact_index']=True; assert any('scope boundary' in x for x in errors(bundle))
def test_examples_cover_required_cases(bundle): assert {x['label'] for x in bundle[0]['examples']}=={'Bob current-run snapshot','master_log bounded history','Gemini append-only ledger','Gemini latest snapshot','Menzo duplicate pair coverage','published_html_review verified final artifact','review package source/candidate material','future retained source artifact linked by content_id'}


def test_master_log_error_path_is_artifact_only(bundle):
 paths={x['path_or_pattern'] for x in bundle[0]['legacy_artifact_inventory']}
 assert 'artifacts/newsroom/master_log_error.json' in paths
 assert 'state/newsroom/master_log_error.json' not in paths
 inventory(bundle[0],'artifacts/newsroom/master_log_error.json')['path_or_pattern']='state/newsroom/master_log_error.json'
 assert any('master_log_error' in x for x in errors(bundle))

@pytest.mark.parametrize('path,limit',[('artifacts/newsroom/newsroom_master.log',40),('logs/newsroom_master.log',300)])
def test_human_master_logs_are_bounded_rewrites(bundle,path,limit):
 row=inventory(bundle[0],path)
 assert row['producer_component']=='agents.master_log_v93_19'
 assert row['persistence_class']=='bounded_history' and row['mutation_mode']=='bounded_rewrite'
 assert row['retention_summary']=={'mode':'bounded_count','max_items':limit,'value_source':'runtime_configurable'}
 row['mutation_mode']='append_only'
 assert any('human-log contract' in x for x in errors(bundle))

@pytest.mark.parametrize('path,role,purpose',[
 ('published_html_review/**/original.html','source_material','source_material'),
 ('published_html_review/**/final.html','final_published_material','final_published_material'),
 ('published_html_review/*_original.html','source_material','source_material'),
 ('published_html_review/*_final.html','final_published_material','final_published_material'),
 ('published_html_review/v93[-_]news[-_]*.html','translated_candidate','translated_candidate_material'),
 ('published_html_review/v93[-_]publisher[-_]*.html','final_published_material','final_published_material')])
def test_published_html_adapter_families(bundle,path,role,purpose):
 row=inventory(bundle[0],path); assert role in row['semantic_roles']; assert any(x['purpose']==purpose for x in row['authority_claims'])
 row['semantic_roles']=['diagnostic_output']; assert any('adapter semantics' in x for x in errors(bundle))

def test_published_html_unknown_is_diagnostic_without_declassifying_adapters(bundle):
 row=inventory(bundle[0],'published_html_review/**/*.html'); assert row['semantic_roles']==['diagnostic_output']; assert 'after recognized' in row['notes']
 row['authority_claims'][0]['level']='authoritative'; assert any('diagnostic-only' in x for x in errors(bundle))

@pytest.mark.parametrize('path,fmt,role,purpose',[
 ('review_packages/**/original.html','html','source_material','source_material'),
 ('review_packages/**/source.html','html','source_material','source_material'),
 ('review_packages/**/*_original.html','html','source_material','source_material'),
 ('review_packages/**/*_source.html','html','source_material','source_material'),
 ('review_packages/**/translated.html','html','translated_candidate','translated_candidate_material'),
 ('review_packages/**/candidate.html','html','translated_candidate','translated_candidate_material'),
 ('review_packages/**/body.html','html','translated_candidate','translated_candidate_material'),
 ('review_packages/**/*_translated.html','html','translated_candidate','translated_candidate_material'),
 ('review_packages/**/*_candidate.html','html','translated_candidate','translated_candidate_material'),
 ('review_packages/**/*_body.html','html','translated_candidate','translated_candidate_material'),
 ('review_packages/**/metadata.json','json','diagnostic_output','quality_review')])
def test_review_package_pattern_format_and_role(bundle,path,fmt,role,purpose):
 row=inventory(bundle[0],path); assert row['format']==fmt and role in row['semantic_roles']; assert any(x['purpose']==purpose for x in row['authority_claims']); assert not any(x['purpose']=='final_published_material' for x in row['authority_claims'])

def test_review_package_unknown_html_is_diagnostic(bundle):
 row=inventory(bundle[0],'review_packages/**/*.html'); assert row['format']=='html' and row['semantic_roles']==['diagnostic_output','quality_review']

@pytest.mark.parametrize('path,fmt',[('reports/*.json','json'),('reports/*.md','markdown')])
def test_report_extension_format_split(bundle,path,fmt): assert inventory(bundle[0],path)['format']==fmt

@pytest.mark.parametrize('path,bad_format',[('reports/*.json','markdown'),('reports/*.md','json'),('review_packages/**/metadata.json','html'),('published_html_review/**/final.html','zip')])
def test_pattern_extension_format_validator(bundle,path,bad_format):
 inventory(bundle[0],path)['format']=bad_format; assert any('extension requires format' in x for x in errors(bundle))

def test_pair_coverage_real_schema_and_producer(bundle):
 row=inventory(bundle[0],'artifacts/newsroom/menzo_duplicate_pair_coverage.json'); assert row['producer_component']=='agents.menzo_policy_v93_15'
 ex=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='Menzo duplicate pair coverage'); assert ex['artifact_schema_version']['version']=='owtv_duplicate_pair_coverage_v1'
 ex['artifact_schema_version']['version']='v95.21.1'; assert any('real artifact schema' in x for x in errors(bundle))

def test_simone_raw_results_selector(bundle):
 row=inventory(bundle[0],'artifacts/newsroom/simone_report_publish.json'); assert row['authority_claims'][0]['selector']=='results[status=published]'
 row['authority_claims'][0]['selector']='published_reports[status=published]'; assert any('Simone raw artifact selector' in x for x in errors(bundle))

@pytest.mark.parametrize('index,key,value',[(0,'id','weakened'),(0,'when','anything'),(0,'require',[]),(1,'when','anything'),(2,'when',{'producer_component_kind':'anything'}),(2,'require',[])])
def test_conditional_requirements_are_immutable(bundle,index,key,value):
 bundle[0]['envelope']['conditional_requirements'][index][key]=value; assert any('conditional_requirements' in x for x in errors(bundle))

@pytest.mark.parametrize('object_name,key,value',[
 ('retention_policy_contract','required_fields',['mode']),('retention_policy_contract','optional_fields',[]),
 ('authority_claim_contract','single_authoritative_boolean_forbidden',False),('authority_claim_contract','required_fields',['purpose']),
 ('path_contract','relative_only',False),('path_contract','traversal_forbidden',False),('path_contract','content_embedding_forbidden',False),
 ('integrity_contract','required_for_legacy',True),('integrity_contract','size_bytes_minimum',-1)])
def test_core_contract_declarations_are_immutable(bundle,object_name,key,value):
 bundle[0][object_name][key]=value; assert any(object_name in x for x in errors(bundle))

def test_document_required_sections_cannot_disable_markdown_check(bundle):
 bundle[0]['document_sync']['required_sections'].remove('Scope guard'); assert any('document_sync.required_sections' in x for x in errors(bundle))

def test_future_source_inventory_and_example_are_aligned(bundle):
 row=inventory(bundle[0],'state/newsroom/future_retained_source/**'); assert row['storage_class']=='runtime_state' and row['retention_summary']['mode']=='unknown_legacy'
 ex=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='future retained source artifact linked by content_id'); assert ex['path'].startswith('state/newsroom/future_retained_source/') and ex['storage_class']=='runtime_state'
 ex['path']='future_retained_sources/content-1/source.html'; assert any('future retained source example' in x for x in errors(bundle))

def test_documented_published_html_retention_is_unknown(bundle):
 rows=[x for x in bundle[0]['legacy_artifact_inventory'] if x['path_or_pattern'].startswith('published_html_review/')]
 assert rows and all(x['retention_summary']=={'mode':'unknown_legacy','value_source':'unknown_legacy'} for x in rows)


@pytest.mark.parametrize('name,key,value',[
 ('artifact_id','type','integer'),('artifact_id','presence','optional'),
 ('producer_agent','presence','required'),('size_bytes','type','string')])
def test_envelope_field_definition_is_immutable(bundle,name,key,value):
 row=next(x for x in bundle[0]['envelope']['fields'] if x['name']==name); row[key]=value
 assert any('field definitions' in x for x in errors(bundle))

def test_envelope_field_row_cannot_lose_type_or_presence(bundle):
 del bundle[0]['envelope']['fields'][0]['type']; assert any('field definitions' in x for x in errors(bundle))

def test_duplicate_envelope_field_definition_fails(bundle):
 bundle[0]['envelope']['fields'].append(copy.deepcopy(bundle[0]['envelope']['fields'][0])); assert any('field definitions' in x for x in errors(bundle))

def test_row_presence_and_partition_must_agree(bundle):
 row=next(x for x in bundle[0]['envelope']['fields'] if x['name']=='producer_agent');row['presence']='required'
 bundle[0]['envelope']['required_fields'].append('producer_agent');bundle[0]['envelope']['optional_fields'].remove('producer_agent')
 assert any('field definitions' in x for x in errors(bundle))

def test_known_agent_component_requires_producer_agent(bundle):
 del bundle[0]['examples'][0]['manifest']['producer_agent']; assert any('requires producer_agent' in x for x in errors(bundle))

def test_non_agent_diagnostic_component_may_omit_producer_agent(bundle):
 ex=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='published_html_review verified final artifact'); assert 'producer_agent' not in ex; assert errors(bundle)==[]

def test_invalid_agent_for_known_component_fails(bundle):
 bundle[0]['examples'][0]['manifest']['producer_agent']='UnknownAgent'; assert any('invalid producer agent' in x for x in errors(bundle))

def test_producer_requirement_mapping_is_immutable(bundle):
 bundle[0]['producer_agent_requirement']['required_for_components'].remove('newsroom_runner'); assert any('producer_agent_requirement' in x for x in errors(bundle))

def test_examples_align_with_family_retention_and_schema(bundle):
 final=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='published_html_review verified final artifact')
 future=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='future retained source artifact linked by content_id')
 assert final['retention_policy']=={'mode':'unknown_legacy','value_source':'unknown_legacy'}
 assert future['artifact_schema_version']=={'status':'none_unknown'}
 final['retention_policy']={'mode':'persistent','value_source':'code_default'}; assert any('example/family contract mismatch' in x for x in errors(bundle))

def test_example_family_core_field_drift_fails(bundle):
 bundle[0]['examples'][0]['manifest']['persistence_class']='persistent_state'; assert any('example/family contract mismatch' in x for x in errors(bundle))

def test_python_glob_v1_supported_and_modular_pattern_representable(bundle):
 assert bundle[0]['path_pattern_contract']['dialect']=='python_glob_v1'
 assert inventory(bundle[0],'published_html_review/v93[-_]news[-_]*.html')['format']=='html'
 assert errors(bundle)==[]

def test_unsupported_brace_expansion_fails(bundle):
 inventory(bundle[0],'review_packages/**/source.html')['path_or_pattern']='review_packages/**/{source,original}.html'
 assert any('unsupported brace expansion' in x for x in errors(bundle))

def test_path_pattern_contract_is_immutable(bundle):
 bundle[0]['path_pattern_contract']['brace_expansion']=True; assert any('path_pattern_contract' in x for x in errors(bundle))

def test_markdown_example_only_mutation_fails(bundle):
 md=bundle[1].replace('"artifact_id":"example:instance:001"','"artifact_id":"example:instance:stale"',1)
 assert any('Markdown examples' in x for x in errors((bundle[0],md,bundle[2]),True))

@pytest.mark.parametrize('status,version,valid',[
 ('known',None,False),('known','schema-v1',True),('producer_version_only',None,False),
 ('producer_version_only','runtime-v2',True),('none_unknown','invented',False),('varies','one-version',False)])
def test_artifact_schema_version_status_rules(bundle,status,version,valid):
 obj={'status':status};
 if version is not None:obj['version']=version
 bundle[0]['examples'][0]['manifest']['artifact_schema_version']=obj
 has_schema_error=any('artifact_schema_version' in x for x in errors(bundle))
 assert has_schema_error is (not valid)

def test_artifact_schema_version_contract_is_immutable(bundle):
 bundle[0]['artifact_schema_version_contract']['status_rules']['none_unknown']['version']='optional'
 assert any('artifact_schema_version_contract' in x for x in errors(bundle))

@pytest.mark.parametrize('field,value',[('artifact_created_at_utc',123),('code_commit',123),('semantic_roles','translated_candidate'),('retention_policy',[]),('authority_claims',{}),('size_bytes',True)])
def test_manifest_instance_field_spec_types_are_enforced(bundle,field,value):
 bundle[0]['examples'][0]['manifest'][field]=value
 assert any(('canonical type' in error and field in error) for error in errors(bundle))

def test_valid_optional_field_omission_still_passes(bundle):
 manifest=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='future retained source artifact linked by content_id')
 for field in bundle[0]['envelope']['optional_fields']:
  manifest.pop(field,None)
 assert errors(bundle)==[]

@pytest.mark.parametrize('component,path',[('agents.publisher_history','state/newsroom/publisher_history.json'),('agents.simone_publisher_v93_18','state/newsroom/simone_reports_latest.json')])
def test_additional_known_agentic_component_requires_agent(bundle,component,path):
 row=inventory(bundle[0],path)
 example=copy.deepcopy(bundle[0]['examples'][0]['manifest'])
 example.update(artifact_id='example:agentic:'+component,path=path,artifact_type=row['artifact_type'],storage_class=row['storage_class'],format=row['format'],producer_component=component,producer_stage=row['producer_stage'],semantic_roles=row['semantic_roles'],persistence_class=row['persistence_class'],mutation_mode=row['mutation_mode'],retention_policy=row['retention_summary'],authority_claims=row['authority_claims'],artifact_schema_version={'status':row['artifact_schema_status']})
 example.pop('producer_agent',None)
 bundle[0]['examples'].append({'label':'temporary agentic example','manifest':example})
 assert any('requires producer_agent' in error for error in errors(bundle))

def test_future_reform_component_may_omit_agent(bundle):
 example=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='future retained source artifact linked by content_id')
 assert example['producer_component']=='future Reform B retention' and 'producer_agent' not in example
 assert errors(bundle)==[]

def test_removing_known_inventory_component_requirement_fails(bundle):
 bundle[0]['producer_agent_requirement']['required_for_components'].remove('agents.publisher_history')
 assert any('producer_agent_requirement' in error for error in errors(bundle))

def resolved(bundle,path):
 from scripts.validate_artifact_manifest_schema import matching_families
 return matching_families(path,bundle[0]['legacy_artifact_inventory'])

def test_published_final_specific_family_beats_catch_all(bundle):
 rows=resolved(bundle,'published_html_review/run/item/final.html')
 assert [x['path_or_pattern'] for x in rows]==['published_html_review/**/final.html']
 assert rows[0]['semantic_roles']==['final_published_material']

def test_published_original_specific_family_beats_catch_all(bundle):
 rows=resolved(bundle,'published_html_review/run/item/original.html')
 assert [x['path_or_pattern'] for x in rows]==['published_html_review/**/original.html']
 assert rows[0]['semantic_roles']==['source_material']

def test_unknown_published_html_uses_diagnostic_catch_all(bundle):
 rows=resolved(bundle,'published_html_review/unrecognized.html')
 assert [x['path_or_pattern'] for x in rows]==['published_html_review/**/*.html']
 assert rows[0]['semantic_roles']==['diagnostic_output']

def test_review_source_specific_family_beats_catch_all(bundle):
 rows=resolved(bundle,'review_packages/x/source.html')
 assert [x['path_or_pattern'] for x in rows]==['review_packages/**/source.html']
 assert 'source_material' in rows[0]['semantic_roles']

def test_final_example_cannot_validate_as_diagnostic_catch_all(bundle):
 ex=next(x['manifest'] for x in bundle[0]['examples'] if x['label']=='published_html_review verified final artifact')
 ex['semantic_roles']=['diagnostic_output'];ex['authority_claims']=[{'purpose':'final_published_material','level':'diagnostic','selector':'only HTML not matched by a recognized adapter'}]
 assert any('example/family contract mismatch' in error for error in errors(bundle))

def test_family_resolution_contract_is_immutable(bundle):
 bundle[0]['family_resolution_contract']['strategy']='inventory_order'
 assert any('family_resolution_contract' in error for error in errors(bundle))

def test_simone_latest_publication_state_family(bundle):
 row=inventory(bundle[0],'state/newsroom/simone_report_publish_latest.json')
 assert row['producer_component']=='agents.simone_publisher_v93_18' and row['producer_agent']=='Simone'
 assert row['evidence_basis']=='code_declared' and row['artifact_type']=='snapshot'
 assert row['persistence_class']=='current_snapshot' and row['mutation_mode']=='atomic_overwrite'
 assert row['authority_claims']==[{'purpose':'report_publication_outcome','level':'authoritative','selector':'results[status=published]'}]
 assert not any(x['purpose']=='final_published_material' for x in row['authority_claims'])

def test_missing_simone_latest_publication_state_fails(bundle):
 bundle[0]['legacy_artifact_inventory']=[x for x in bundle[0]['legacy_artifact_inventory'] if x['path_or_pattern']!='state/newsroom/simone_report_publish_latest.json']
 assert any('missing required legacy inventory family' in error for error in errors(bundle))

@pytest.mark.parametrize('pattern,paths',[('review_packages/**/source.html',['review_packages/source.html','review_packages/run/item/source.html']),('published_html_review/**/final.html',['published_html_review/final.html','published_html_review/run/item/final.html'])])
def test_double_star_slash_matches_zero_or_more_directories(bundle,pattern,paths):
 from scripts.validate_artifact_manifest_schema import glob_regex
 import re
 assert all(re.fullmatch(glob_regex(pattern),path) for path in paths)

@pytest.mark.parametrize('field',[ 'artifact_created_at_utc','code_commit','content_id','producer_agent'])
def test_optional_string_present_but_empty_fails(bundle,field):
 bundle[0]['examples'][0]['manifest'][field]=''
 assert any(field in error and 'non-empty' in error for error in errors(bundle))

def test_optional_string_whitespace_only_fails(bundle):
 bundle[0]['examples'][0]['manifest']['code_commit']='   '
 assert any('code_commit' in error and 'non-empty' in error for error in errors(bundle))
