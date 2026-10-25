"""Source-isolated factual cards; no editorial classes or duplicate verdicts.

The two isolated operations are the extraction and identity/tag enrichment used
in the frozen owner tests. Cached stages are bound to URL, complete body, title,
model, policy and schema. Facts are never reassigned by the enrichment operation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / 'state/newsroom/menzo_fact_cards_v1.json'
VERSION = 'isolated-source-facts-tags-v1'
EXTRACTION_POLICY = ROOT / 'docs/editorial-rules/OWTV_ISOLATED_FACT_EXTRACTION_V1.md'
ENRICHMENT_POLICY = ROOT / 'docs/editorial-rules/OWTV_ISOLATED_FACT_ENRICHMENT_V1.md'
MAX_ENTRIES = 4096
FAMILIES = ['promotion_arrival', 'career_departure_retirement', 'medical_availability',
            'business_media_ownership', 'business_touring', 'industry_economics',
            'wrestling_competition', 'event_production', 'disciplinary_conduct', 'other']
FACETS = ['employment_contract', 'promotion_arrival', 'career_retirement_departure',
          'health_injury_recovery', 'personal_family_bereavement', 'participation_availability',
          'media_ownership_business', 'touring_business', 'industry_economics', 'match_result',
          'match_booking_replacement', 'championship_status', 'discipline_conduct',
          'event_production', 'viewership_ratings', 'personal_life', 'creative_character_storyline', 'other']
KINDS = ['focused_news', 'multi_story_roundup', 'show_report']


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else dumps(value)).encode()).hexdigest()


def norm(value):
    text = unicodedata.normalize('NFKD', str(value))
    return re.sub(r'[^a-z0-9]+', '_', ''.join(c for c in text if not unicodedata.combining(c)).lower()).strip('_')


def text(value, limit=1500):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def strings(value, limit=150, maximum=64):
    return isinstance(value, list) and len(value) <= maximum and all(text(v, limit) for v in value)


def obj(properties):
    return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}


def array(items):
    return {'type': 'array', 'items': items}


def source_input(row):
    body = row.get('retained_body')
    if row.get('input_coverage') != 'FULL_BODY' or not text(body, 10_000_000):
        raise ValueError('complete_source_required')
    pieces = [s for s in re.split(r'(?<=[.!?])\s+', body) if s.strip()]
    units = [{'unit_id': 'u' + str(i + 1), 'text': s} for i, s in enumerate(pieces)]
    assert ' '.join(' '.join(x['text'] for x in units).split()) == ' '.join(body.split())
    from agents.menzo_duplicate_scorer import canonical_source_url
    # Use the existing article identity for source stages and owned fact refs.
    url = canonical_source_url(dict(row))
    if not url:
        raise ValueError('canonical_url_required')
    return {'title': row.get('title') or '', 'source_url': url,
            'source_units': units}


def extraction_schema(payload):
    unit = {'type': 'string', 'enum': [r['unit_id'] for r in payload['source_units']]}
    subject = obj({'kind': {'type': 'string', 'enum': ['person', 'team', 'organization']},
                   'name': {'type': 'string'}})
    fact = obj({'statement': {'type': 'string'}, 'source_unit_ids': array(unit),
                'central_subjects': array(subject), 'episode_family': {'type': 'string', 'enum': FAMILIES},
                'development_tags': array({'type': 'string'}), 'specific_event_tags': array({'type': 'string'})})
    return obj({'coverage_complete': {'type': 'boolean'}, 'article_kind': {'type': 'string', 'enum': KINDS},
                'context_tags': array({'type': 'string'}), 'quoted_speakers': array({'type': 'string'}), 'facts': array(fact)})


def validate_extraction(raw, payload):
    errors = []
    properties = extraction_schema(payload)['properties']
    if not isinstance(raw, Mapping) or set(raw) != set(properties):
        return None, [{'family': 'fact_card_shape', 'detail': 'exact_extraction_object_required'}], []
    units = {r['unit_id']: r['text'] for r in payload['source_units']}
    if raw.get('coverage_complete') is not True or raw.get('article_kind') not in KINDS:
        errors.append({'family': 'fact_card_coverage', 'detail': 'complete_source_and_kind_required'})
    if not strings(raw.get('context_tags')) or not strings(raw.get('quoted_speakers')):
        errors.append({'family': 'fact_card_shape', 'detail': 'invalid_context_lists'})
    facts = raw.get('facts')
    if not isinstance(facts, list) or not 1 <= len(facts) <= 128:
        return None, errors + [{'family': 'fact_card_coverage', 'detail': 'bounded_nonempty_facts_required'}], []
    expected = set(properties['facts']['items']['properties'])
    for fact in facts:
        if not isinstance(fact, Mapping) or set(fact) != expected:
            errors.append({'family': 'fact_card_shape', 'detail': 'invalid_fact'}); continue
        support = fact.get('source_unit_ids')
        if not strings(support) or not support or any(u not in units for u in support):
            errors.append({'family': 'fact_card_binding', 'detail': 'source_units_must_belong_to_article'})
        if not text(fact.get('statement')) or fact.get('episode_family') not in FAMILIES:
            errors.append({'family': 'fact_card_shape', 'detail': 'invalid_statement_or_family'})
        if not strings(fact.get('development_tags')) or not strings(fact.get('specific_event_tags')):
            errors.append({'family': 'fact_card_shape', 'detail': 'invalid_fact_tags'})
        subjects = fact.get('central_subjects')
        if not isinstance(subjects, list) or len(subjects) > 32 or any(
                not isinstance(s, Mapping) or set(s) != {'kind', 'name'} or
                s.get('kind') not in {'person', 'team', 'organization'} or not text(s.get('name'), 150)
                for s in subjects):
            errors.append({'family': 'fact_card_shape', 'detail': 'invalid_subjects'})
    return (None if errors else copy.deepcopy(dict(raw))), errors, []


def bind_extraction(raw, payload, identity):
    units = {r['unit_id']: r['text'] for r in payload['source_units']}
    return {'article_id': identity, 'title': payload['title'], 'source_url': payload['source_url'],
            'article_kind': raw['article_kind'], 'context_tags': copy.deepcopy(raw['context_tags']),
            'quoted_speakers': copy.deepcopy(raw['quoted_speakers']),
            'facts': [{'fact_id': identity + '.k' + str(i + 1), 'article_id': identity,
                       **copy.deepcopy(f), 'support_sha256': digest(' '.join(units[u] for u in f['source_unit_ids']))}
                      for i, f in enumerate(raw['facts'])]}


def enrichment_input(payload, card):
    subjects = {}
    for f in card['facts']:
        for s in f['central_subjects']:
            key = (s['kind'], norm(s['name']))
            if key not in subjects:
                subjects[key] = {'subject_ref': 's' + str(len(subjects) + 1),
                                 'kind': s['kind'], 'source_name': s['name']}
    facts = [{'fact_ref': f['fact_id'], 'statement': f['statement'], 'source_unit_ids': f['source_unit_ids'],
              'subject_refs': [subjects[(s['kind'], norm(s['name']))]['subject_ref'] for s in f['central_subjects']],
              'original_episode_family': f['episode_family'], 'original_development_tags': f['development_tags'],
              'original_specific_event_tags': f['specific_event_tags']} for f in card['facts']]
    return {**copy.deepcopy(payload), 'subjects': list(subjects.values()), 'fixed_facts': facts}


def _legacy_enrichment_schema(payload):
    string = {'type': 'string'}
    unit = {'type': 'string', 'enum': [r['unit_id'] for r in payload['source_units']]}
    # No subject may exist (e.g. a data table). Empty enums are not valid provider schemas.
    subject_ref = {'type': 'string'}
    if payload['subjects']:
        subject_ref['enum'] = [s['subject_ref'] for s in payload['subjects']]
    entity = obj({'subject_ref': subject_ref, 'canonical_name': string, 'aliases': array(string),
                  'confidence': {'type': 'string', 'enum': ['certain', 'uncertain']},
                  'identity_basis': string, 'source_unit_ids': array(unit)})
    fact = obj({'fact_ref': {'type': 'string', 'enum': [f['fact_ref'] for f in payload['fixed_facts']]},
                'episode_facets': array({'type': 'string', 'enum': FACETS}), 'development_tags': array(string),
                'episode_tags': array(string), 'source_unit_ids': array(unit)})
    return obj({'coverage_complete': {'type': 'boolean'}, 'identities': array(entity), 'facts': array(fact)})


def enrichment_schema(payload):
    """Expose the existing local bounds; accepted factual content is unchanged."""
    schema = _legacy_enrichment_schema(payload)
    fields = schema['properties']
    for name in ('identities', 'facts'):
        fields[name]['maxItems'] = min(256, len(payload['subjects' if name == 'identities' else 'fixed_facts']))
        support = fields[name]['items']['properties']['source_unit_ids']
        support.update(minItems=1, maxItems=64)
        support['items'].update(minLength=1, maxLength=150)
    identity = fields['identities']['items']['properties']
    identity['canonical_name'] = {'type': 'string', 'minLength': 1, 'maxLength': 150}
    # The legacy schema shares string objects: copy before assigning distinct bounds.
    identity['identity_basis'] = {'type': 'string', 'minLength': 1, 'maxLength': 1500}
    identity['aliases'] = {'type': 'array', 'maxItems': 64,
                           'items': {'type': 'string', 'minLength': 1, 'maxLength': 150}}
    fact = fields['facts']['items']['properties']
    for name in ('episode_facets', 'development_tags', 'episode_tags'):
        fact[name]['maxItems'] = 64
        fact[name]['items'] = {**fact[name]['items'], 'minLength': 1, 'maxLength': 150,
            'description': 'A non-empty tag, at most 150 characters; use concise normalized English labels.'}
        fact[name]['description'] = ('At most 64 concise tags. Every tag must contain non-whitespace text '
                                     'and be at most 150 characters. Use an empty list if no tag applies.')
    return schema


def _tag_error(value, field, ref):
    """Bounded technical evidence only: never retain the rejected article text."""
    error = {'family': 'fact_card_shape', 'fields': [field], 'ref': ref}
    if not isinstance(value, list):
        return {**error, 'detail': 'tag_array_required'}
    if len(value) > 64:
        return {**error, 'detail': 'tag_array_too_large', 'actual': len(value), 'limit': 64}
    for index, tag in enumerate(value):
        evidence = {**error, 'index': index}
        if not isinstance(tag, str):
            return {**evidence, 'detail': 'tag_string_required'}
        if not tag.strip():
            return {**evidence, 'detail': 'tag_empty'}
        if len(tag.strip()) > 150:
            return {**evidence, 'detail': 'tag_too_long', 'actual': len(tag.strip()), 'limit': 150}
        if field == 'episode_facets' and tag not in FACETS:
            return {**evidence, 'detail': 'unknown_episode_facet'}
    return None


def validate_enrichment(raw, payload):
    errors = []
    schema = enrichment_schema(payload)
    if not isinstance(raw, Mapping) or set(raw) != set(schema['properties']):
        return None, [{'family': 'fact_card_shape', 'detail': 'exact_enrichment_object_required'}], []
    if raw.get('coverage_complete') is not True:
        errors.append({'family': 'fact_card_coverage', 'detail': 'complete_enrichment_required'})
    units = {r['unit_id'] for r in payload['source_units']}
    for field, ref, expected in (
            ('identities', 'subject_ref', {s['subject_ref'] for s in payload['subjects']}),
            ('facts', 'fact_ref', {f['fact_ref'] for f in payload['fixed_facts']})):
        rows = raw.get(field)
        if not isinstance(rows, list) or len(rows) > 256 or any(not isinstance(r, Mapping) for r in rows):
            errors.append({'family': 'fact_card_shape', 'detail': 'bounded_enrichment_rows_required'}); continue
        ids = [r.get(ref) for r in rows]
        if any(not isinstance(r, str) for r in ids) or len(ids) != len(set(ids)) or set(ids) != expected:
            errors.append({'family': 'fact_card_binding', 'detail': 'exact_owned_enrichment_refs_required'})
        fields = set(schema['properties'][field]['items']['properties'])
        for r in rows:
            support = r.get('source_unit_ids')
            if set(r) != fields or not strings(support) or not support or any(u not in units for u in support):
                errors.append({'family': 'fact_card_binding', 'detail': 'invalid_enrichment_source_binding'})
            if field == 'identities':
                if (not text(r.get('canonical_name'), 150) or not strings(r.get('aliases')) or
                        r.get('confidence') not in {'certain', 'uncertain'} or not text(r.get('identity_basis'))):
                    errors.append({'family': 'fact_card_shape', 'detail': 'invalid_identity'})
            else:
                for tag_field in ('episode_facets', 'development_tags', 'episode_tags'):
                    error = _tag_error(r.get(tag_field), tag_field, r.get(ref))
                    if error:
                        errors.append(error)
    return (None if errors else copy.deepcopy(dict(raw))), errors, []


def bind_enrichment(card, raw, payload, body):
    subjects = {s['subject_ref']: s for s in payload['subjects']}
    by_subject = {(subjects[r['subject_ref']]['kind'], norm(subjects[r['subject_ref']]['source_name'])): r
                  for r in raw['identities']}
    extra = {r['fact_ref']: r for r in raw['facts']}
    result = copy.deepcopy(card)
    result.update(contract_version=VERSION, source_body_sha256=digest(body), source_body_chars=len(body))
    for f in result['facts']:
        for s in f['central_subjects']:
            resolved = by_subject[(s['kind'], norm(s['name']))]
            original_name = norm(s['name']) or ('unresolved_' + digest(s['name'])[:16])
            labels = {original_name}
            if resolved['confidence'] == 'certain':
                labels.update(norm(n) for n in [resolved['canonical_name'], *resolved['aliases']])
            s.update(normalized_name=original_name, identity_labels=sorted(labels - {''}),
                     identity_confidence=resolved['confidence'] if norm(s['name']) else 'uncertain',
                     canonical_name=resolved['canonical_name'])
        tags = extra[f['fact_id']]
        f['episode_facets'] = sorted(set(tags['episode_facets']) - {'other'})
        f['retrieval_episode_tags'] = sorted({norm(t) for t in tags['episode_tags']})
        f['development_tags'] = sorted({norm(t) for t in f['development_tags'] + tags['development_tags']})
    result['card_sha256'] = digest(result)
    return result


class Cache:
    """Atomic bounded cache of source stages and individual pair decisions."""
    def __init__(self):
        self.error = None
        self.dirty = False
        try:
            self.entries = json.loads(CACHE_FILE.read_text(encoding='utf-8')) if CACHE_FILE.exists() else {'version': VERSION, 'entries': {}}
            if self.entries.get('version') != VERSION or not isinstance(self.entries.get('entries'), dict):
                raise ValueError('invalid_fact_cache')
            if any(not isinstance(v, dict) or not text(v.get('stored_at'), 100) or not isinstance(v.get('output'), dict)
                   for v in self.entries['entries'].values()):
                raise ValueError('invalid_fact_cache_entry')
        except (OSError, ValueError, AttributeError):
            self.entries = {'version': VERSION, 'entries': {}}
            self.error = 'fact_cache_unavailable'

    def get(self, key):
        return copy.deepcopy(self.entries['entries'].get(key, {}).get('output'))

    def put(self, key, output):
        if self.error:
            raise ValueError(self.error)
        if self.get(key) == output:
            return
        self.entries['entries'][key] = {'output': copy.deepcopy(output), 'stored_at': datetime.now(timezone.utc).isoformat()}
        self.dirty = True
        self.flush()

    def flush(self):
        if not self.dirty or self.error:
            return
        from agents.menzo_policy_v93_15 import write_json
        self.entries['entries'] = dict(sorted(self.entries['entries'].items(),
                                              key=lambda kv: kv[1]['stored_at'])[-MAX_ENTRIES:])
        try:
            write_json(CACHE_FILE, self.entries)
        except OSError:
            self.error = 'fact_cache_write_failed'
            raise
        self.dirty = False


def obtain(row, cache, run_once, call, model, *, max_input_bytes):
    """Return a source-bound card or a technical HOLD; at most one attempt per stage."""
    attempts, validations, request_ids = 0, [], []
    stats = {'extraction_cache_hit': False, 'enrichment_cache_hit': False}
    try:
        if cache.error:
            raise ValueError(cache.error)
        payload = source_input(row)
        for stage, path, schema_fn, validator in (
                ('editorial_fact_extraction', EXTRACTION_POLICY, extraction_schema, validate_extraction),
                ('editorial_fact_enrichment', ENRICHMENT_POLICY, enrichment_schema, validate_enrichment)):
            schema = schema_fn(payload)
            prompt = path.read_text() + '\nReturn only JSON. INPUT=' + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if len(prompt.encode()) > max_input_bytes:
                raise ValueError('fact_card_input_limit')
            fingerprint = digest({'stage': stage, 'model': model, 'prompt': prompt, 'schema': schema, 'version': VERSION})
            raw = cache.get(fingerprint)
            if raw is None and stage == 'editorial_fact_enrichment':
                # Bounds do not change local acceptance. Revalidate old successes and
                # preserve their provenance/card hashes, avoiding a history-wide replay.
                legacy_fingerprint = digest({'stage': stage, 'model': model, 'prompt': prompt,
                    'schema': _legacy_enrichment_schema(payload), 'version': VERSION})
                legacy = cache.get(legacy_fingerprint)
                if legacy is not None:
                    _, legacy_errors, _ = validator(legacy, payload)
                    if not legacy_errors:
                        raw, fingerprint = legacy, legacy_fingerprint
            cached = raw is not None
            if cached:
                output, failures, _ = validator(raw, payload)
                if failures:
                    raise ValueError('invalid_cached_fact_card')
            else:
                single = {'candidates': [row], 'authorized_relations': [],
                          '_admission_candidate_ids': [payload['source_url']], '_admission_history_ids': []}
                operation = run_once(single, call, prompt, schema, stage, path,
                                     lambda raw: validator(raw, payload), cache_success=True,
                                     policy_version=VERSION)
                attempts += operation.get('attempts', 0)
                validations += operation.get('validation_attempts', [])
                request_ids += operation.get('logical_request_ids', [operation.get('logical_request_id')])
                if operation['status'] != 'VALIDATED':
                    return None, {**operation, 'attempts': attempts, 'validation_attempts': validations,
                                  'logical_request_ids': request_ids, **stats}
                output = operation['output']
                cache.put(fingerprint, output)
            stats['extraction_cache_hit' if stage == 'editorial_fact_extraction' else 'enrichment_cache_hit'] = cached
            if stage == 'editorial_fact_extraction':
                identity = 'f' + digest({'url': payload['source_url'], 'extraction': fingerprint})[:24]
                card = bind_extraction(output, payload, identity)
                payload = enrichment_input(payload, card)
            else:
                complete = bind_enrichment(card, output, payload, row['retained_body'])
                complete['provenance'] = {'model_requested': model,
                    'extraction_policy_sha256': digest(EXTRACTION_POLICY.read_text()),
                    'enrichment_policy_sha256': digest(ENRICHMENT_POLICY.read_text()),
                    'enrichment_request_fingerprint': fingerprint}
                complete['card_sha256'] = digest({k: v for k, v in complete.items() if k != 'card_sha256'})
                # Keep the complete source-bound card directly inspectable even if a
                # source-body cache entry later ages out. It grants no URL eligibility.
                cache.put('card:' + complete['card_sha256'], complete)
                return complete, {
                    'status': 'VALIDATED', 'attempts': attempts, 'validation_attempts': validations,
                    'logical_request_ids': request_ids, **stats}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, {'status': 'TECHNICAL_HOLD', 'attempts': attempts, 'validation_attempts': validations,
                      'logical_request_ids': request_ids, 'fallback_reason': str(exc)[:80],
                      'validation_errors': [{'family': 'fact_card_unavailable', 'detail': type(exc).__name__}], **stats}
