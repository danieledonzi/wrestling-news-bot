"""Measured card/pair coverage, separate from semantic correctness and final verdicts."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json

from agents.menzo_card_admission import VERSION
from agents.menzo_source_material import CONTRACT_VERSION


def identity(value):
    return isinstance(value, str) and bool(value)


def whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def stamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
    except (ValueError, TypeError):
        return None


def build(rows, since, until, *, readable=True):
    events, bad = [], 0
    kinds = {'editorial_admission_cycle', 'editorial_card_observation', 'editorial_pair_disposition',
             'editorial_candidate_inventory', 'editorial_candidate_inventory_cycle'}
    for row in rows:
        if row.get('agent') != 'Menzo' or row.get('event_type') not in kinds:
            continue
        at = stamp(row.get('timestamp_utc'))
        if not at or at > until:
            continue
        try:
            data = json.loads(row.get('result') or '')
            if not isinstance(data, dict) or data.get('input_contract') != CONTRACT_VERSION:
                raise ValueError('invalid_payload')
            if row['event_type'].startswith('editorial_candidate_inventory'):
                if not isinstance(data.get('inventory_id'), str): raise ValueError('missing_inventory_id')
            elif data.get('admission_contract') != VERSION or not isinstance(data.get('audit_observation_id'), str):
                raise ValueError('invalid_card_contract')
            kind = row['event_type']
            if kind == 'editorial_pair_disposition':
                if (not all(identity(data.get(k)) for k in ('pair_id','left_id','right_id','left_url','right_url','reason')) or
                        data.get('scope') not in ('same_run','recent_history') or
                        data.get('decision') not in ('EXCLUDED_HISTORY','ADMIT','NO_SUSPICION','TECHNICAL_HOLD') or
                        any(data.get(k) is not None and not identity(data[k]) for k in ('left_card_sha256','right_card_sha256'))):
                    raise ValueError('invalid_pair_disposition')
            elif kind == 'editorial_card_observation':
                if (not identity(data.get('url')) or not identity(data.get('endpoint_id')) or
                        data.get('scope') not in ('current','history') or data.get('status') not in ('READY','TECHNICAL_HOLD') or
                        (data['status']=='READY' and (not identity(data.get('card_sha256')) or not whole(data.get('fact_count'))))):
                    raise ValueError('invalid_card_observation')
            elif kind == 'editorial_candidate_inventory':
                if (not identity(data.get('candidate_id')) or not identity(data.get('url')) or
                        data.get('disposition') not in ('TERMINAL_SKIP','EXACT_DUPLICATE','TECHNICAL_HOLD','CLASSIFIED','UNRESOLVED') or
                        data.get('first_class') not in (None,'MUST_PUBLISH','SHOULD_PUBLISH','PUBLISHABLE_SOFT','SKIP')):
                    raise ValueError('invalid_candidate_inventory')
            elif row.get('status') != 'started':
                expected = ('candidate_count',) if kind == 'editorial_candidate_inventory_cycle' else ('pair_universe','card_observations')
                if any(not whole(data.get(k)) for k in expected):
                    raise ValueError('invalid_cycle_counts')
            events.append({'event_type': row['event_type'], 'status': row.get('status'),
                           'at': at.isoformat(), 'run_id': row.get('run_id'), **data})
        except (ValueError, TypeError):
            if at >= since: bad += 1
    starts = [e for e in events if e['event_type'] == 'editorial_admission_cycle' and e['status'] == 'started']
    cutover = min((stamp(e['at']) for e in starts), default=None)
    window = [e for e in events if stamp(e['at']) >= since]
    pairs = [e for e in window if e['event_type'] == 'editorial_pair_disposition']
    cards = [e for e in window if e['event_type'] == 'editorial_card_observation']
    inventory = [e for e in window if e['event_type'] == 'editorial_candidate_inventory']
    sessions = defaultdict(list)
    for e in events:
        sessions[e.get('audit_observation_id') or e.get('inventory_id')].append(e)
    incomplete = []
    for ident, rs in sessions.items():
        if not any(stamp(e['at']) >= since for e in rs):
            continue
        inventory_cycle = any(e['event_type'] == 'editorial_candidate_inventory_cycle' for e in rs)
        cycle_kind = 'editorial_candidate_inventory_cycle' if inventory_cycle else 'editorial_admission_cycle'
        end = [e for e in rs if e['event_type'] == cycle_kind and e['status'] != 'started']
        start = [e for e in rs if e['event_type'] == cycle_kind and e['status'] == 'started']
        if len(end) != 1 or len(start) != 1:
            incomplete.append(ident); continue
        if inventory_cycle:
            seen = [e for e in rs if e['event_type'] == 'editorial_candidate_inventory']
            if (end[0].get('candidate_count') != len(seen) or len({e.get('candidate_id') for e in seen}) != len(seen)):
                incomplete.append(ident)
        else:
            ps = [e for e in rs if e['event_type'] == 'editorial_pair_disposition']
            cs = [e for e in rs if e['event_type'] == 'editorial_card_observation']
            if (end[0].get('pair_universe') != len(ps) or len({e.get('pair_id') for e in ps}) != len(ps) or
                    end[0].get('card_observations') != len(cs)):
                incomplete.append(ident)
    dispositions = {'EXCLUDED_HISTORY', 'ADMIT', 'NO_SUSPICION', 'TECHNICAL_HOLD'}
    bad += sum(e.get('decision') not in dispositions or not e.get('pair_id') or not e.get('reason') for e in pairs)
    bad += sum(e.get('status') not in {'READY', 'TECHNICAL_HOLD'} or not e.get('url') or
               (e.get('status') == 'READY' and (not e.get('card_sha256') or not isinstance(e.get('fact_count'), int))) for e in cards)
    coverage = ('unavailable' if not readable or bad or incomplete or cutover is None else
                'full' if cutover <= since else 'partial')
    observed = {'card_observations': len(cards), 'unique_source_urls': len({e['url'] for e in cards}),
                'ready_card_observations': sum(e.get('status') == 'READY' for e in cards),
                'card_hold_observations': sum(e.get('status') == 'TECHNICAL_HOLD' for e in cards),
                'extraction_cache_hits': sum(bool(e.get('extraction_cache_hit')) for e in cards),
                'enrichment_cache_hits': sum(bool(e.get('enrichment_cache_hit')) for e in cards),
                'pair_disposition_observations': len(pairs),
                'unique_pair_materials_observed': len({(e['pair_id'], e.get('left_card_sha256'), e.get('right_card_sha256')) for e in pairs}),
                'pair_decisions': dict(Counter(e['decision'] for e in pairs)),
                'pair_decision_cache_hits': sum(bool(e.get('cache_hit')) for e in pairs),
                'history_exclusion_reasons': dict(Counter(e['reason'] for e in pairs if e['decision'] == 'EXCLUDED_HISTORY')),
                'inventory_observations': len(inventory), 'inventory_unique_urls': len({e.get('url') for e in inventory}),
                'inventory_dispositions': dict(Counter(e.get('disposition') for e in inventory))}
    return {'contract_version': VERSION, 'coverage': coverage, 'cutover_at': cutover.isoformat() if cutover else None,
            'observed': observed, 'window_metrics': observed if coverage == 'full' else None,
            'incomplete_cycles': incomplete, 'invalid_payloads': bad, 'cards': cards,
            'pair_dispositions': pairs, 'inventory': inventory,
            'interpretation': ['Inventario limitato agli URL catturati dalla newsroom, non un totale RSS inventato.',
                'EXCLUDED_HISTORY è un filtro di reperimento, non un verdetto Gemini NO_MATCH.',
                'NO_SUSPICION è ammissione negativa; NO_MATCH è un giudizio duplicate completo.',
                'Conteggi di osservazioni, URL unici, materiali e decisioni finali hanno denominatori distinti.',
                'Copertura completa certifica la rendicontazione, non la correttezza semantica.',
                'HOLD e dati mancanti non sono SKIP né valori zero.']}
