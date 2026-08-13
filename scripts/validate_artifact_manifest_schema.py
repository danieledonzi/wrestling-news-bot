#!/usr/bin/env python3
"""Validate OWTV Artifact Manifest Schema v1; Python 3.9 stdlib only."""
import argparse, json, re, sys
from collections import Counter
from pathlib import Path, PurePosixPath
EXPECTED_SCHEMA='owtv_artifact_manifest_schema_v1'; EXPECTED_POLICY='v95.22_a3'
EXPECTED={
'artifact_types':['snapshot','ledger','history','cache','memory','coverage','archive','report','log'],
'storage_classes':['runtime_snapshot','runtime_state','runtime_log','diagnostic_report','review_archive','published_material_archive'],
'persistence_classes':['current_snapshot','bounded_history','persistent_state','append_only_ledger','immutable_archive','generated_report'],
'mutation_modes':['atomic_overwrite','bounded_rewrite','append_only','immutable'],
'retention_modes':['current_only','bounded_count','bounded_time','persistent','sampled','unknown_legacy'],
'retention_value_sources':['fixed_contract','code_default','runtime_configurable','unknown_legacy'],
'semantic_roles':['runtime_status','intake_snapshot','report_lifecycle','selection_decision','duplicate_evidence','content_sufficiency','translated_candidate','quality_review','publication_result','audit','model_call_telemetry','source_material','final_published_material','diagnostic_output','state_memory'],
'authority_purposes':['pipeline_observability','publication_outcome','report_publication_outcome','source_material','translated_candidate_material','final_published_material','duplicate_decision','quality_review','model_usage_cost','runtime_health'],
'authority_levels':['authoritative','supporting','diagnostic','legacy_context'],
'formats':['json','jsonl','text/log','markdown','html','zip'],
'evidence_basis':['both','observed_production','code_declared','documented_legacy','planned_canonical'],
'lifecycle_statuses':['active','fallback','legacy','error_only','planned'],
'artifact_schema_statuses':['known','producer_version_only','none_unknown','varies']}
FIELD_SPEC=[('schema_version', 'string', 'required'), ('policy_version', 'string', 'required'), ('artifact_id', 'string', 'required'), ('artifact_type', 'string', 'required'), ('path', 'string', 'required'), ('storage_class', 'string', 'required'), ('format', 'string', 'required'), ('producer_agent', 'string', 'optional'), ('producer_stage', 'string', 'required'), ('producer_component', 'string', 'required'), ('manifested_at_utc', 'string', 'required'), ('artifact_created_at_utc', 'string', 'optional'), ('run_id', 'string', 'optional'), ('article_id', 'string', 'optional'), ('pair_id', 'string', 'optional'), ('correlation_id', 'string', 'optional'), ('content_id', 'string', 'optional'), ('story_id', 'string', 'optional'), ('report_key', 'string', 'optional'), ('logical_request_id', 'string', 'optional'), ('semantic_roles', 'array', 'required'), ('persistence_class', 'string', 'required'), ('mutation_mode', 'string', 'required'), ('retention_policy', 'object', 'required'), ('authority_claims', 'array', 'required'), ('artifact_schema_version', 'object', 'required'), ('sha256', 'string', 'optional'), ('size_bytes', 'integer', 'optional'), ('code_commit', 'string', 'optional')]
FIELDS={'schema_version','policy_version','artifact_id','artifact_type','path','storage_class','format','producer_agent','producer_stage','producer_component','manifested_at_utc','artifact_created_at_utc','run_id','article_id','pair_id','correlation_id','content_id','story_id','report_key','logical_request_id','semantic_roles','persistence_class','mutation_mode','retention_policy','authority_claims','artifact_schema_version','sha256','size_bytes','code_commit'}
REQUIRED={'schema_version','policy_version','artifact_id','artifact_type','path','storage_class','format','producer_stage','producer_component','manifested_at_utc','semantic_roles','persistence_class','mutation_mode','retention_policy','authority_claims','artifact_schema_version'}
IDENTITIES=['run_id','article_id','pair_id','correlation_id','content_id','story_id','report_key','logical_request_id']
DOCUMENT_SECTIONS=['Purpose and scope','A1, A2, Phase 1 and Reform B','Artifact instance and family','Taxonomies','Retention policy','Purpose-scoped authority','Path-pattern dialect','Identity, path and integrity','A2 artifact_refs compatibility','Legacy artifact inventory','Examples','Null, missing and not applicable','Scope guard']
CONDITIONS=[{'id':'bounded_count_limit','when':'retention_policy.mode == bounded_count','require':['retention_policy.max_items']},{'id':'bounded_time_limit','when':'retention_policy.mode == bounded_time','require':['retention_policy.max_age_days']},{'id':'producer_agent_if_applicable','when':{'producer_component_kind':'canonical_newsroom_or_model_agent'},'require':['producer_agent']}]
RETENTION_CONTRACT={'additional_fields_allowed':False,'required_fields':['mode','value_source'],'optional_fields':['max_items','max_age_days'],'max_items_minimum':1,'max_age_days_minimum':1}
AUTHORITY_CONTRACT={'additional_fields_allowed':False,'required_fields':['purpose','level'],'optional_fields':['selector','note'],'purpose_scoped':True,'single_authoritative_boolean_forbidden':True}
PATH_CONTRACT={'relative_only':True,'traversal_forbidden':True,'content_embedding_forbidden':True,'extension_format_mapping':{'.json':'json','.jsonl':'jsonl','.md':'markdown','.html':'html','.zip':'zip','.log':'text/log'},'documented_pattern_exceptions':[]}
INTEGRITY_CONTRACT={'sha256_pattern':'^[0-9a-f]{64}$','size_bytes_minimum':0,'required_for_legacy':False,'recommended_for':['immutable_archive','future artifact-index entries']}
EXT_FORMAT={'.json':'json','.jsonl':'jsonl','.md':'markdown','.html':'html','.zip':'zip','.log':'text/log'}
PRODUCER_REQUIREMENT={'required_for_components':['newsroom_runner','agents.master_log_v93_19','agents.gemini_ledger','agents.menzo_policy_v93_15','agents.publisher_history','agents.simone_publisher_v93_18','agents.menzo_duplicate_cache','agents.story_dedupe_v93_32'],'exempt_components_may_omit':True,'unknown_components_may_omit':True}
PATTERN_CONTRACT={'dialect':'python_glob_v1','separator':'/','supported_tokens':['*','**','?','[...]'],'brace_expansion':False,'absolute_paths_allowed':False,'parent_traversal_allowed':False,'filesystem_discovery':False}
SCHEMA_VERSION_CONTRACT={'additional_fields_allowed':False,'required_fields':['status'],'optional_fields':['version'],'status_rules':{'known':{'version':'required_non_empty_artifact_schema_version'},'producer_version_only':{'version':'required_non_empty_producer_or_runtime_version_not_artifact_schema'},'none_unknown':{'version':'forbidden'},'varies':{'version':'forbidden'}}}
REQUIRED_PATHS={'artifacts/newsroom/jarvis_status.json','artifacts/newsroom/massy_board.json','artifacts/newsroom/simone_reports.json','artifacts/newsroom/simone_report_publish.json','artifacts/newsroom/menzo_decisions.json','artifacts/newsroom/andrea_pre_bob_latest.json','artifacts/newsroom/bob_articles.json','artifacts/newsroom/alfred_review.json','artifacts/newsroom/publisher_result.json','artifacts/newsroom/archivista_report.json','artifacts/newsroom/agent_timeline.json','artifacts/newsroom/run_summary.json','artifacts/newsroom/master_log_tail.jsonl','artifacts/newsroom/newsroom_master.log','artifacts/newsroom/gemini_call_ledger_latest.json','artifacts/newsroom/menzo_duplicate_pair_coverage.json','state/newsroom/master_log.jsonl','state/newsroom/gemini_call_ledger.jsonl','state/newsroom/publisher_history.json','state/newsroom/simone_report_history.json','state/newsroom/simone_reports_latest.json','state/newsroom/menzo_duplicate_arbitration_cache_v2.json','reports/*.json','reports/*.md','review_packages/**/original.html','review_packages/**/source.html','review_packages/**/translated.html','review_packages/**/candidate.html','review_packages/**/body.html','review_packages/**/*.html','published_html_review/**/original.html','published_html_review/**/final.html','published_html_review/*_original.html','published_html_review/*_final.html','published_html_review/v93[-_]news[-_]*.html','published_html_review/v93[-_]publisher[-_]*.html','published_html_review/**/*.html','logs/newsroom_master.log','artifacts/newsroom/master_log_error.json'}
INV_KEYS={'path_or_pattern','artifact_type','format','producer_component','producer_agent','producer_stage','storage_class','persistence_class','mutation_mode','evidence_basis','lifecycle_status','semantic_roles','retention_summary','authority_claims','artifact_schema_status','notes'}
def err(a,m): a.append(m)
def safe_path(p):
 return isinstance(p,str) and p and not p.startswith(('/', '\\')) and not re.match(r'^[A-Za-z]:',p) and '..' not in PurePosixPath(p.replace('\\','/')).parts
def retention(x, errors, where):
 if not isinstance(x,dict) or not {'mode','value_source'} <= set(x) or not set(x) <= {'mode','value_source','max_items','max_age_days'}: err(errors,where+' invalid retention policy'); return
 if x['mode'] not in EXPECTED['retention_modes'] or x['value_source'] not in EXPECTED['retention_value_sources']: err(errors,where+' invalid retention mode/value source')
 if x['mode']=='bounded_count' and not isinstance(x.get('max_items'),int): err(errors,where+' bounded_count requires max_items')
 if x['mode']=='bounded_time' and not isinstance(x.get('max_age_days'),int): err(errors,where+' bounded_time requires max_age_days')
 for k in ('max_items','max_age_days'):
  if k in x and (not isinstance(x[k],int) or isinstance(x[k],bool) or x[k]<1): err(errors,where+' '+k+' must be positive')
def claims(xs,errors,where):
 if not isinstance(xs,list): err(errors,where+' authority_claims must be list'); return
 for x in xs:
  if not isinstance(x,dict) or not {'purpose','level'} <= set(x) or not set(x) <= {'purpose','level','selector','note'}: err(errors,where+' malformed purpose-scoped authority claim'); continue
  if x['purpose'] not in EXPECTED['authority_purposes'] or x['level'] not in EXPECTED['authority_levels']: err(errors,where+' invalid authority purpose/level')
def envelope(x,errors,where):
 if not isinstance(x,dict): err(errors,where+' must be object'); return
 unknown=set(x)-FIELDS; missing=REQUIRED-set(x)
 if unknown: err(errors,where+' closed envelope rejects '+','.join(sorted(unknown)))
 if missing: err(errors,where+' missing mandatory field '+','.join(sorted(missing)))
 field_types={name:field_type for name,field_type,_presence in FIELD_SPEC}
 for name,value in x.items():
  expected=field_types.get(name)
  valid=(expected=='string' and isinstance(value,str)) or (expected=='integer' and isinstance(value,int) and not isinstance(value,bool)) or (expected=='array' and isinstance(value,list)) or (expected=='object' and isinstance(value,dict))
  if expected and not valid:err(errors,where+' field '+name+' must have canonical type '+expected)
 if x.get('schema_version')!=EXPECTED_SCHEMA or x.get('policy_version')!=EXPECTED_POLICY: err(errors,where+' version mismatch')
 if x.get('artifact_id') in [x.get(k) for k in ('path','artifact_type','content_id','run_id')]: err(errors,where+' artifact_id must not equal path/type/content_id/run_id')
 if not safe_path(x.get('path')): err(errors,where+' unsafe path')
 for k in IDENTITIES+['artifact_id','producer_component','manifested_at_utc']:
  if k in x and (not isinstance(x[k],str) or not x[k]): err(errors,where+' invalid '+k)
 t=x.get('artifact_type'); s=x.get('storage_class'); p=x.get('persistence_class'); m=x.get('mutation_mode'); f=x.get('format')
 for v,key in [(t,'artifact_types'),(s,'storage_classes'),(p,'persistence_classes'),(m,'mutation_modes'),(f,'formats')]:
  if v not in EXPECTED[key]: err(errors,where+' invalid '+key)
 if x.get('producer_agent') is not None and x.get('producer_agent') not in EXPECTED_A2_AGENTS: err(errors,where+' invalid producer agent')
 if x.get('producer_component') in PRODUCER_REQUIREMENT['required_for_components'] and not x.get('producer_agent'):err(errors,where+' known canonical producer component requires producer_agent')
 if x.get('producer_stage') not in EXPECTED_A2_STAGES: err(errors,where+' invalid producer stage')
 roles=x.get('semantic_roles');
 if not isinstance(roles,list) or not roles or len(roles)!=len(set(roles)) or any(z not in EXPECTED['semantic_roles'] for z in roles): err(errors,where+' invalid semantic roles')
 retention(x.get('retention_policy'),errors,where); claims(x.get('authority_claims'),errors,where)
 av=x.get('artifact_schema_version')
 if not isinstance(av,dict) or av.get('status') not in EXPECTED['artifact_schema_statuses'] or not {'status'}<=set(av)<= {'status','version'}: err(errors,where+' invalid artifact_schema_version')
 else:
  version=av.get('version'); status=av.get('status')
  if status in {'known','producer_version_only'} and (not isinstance(version,str) or not version):err(errors,where+' artifact_schema_version '+status+' requires non-empty version')
  if status in {'none_unknown','varies'} and 'version' in av:err(errors,where+' artifact_schema_version '+status+' forbids version')
 if 'sha256' in x and (not isinstance(x['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',x['sha256'])): err(errors,where+' invalid SHA-256')
 if 'size_bytes' in x and (not isinstance(x['size_bytes'],int) or isinstance(x['size_bytes'],bool) or x['size_bytes']<0): err(errors,where+' size_bytes must be non-negative')
def splitrow(line):
 token='\0'; return [c.strip().replace(token,'|') for c in line.strip().strip('|').replace('\\|',token).split('|')]
def md_table(md):
 marker='<!-- SYNC:INVENTORY_COLUMNS '
 pos=md.find(marker)
 if pos<0:return []
 lines=md[pos:].splitlines(); table=[]; on=False
 for ln in lines[1:]:
  if ln.startswith('|'): on=True; table.append(ln)
  elif on: break
 return [splitrow(x) for x in table[2:]] if len(table)>=2 else []
def canon(v):
 if v is None:return '—'
 if isinstance(v,(dict,list)):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
 return str(v)
def glob_regex(pattern):
 out=''; i=0
 while i<len(pattern):
  c=pattern[i]
  if c=='*':
   if i+1<len(pattern) and pattern[i+1]=='*': out+='.*'; i+=2
   else: out+='[^/]*'; i+=1
  elif c=='?':out+='[^/]';i+=1
  elif c=='[':
   end=pattern.find(']',i+1)
   if end<0:out+=r'\[';i+=1
   else:out+=pattern[i:end+1];i=end+1
  else:out+=re.escape(c);i+=1
 return '^'+out+'$'
def matching_families(path, inventory):
 return [row for row in inventory if re.fullmatch(glob_regex(row.get('path_or_pattern','')),path)]
def markdown_examples(markdown, labels, errors):
 found=[]
 for label in labels:
  match=re.search(r'^### '+re.escape(label)+r'\s*\n```json\s*\n([\s\S]*?)\n```\s*$',markdown,re.M)
  if not match:err(errors,'Markdown missing JSON example: '+label);continue
  try:found.append({'label':label,'manifest':json.loads(match.group(1))})
  except json.JSONDecodeError:err(errors,'Markdown example is invalid JSON: '+label)
 return found
def validate(data,markdown=None,a2=None):
 global EXPECTED_A2_AGENTS,EXPECTED_A2_STAGES
 errors=[]
 if not isinstance(data,dict):return ['root must be object']
 if data.get('schema_version')!=EXPECTED_SCHEMA:err(errors,'schema_version must be '+EXPECTED_SCHEMA)
 if data.get('policy_version')!=EXPECTED_POLICY:err(errors,'policy_version must be '+EXPECTED_POLICY)
 if data.get('contract_scope')!='measurement_only_contract_no_runtime_emission':err(errors,'measurement-only scope weakened')
 b=data.get('phase_boundary',{})
 if b!={'phase':'Phase 0','creates_runtime_manifest':False,'creates_artifact_index':False,'changes_retention':False,'embeds_content':False}:err(errors,'Phase 0 scope boundary changed')
 tax=data.get('taxonomies',{})
 for k,v in EXPECTED.items():
  if tax.get(k)!=v:err(errors,k+' immutable taxonomy mismatch')
  if isinstance(tax.get(k),list) and len(tax[k])!=len(set(tax[k])):err(errors,k+' values must be unique')
 env=data.get('envelope',{}); rows=env.get('fields',[]) if isinstance(env,dict) else []
 if env.get('additional_fields_allowed') is not False:err(errors,'closed manifest envelope required')
 names=[r.get('name') for r in rows if isinstance(r,dict)]
 actual_field_spec=[(r.get('name'),r.get('type'),r.get('presence')) for r in rows if isinstance(r,dict)]
 if actual_field_spec!=FIELD_SPEC or len(names)!=len(set(names)):err(errors,'envelope field definitions must exactly match immutable name/type/presence specification')
 if set(env.get('required_fields',[]))!=REQUIRED or set(env.get('optional_fields',[]))!=FIELDS-REQUIRED or set(env.get('required_fields',[]))&set(env.get('optional_fields',[])):err(errors,'required/optional partition mismatch')
 if env.get('conditional_requirements')!=CONDITIONS:err(errors,'conditional_requirements immutable contract mismatch')
 if data.get('retention_policy_contract')!=RETENTION_CONTRACT:err(errors,'retention_policy_contract immutable contract mismatch')
 if data.get('authority_claim_contract')!=AUTHORITY_CONTRACT:err(errors,'authority_claim_contract immutable contract mismatch')
 if data.get('path_contract')!=PATH_CONTRACT:err(errors,'path_contract immutable contract mismatch')
 if data.get('integrity_contract')!=INTEGRITY_CONTRACT:err(errors,'integrity_contract immutable contract mismatch')
 if data.get('producer_agent_requirement')!=PRODUCER_REQUIREMENT:err(errors,'producer_agent_requirement immutable contract mismatch')
 if data.get('path_pattern_contract')!=PATTERN_CONTRACT:err(errors,'path_pattern_contract immutable contract mismatch')
 if data.get('artifact_schema_version_contract')!=SCHEMA_VERSION_CONTRACT:err(errors,'artifact_schema_version_contract immutable contract mismatch')
 if data.get('document_sync',{}).get('required_sections')!=DOCUMENT_SECTIONS:err(errors,'document_sync.required_sections immutable contract mismatch')
 sem=env.get('artifact_id_semantics',{})
 if sem.get('not_equivalent_to')!=['path','artifact_type','content_id','run_id'] or not all(sem.get(k) is True for k in ['identifies_concrete_instance','stable_for_same_instance','unique_across_distinct_instances']):err(errors,'artifact_id/path identity semantics weakened')
 if sem.get('runtime_generation_algorithm')!='not_defined_in_phase_0':err(errors,'A3 must not define runtime artifact_id writer')
 EXPECTED_A2_AGENTS=set((a2 or {}).get('agents',[])); EXPECTED_A2_STAGES=set((a2 or {}).get('stages',[]))
 agentic_inventory_components={row.get('producer_component') for row in data.get('legacy_artifact_inventory',[]) if row.get('producer_agent') in EXPECTED_A2_AGENTS and (row.get('producer_component')=='newsroom_runner' or str(row.get('producer_component','')).startswith('agents.'))}
 if agentic_inventory_components!=set(PRODUCER_REQUIREMENT['required_for_components']):err(errors,'producer_agent_requirement must cover every known agentic inventory component')
 if not EXPECTED_A2_AGENTS or not EXPECTED_A2_STAGES:err(errors,'A2 canonical agents/stages unavailable')
 comp=data.get('a2_compatibility',{}); art=(a2 or {}).get('artifact_refs_contract',{})
 if (a2 or {}).get('schema_version')!='owtv_event_schema_v1':err(errors,'A2 schema_version incompatible')
 if comp.get('producer_agents')!=(a2 or {}).get('agents') or comp.get('producer_stages')!=(a2 or {}).get('stages'):err(errors,'producer agent/stage compatibility drift')
 if data.get('identity_links')!=IDENTITIES or not set(IDENTITIES)<=set(r.get('name') for r in (a2 or {}).get('identities',{}).get('fields',[])):err(errors,'identity naming incompatibility with A2')
 if comp.get('artifact_ref_relations')!=['input','output','evidence'] or art.get('relation_values')!=['input','output','evidence']:err(errors,'A2 relation drift')
 if comp.get('artifact_ref_required_fields')!=['path','relation'] or set(art.get('required_item_fields',[]))!={'path','relation'}:err(errors,'A2 artifact reference required fields drift')
 if comp.get('artifact_ref_optional_fields')!=['artifact_type','schema_version','sha256'] or set(art.get('optional_item_fields',[]))!={'artifact_type','schema_version','sha256'}:err(errors,'A2 artifact reference optional fields drift')
 if comp.get('embed_content') is not False or art.get('embed_content') is not False:err(errors,'A2 embed_content drift')
 inv=data.get('legacy_artifact_inventory',[]); paths=[]
 for i,x in enumerate(inv):
  w='inventory[%d]'%i
  if not isinstance(x,dict) or set(x)!=INV_KEYS:err(errors,w+' malformed inventory row');continue
  paths.append(x['path_or_pattern'])
  for val,key in [(x['artifact_type'],'artifact_types'),(x['storage_class'],'storage_classes'),(x['persistence_class'],'persistence_classes'),(x['mutation_mode'],'mutation_modes'),(x['format'],'formats'),(x['evidence_basis'],'evidence_basis'),(x['lifecycle_status'],'lifecycle_statuses'),(x['artifact_schema_status'],'artifact_schema_statuses')]:
   if val not in EXPECTED[key]:err(errors,w+' invalid '+key)
  if not safe_path(x['path_or_pattern']):err(errors,w+' unsafe path/pattern')
  if '{' in x['path_or_pattern'] or '}' in x['path_or_pattern']:err(errors,w+' unsupported brace expansion in python_glob_v1')
  matches=[(ext,fmt) for ext,fmt in EXT_FORMAT.items() if x['path_or_pattern'].lower().endswith(ext)]
  if len(matches)==1 and x['format']!=matches[0][1]:err(errors,w+' path/pattern extension requires format '+matches[0][1])
  if x['producer_agent'] is not None and x['producer_agent'] not in EXPECTED_A2_AGENTS:err(errors,w+' invalid producer agent')
  if x['producer_stage'] not in EXPECTED_A2_STAGES:err(errors,w+' invalid producer stage')
  if not x['notes']:err(errors,w+' notes required')
  if not isinstance(x['semantic_roles'],list) or any(z not in EXPECTED['semantic_roles'] for z in x['semantic_roles']):err(errors,w+' invalid semantic role')
  retention(x['retention_summary'],errors,w); claims(x['authority_claims'],errors,w)
 if len(paths)!=len(set(paths)):err(errors,'inventory path/pattern must be unique')
 if not REQUIRED_PATHS<=set(paths):err(errors,'missing required legacy inventory family')
 by={x.get('path_or_pattern'):x for x in inv if isinstance(x,dict)}
 def must(path,key,val,msg):
  if by.get(path,{}).get(key)!=val:err(errors,msg)
 must('state/newsroom/master_log.jsonl','mutation_mode','bounded_rewrite','master_log must be bounded_rewrite')
 must('state/newsroom/gemini_call_ledger.jsonl','mutation_mode','append_only','Gemini ledger must be append_only')
 must('artifacts/newsroom/gemini_call_ledger_latest.json','artifact_type','snapshot','Gemini latest must be snapshot, not ledger')
 if any(c.get('purpose')=='final_published_material' for p,x in by.items() if p in ['artifacts/newsroom/bob_articles.json','artifacts/newsroom/alfred_review.json','artifacts/newsroom/publisher_result.json'] or p.startswith('review_packages/') for c in x.get('authority_claims',[])):err(errors,'candidate/publisher/review package falsely promoted to final material')
 if any(c.get('level')=='authoritative' and c.get('purpose')=='pipeline_observability' for c in by.get('artifacts/newsroom/master_log_tail.jsonl',{}).get('authority_claims',[])):err(errors,'master_log_tail promoted above primary master log')
 if by.get('state/newsroom/master_log.jsonl',{}).get('authority_claims')!=[{'purpose':'pipeline_observability','level':'authoritative','selector':'complete run records'}]:err(errors,'primary master log authority weakened')
 if 'state/newsroom/master_log_error.json' in by or 'artifacts/newsroom/master_log_error.json' not in by:err(errors,'master_log_error must remain under artifacts/newsroom')
 for path,limit in [('artifacts/newsroom/newsroom_master.log',40),('logs/newsroom_master.log',300)]:
  row=by.get(path,{})
  if row.get('producer_component')!='agents.master_log_v93_19' or row.get('persistence_class')!='bounded_history' or row.get('mutation_mode')!='bounded_rewrite' or row.get('retention_summary')!={'mode':'bounded_count','max_items':limit,'value_source':'runtime_configurable'}:err(errors,path+' bounded human-log contract mismatch')
 simone=by.get('artifacts/newsroom/simone_report_publish.json',{})
 if simone.get('authority_claims')!=[{'purpose':'report_publication_outcome','level':'authoritative','selector':'results[status=published]'}]:err(errors,'Simone raw artifact selector must use results[status=published]')
 coverage=by.get('artifacts/newsroom/menzo_duplicate_pair_coverage.json',{})
 if coverage.get('producer_component')!='agents.menzo_policy_v93_15':err(errors,'duplicate pair coverage producer mismatch')
 adapters={'published_html_review/**/original.html':('source_material','source_material'),'published_html_review/**/final.html':('final_published_material','final_published_material'),'published_html_review/*_original.html':('source_material','source_material'),'published_html_review/*_final.html':('final_published_material','final_published_material'),'published_html_review/v93[-_]news[-_]*.html':('translated_candidate','translated_candidate_material'),'published_html_review/v93[-_]publisher[-_]*.html':('final_published_material','final_published_material')}
 for path,(role,purpose) in adapters.items():
  row=by.get(path,{})
  if role not in row.get('semantic_roles',[]) or not any(c.get('purpose')==purpose for c in row.get('authority_claims',[])):err(errors,'published_html_review adapter semantics mismatch: '+path)
 unknown=by.get('published_html_review/**/*.html',{})
 if unknown.get('semantic_roles')!=['diagnostic_output'] or any(c.get('level')!='diagnostic' for c in unknown.get('authority_claims',[])):err(errors,'unknown published HTML must remain diagnostic-only')
 future=by.get('state/newsroom/future_retained_source/**',{})
 if future.get('storage_class')!='runtime_state' or future.get('retention_summary')!={'mode':'unknown_legacy','value_source':'unknown_legacy'}:err(errors,'future retained source family mismatch')
 if all(x.get('artifact_schema_status')=='known' for x in inv):err(errors,'false claim that all legacy artifacts have schema_version')
 for i,e in enumerate(data.get('examples',[])): envelope(e.get('manifest'),errors,'example[%d]'%i)
 examples={e.get('label'):e.get('manifest',{}) for e in data.get('examples',[]) if isinstance(e,dict)}
 pair=examples.get('Menzo duplicate pair coverage',{})
 if pair.get('producer_component')!='agents.menzo_policy_v93_15' or pair.get('artifact_schema_version')!={'status':'known','version':'owtv_duplicate_pair_coverage_v1'}:err(errors,'pair coverage example must use real artifact schema, not runtime release')
 future_example=examples.get('future retained source artifact linked by content_id',{})
 if not str(future_example.get('path','')).startswith('state/newsroom/future_retained_source/') or future_example.get('storage_class')!='runtime_state':err(errors,'future retained source example/family mismatch')
 for label,manifest in examples.items():
  families=matching_families(str(manifest.get('path','')),inv)
  comparable=('artifact_type','storage_class','format','producer_stage','persistence_class','mutation_mode')
  def compatible(row):
   if any(manifest.get(k)!=row.get(k) for k in comparable):return False
   if manifest.get('retention_policy')!=row.get('retention_summary'):return False
   if manifest.get('artifact_schema_version',{}).get('status')!=row.get('artifact_schema_status'):return False
   if not set(manifest.get('semantic_roles',[]))<=set(row.get('semantic_roles',[])):return False
   family_claims={(c.get('purpose'),c.get('level')) for c in row.get('authority_claims',[]) if isinstance(c,dict)}
   manifest_claims=manifest.get('authority_claims',[])
   return isinstance(manifest_claims,list) and all(isinstance(c,dict) and (c.get('purpose'),c.get('level')) in family_claims for c in manifest_claims)
  if not any(compatible(row) for row in families):err(errors,'example/family contract mismatch: '+label)
 if markdown is not None:
  for section in DOCUMENT_SECTIONS:
   if not re.search(r'^## '+re.escape(section)+r'\s*$',markdown,re.M):err(errors,'Markdown missing section: '+section)
  markers={'ARTIFACT_TYPES':'artifact_types','STORAGE_CLASSES':'storage_classes','PERSISTENCE_CLASSES':'persistence_classes','MUTATION_MODES':'mutation_modes','RETENTION_MODES':'retention_modes','SEMANTIC_ROLES':'semantic_roles','AUTHORITY_PURPOSES':'authority_purposes','AUTHORITY_LEVELS':'authority_levels'}
  headings={'artifact_types':'Artifact types','storage_classes':'Storage classes','persistence_classes':'Persistence classes','mutation_modes':'Mutation modes','retention_modes':'Retention modes','semantic_roles':'Semantic roles','authority_purposes':'Authority purposes','authority_levels':'Authority levels'}
  for marker,key in markers.items():
   if '<!-- SYNC:%s %s -->'%(marker,'|'.join(EXPECTED[key])) not in markdown:err(errors,'Markdown sync mismatch: '+key)
   match=re.search(r'^### '+re.escape(headings[key])+r'\s*$([\s\S]*?)(?=^### |^## )',markdown,re.M)
   table=[] if not match else [splitrow(line)[0] for line in match.group(1).splitlines() if line.startswith('| ')][1:]
   if table!=EXPECTED[key]:err(errors,'Markdown taxonomy table mismatch: '+key)
  keys=['path_or_pattern','artifact_type','format','producer_component','producer_agent','producer_stage','storage_class','persistence_class','mutation_mode','evidence_basis','lifecycle_status','semantic_roles','retention_summary','authority_claims','artifact_schema_status','notes']
  jr=[tuple(canon(x[k]) for k in keys) for x in inv]; mr=[tuple(x) for x in md_table(markdown)]
  if Counter(jr)!=Counter(mr):err(errors,'Markdown inventory must exactly match JSON including notes/authority/retention and duplicates')
  labels=[e.get('label') for e in data.get('examples',[]) if isinstance(e,dict)]
  if markdown_examples(markdown,labels,errors)!=data.get('examples',[]):err(errors,'Markdown examples must semantically equal JSON examples')
 return errors
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('schema',nargs='?',default='config/artifact_manifest_schema_v1.json');p.add_argument('--markdown',default='docs/runtime/OWTV_ARTIFACT_MANIFEST_SCHEMA_V1.md');p.add_argument('--event-schema',default='config/event_schema_v1.json');a=p.parse_args(argv)
 try:d=json.loads(Path(a.schema).read_text());m=Path(a.markdown).read_text();e=json.loads(Path(a.event_schema).read_text())
 except (OSError,json.JSONDecodeError) as x:print('artifact manifest validation failed: %s'%x,file=sys.stderr);return 2
 errors=validate(d,m,e)
 if errors:
  for x in errors:print('ERROR: '+x,file=sys.stderr)
  return 1
 print('OK: %s (%d artifact types, %d storage classes, %d legacy families; A2 compatible)'%(a.schema,len(d['taxonomies']['artifact_types']),len(d['taxonomies']['storage_classes']),len(d['legacy_artifact_inventory'])))
 return 0
if __name__=='__main__':sys.exit(main())
