from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.alfred import normalize_placeholders, normalize_quote_paragraphs, apply_style_normalizations, run_alfred as base_run_alfred
from agents.gemini_ledger import record_gemini_event

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
ALFRED_REVIEW_FILE = NEWSROOM_STATE_DIR / "alfred_review_latest.json"
ARTIFACT_ALFRED_FILE = ARTIFACT_DIR / "alfred_review.json"

VERSION = "v95.3_alfred_quote_resolver_with_normalized_learned_history"
QUOTE_RESOLVER_HISTORY_FILE = NEWSROOM_STATE_DIR / "alfred_quote_resolver_history.json"
ALFRED_QUOTE_RESOLVER_MODEL_CHAIN = [m.strip() for m in os.getenv("ALFRED_QUOTE_RESOLVER_MODEL_CHAIN", "gemini-2.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]
QUOTE_RESOLVER_ALLOWED_KINDS = {"nickname_or_catchphrase", "ring_name", "stable_name", "move_name", "event_name", "title_or_branding"}
MAX_QUOTE_RESOLVER_CALLS_PER_ARTICLE = 3

TRANSLATION_GUARDRAIL_PATTERNS = [
    (re.compile(r"\b(partita|partite|gara|gare|gioco|giochi)\b", re.I), "possible_match_mistranslation", "Nel contesto wrestling 'match' non deve diventare partita/gara/gioco."),
    (re.compile(r"\b(rilascio|rilasciato|rilasciata|rilasciati|rilasciate)\b", re.I), "possible_release_mistranslation", "release/released non deve diventare rilascio/rilasciato: usare licenziamento, licenziato/licenziata, addio o uscita secondo contesto."),
    (re.compile(r"\b(pensione|pensionamento|pensionarsi|pensionato|pensionata)\b", re.I), "possible_retirement_mistranslation", "retirement nel wrestling va reso come ritiro/ritirarsi, non pensione/pensionamento."),
    (re.compile(r"\b(non\s+)?pulit[oaie]\b", re.I), "possible_cleared_mistranslation", "cleared/not cleared va reso come autorizzato/non autorizzato a lottare, non pulito/non pulito."),
    (re.compile(r"\bha\s+collegato\b|\bsi\s+è\s+collegat[oaie]\b|\bsi\s+e\s+collegat[oaie]\b", re.I), "literal_connected_calque", "connected with una mossa non va reso come collegato: usare ha colpito con / ha messo a segno."),
    (re.compile(r"\bla\s+marea\s+(?:è|e)\s+cambiat[ao]\b", re.I), "literal_tide_turned_calque", "tide turned va reso come l'inerzia del match e' cambiata."),
    (re.compile(r"\bben\s+collegat[oaie]\s+nel\s+backstage\b", re.I), "literal_well_connected_calque", "well-connected backstage va reso come ben introdotto nel backstage / con agganci nel backstage."),
    (re.compile(r"\buna\s+promo\b", re.I), "promo_gender_warning", "Promo in italiano wrestling e' maschile: un promo."),
    (re.compile(r"\b(gli|degli)\s+chop\b", re.I), "chop_gender_warning", "Chop in italiano wrestling e' femminile: le chop / delle chop."),
    (re.compile(r"\b(rivelatrice|prevalenza|coinvolto\s+in\s+una\s+dinamica|all'interno\s+della\s+compagnia|televisione\s+nazionale)\b", re.I), "ai_style_or_literalism_warning", "Formula innaturale o troppo da traduzione letterale/AI."),
]

PROTECTED_TITLE_MISTRANSLATION_PATTERNS = [
    (re.compile(r"\b(titolo|campionato)\s+mondiale\s+dei\s+pesi\s+massimi\b", re.I), "official_title_translated", "World Heavyweight Championship non va tradotto."),
    (re.compile(r"\b(titolo|campionato)\s+intercontinentale\b", re.I), "official_title_translated", "Intercontinental Championship non va tradotto."),
    (re.compile(r"\b(titolo|campionato)\s+degli\s+stati\s+uniti\b", re.I), "official_title_translated", "United States Championship non va tradotto."),
    (re.compile(r"\b(titolo|campionato)\s+knockouts\b", re.I), "official_title_translated", "TNA Knockouts Title / TNA Knockouts World Championship non va tradotto."),
    (re.compile(r"\b(match\s+con\s+scala|match\s+scala)\b", re.I), "official_match_type_translated", "Ladder Match non va tradotto."),
    (re.compile(r"\b(match\s+in\s+gabbia|gabbia\s+d'acciaio)\b", re.I), "official_match_type_translated", "Steel Cage Match / Steel Cage non va tradotto se e' nome stipulazione."),
    (re.compile(r"\bultimo\s+uomo\s+in\s+piedi\b", re.I), "official_match_type_translated", "Last Man Standing Match non va tradotto."),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def normalize_quote_expression(value: str) -> str:
    text = html.unescape(str(value or "")).strip()
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = re.sub(r'^[\s"“”\'«»]+|[\s"“”\'«»]+$', "", text)
    text = re.sub(r"[‐‑‒–—-]+", " ", text)
    text = re.sub(r"[\s.!?,;:…]+$", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_aliases(normalized: str) -> list[str]:
    aliases = [normalized, normalized[4:] if normalized.startswith("the ") else f"the {normalized}"]
    return [a for i, a in enumerate(aliases) if a and a not in aliases[:i]]


def canonical_quote_key(value: str) -> str:
    normalized = normalize_quote_expression(value)
    return normalized[4:] if normalized.startswith("the ") else normalized


def is_clearly_narrative_quote(expression: str) -> bool:
    normalized = normalize_quote_expression(expression)
    words = re.findall(r"[a-z']+", normalized)
    if len(words) >= 7:
        return True
    return any(re.search(pattern, normalized) for pattern in [
        r"\b(i|he|she|they|we|you)\s+(am|are|is|was|were|will|would|said|never|wanted|want|think|thought|feel|felt|prove|explain)\b",
        r"\b(this|that|it)\s+(was|is|will|would)\b",
        r"\b(wanted|ready|return|leave|explain|prove)\b",
    ])


def is_short_ambiguous_quote(expression: str) -> bool:
    return 1 <= len(re.findall(r"[a-z0-9']+", normalize_quote_expression(expression))) <= 6 and not is_clearly_narrative_quote(expression)


def load_quote_history() -> dict[str, Any]:
    data = load_json(QUOTE_RESOLVER_HISTORY_FILE, {})
    data.setdefault("version", "v95.3")
    data.setdefault("entries", {})
    data.setdefault("aliases", {})
    return data


def save_quote_history(data: dict[str, Any]) -> None:
    write_json(QUOTE_RESOLVER_HISTORY_FILE, data)


def history_lookup(history: dict[str, Any], expression: str) -> tuple[str | None, dict[str, Any] | None]:
    entries = history.get("entries") if isinstance(history.get("entries"), dict) else {}
    aliases = history.get("aliases") if isinstance(history.get("aliases"), dict) else {}
    for alias in quote_aliases(normalize_quote_expression(expression)) + [canonical_quote_key(expression)]:
        canonical = aliases.get(alias) or (alias if alias in entries else None)
        if canonical and isinstance(entries.get(canonical), dict):
            return str(canonical), entries[canonical]
    return None, None


def update_quote_history(history: dict[str, Any], decision: dict[str, Any], *, expression: str, article_context: dict[str, Any] | None, model: str | None) -> None:
    now = utc_now()
    canonical = canonical_quote_key(str(decision.get("canonical") or expression))
    variants = [normalize_quote_expression(str(v)) for v in decision.get("variants", []) if normalize_quote_expression(str(v))]
    for alias in quote_aliases(normalize_quote_expression(expression)) + quote_aliases(canonical):
        if alias not in variants:
            variants.append(alias)
    current = history.setdefault("entries", {}).get(canonical, {})
    ctx = article_context or {}
    examples = current.get("examples") if isinstance(current.get("examples"), list) else []
    example = {"title": ctx.get("title") or ctx.get("title_it") or ctx.get("source_title"), "url": ctx.get("url") or ctx.get("source_url")}
    if (example.get("title") or example.get("url")) and example not in examples:
        examples = (examples + [example])[-5:]
    history["entries"][canonical] = {
        **current,
        "allow": bool(decision.get("allow")),
        "kind": str(decision.get("kind") or "uncertain"),
        "canonical": canonical,
        "variants": sorted(set(variants)),
        "first_seen": current.get("first_seen") or now,
        "last_seen": now,
        "hits": int(current.get("hits", 0) or 0) + 1,
        "model": model,
        "reason": str(decision.get("reason") or "")[:300],
        "examples": examples,
    }
    for alias in history["entries"][canonical]["variants"]:
        history.setdefault("aliases", {})[alias] = canonical


def build_quote_resolver_prompt(expression: str, article_context: dict[str, Any] | None) -> str:
    ctx = article_context or {}
    context = clean_text(str(ctx.get("context") or ctx.get("body_html") or ""))[:700]
    return f"""You are checking a possible untranslated English expression in an Italian professional wrestling news article.

Expression:
"{expression}"

Article title:
"{ctx.get('title') or ctx.get('title_it') or ctx.get('source_title') or ''}"

Source/context:
"{context}"

Question:
In professional wrestling context, is this expression likely a nickname, catchphrase, ring name, stable name, move name, event name, title, or brand phrase that can reasonably remain in English in an Italian article?

Answer only strict JSON:
{{"allow": true, "kind": "nickname_or_catchphrase|ring_name|stable_name|move_name|event_name|title_or_branding|ordinary_untranslated_sentence|uncertain", "canonical": "lowercase canonical expression", "variants": ["variant 1", "variant 2"], "reason": "short reason"}}"""


def call_quote_resolver_gemini(prompt: str, *, article_context: dict[str, Any] | None = None, expression: str = "", canonical: str = "") -> tuple[dict[str, Any] | None, str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = ALFRED_QUOTE_RESOLVER_MODEL_CHAIN[0] if ALFRED_QUOTE_RESOLVER_MODEL_CHAIN else "missing_model"
    if not api_key:
        return None, model, "missing_api_key"
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        last_error = ""
        for model in ALFRED_QUOTE_RESOLVER_MODEL_CHAIN:
            try:
                text = (getattr(client.models.generate_content(model=model, contents=prompt), "text", "") or "").strip()
                data = json.loads(text)
                if isinstance(data, dict):
                    return data, model, "called"
                last_error = "json_not_object"
            except Exception as exc:
                last_error = str(exc)[:500]
        return None, model, last_error or "failed"
    except Exception as exc:
        return None, model, f"genai_import_or_client_error: {exc}"


def resolve_possible_untranslated_quote(expression: str, article_context: dict[str, Any] | None = None, *, history: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_quote_expression(expression)
    canonical = canonical_quote_key(expression)
    ctx = article_context or {}
    ledger_context = {"title": ctx.get("title") or ctx.get("title_it") or ctx.get("source_title"), "url": ctx.get("url") or ctx.get("source_url"), "expression": expression, "canonical": canonical}
    if not is_short_ambiguous_quote(expression):
        return {"allow": False, "kind": "ordinary_untranslated_sentence", "canonical": canonical, "variants": quote_aliases(normalized), "source": "deterministic_skip", "reason": "Long or narrative English quote; keep untranslated_quote blocker."}
    history = history if history is not None else load_quote_history()
    hit_key, hit = history_lookup(history, expression)
    if hit:
        hit["last_seen"] = utc_now()
        hit["hits"] = int(hit.get("hits", 0) or 0) + 1
        save_quote_history(history)
        allow = bool(hit.get("allow")) and str(hit.get("kind")) in QUOTE_RESOLVER_ALLOWED_KINDS
        record_gemini_event(agent="Alfred", phase="quote_ambiguity_resolver", model=hit.get("model"), status="avoided", reason="history_hit_allow" if allow else "history_hit_block", result="allow" if allow else "block", saved_gemini_call=True, **ledger_context)
        return {"allow": allow, "kind": hit.get("kind"), "canonical": hit_key or canonical, "variants": hit.get("variants", []), "source": "history_hit", "reason": hit.get("reason", "")}
    data, model, status = call_quote_resolver_gemini(build_quote_resolver_prompt(expression, ctx), article_context=ctx, expression=expression, canonical=canonical)
    if not isinstance(data, dict) or "allow" not in data:
        record_gemini_event(agent="Alfred", phase="quote_ambiguity_resolver", model=model, status="failed", reason="possible_untranslated_quote_ambiguity", result="json_error" if status != "missing_api_key" else "missing_api_key", saved_gemini_call=False, **ledger_context)
        return {"allow": False, "kind": "uncertain", "canonical": canonical, "variants": quote_aliases(normalized), "source": "error", "reason": status or "invalid_json"}
    kind = str(data.get("kind") or "uncertain")
    malformed_allow = not isinstance(data.get("allow"), bool)
    allow = data.get("allow") is True and kind in QUOTE_RESOLVER_ALLOWED_KINDS
    decision = {"allow": allow, "kind": kind, "canonical": data.get("canonical") or canonical, "variants": data.get("variants") if isinstance(data.get("variants"), list) else [], "reason": str(data.get("reason") or "")[:300]}
    update_quote_history(history, decision, expression=expression, article_context=ctx, model=model)
    save_quote_history(history)
    record_gemini_event(agent="Alfred", phase="quote_ambiguity_resolver", model=model, status="called", reason="possible_untranslated_quote_ambiguity", result="allow" if allow else ("malformed_allow" if malformed_allow else ("uncertain" if kind == "uncertain" else "block")), saved_gemini_call=False, **ledger_context)
    return {**decision, "allow": allow, "canonical": canonical_quote_key(str(decision.get("canonical") or canonical)), "source": "gemini"}


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or ""))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(value)).strip()


def bob_by_url(bob_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        source_key(article.get("source_url") or ""): article
        for article in bob_result.get("articles", [])
        if isinstance(article, dict)
    }


def expected_tables_from_bob(article: dict[str, Any] | None) -> bool:
    if not isinstance(article, dict):
        return False
    brief = article.get("bob_brief") if isinstance(article.get("bob_brief"), dict) else {}
    diagnostics = article.get("extraction_diagnostics") if isinstance(article.get("extraction_diagnostics"), dict) else {}
    element_counts = article.get("element_counts") if isinstance(article.get("element_counts"), dict) else {}
    if brief.get("expected_tables") is True:
        return True
    if int(diagnostics.get("table_count", 0) or 0) > 0:
        return True
    if int(element_counts.get("table", 0) or 0) > 0:
        return True
    return False


def translation_guardrail_warnings(review: dict[str, Any], article: dict[str, Any] | None) -> list[dict[str, str]]:
    text_parts = [str(review.get("title_it") or "")]
    if isinstance(review.get("approved_article"), dict):
        text_parts.append(str(review["approved_article"].get("body_html") or ""))
    if isinstance(article, dict):
        text_parts.append(str(article.get("body_html") or ""))
    plain = clean_text(" ".join(text_parts))
    if not plain:
        return []
    warnings: list[dict[str, str]] = []
    for pattern, code, message in TRANSLATION_GUARDRAIL_PATTERNS + PROTECTED_TITLE_MISTRANSLATION_PATTERNS:
        match = pattern.search(plain)
        if match:
            warnings.append({
                "code": code,
                "severity": "warning",
                "message": message,
                "evidence": match.group(0)[:300],
            })
    # Deduplicate warnings by code+evidence, preserving order.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for warning in warnings:
        key = (warning.get("code", ""), warning.get("evidence", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped[:8]


def _approved_article_from_source(review: dict[str, Any], article: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(article, dict):
        return None
    body_html, _ = normalize_placeholders(str(article.get("body_html") or ""))
    body_html, _ = normalize_quote_paragraphs(body_html)
    body_html, _ = apply_style_normalizations(body_html)
    element_counts = article.get("element_counts", {}) if isinstance(article.get("element_counts"), dict) else {}
    return {
        "source_url": article.get("source_url"),
        "source_title": article.get("source_title"),
        "title_it": review.get("title_it") or article.get("title_it"),
        "body_html": body_html,
        "excerpt_it": article.get("excerpt_it"),
        "category_hint": article.get("category_hint"),
        "source": article.get("source"),
        "meta": article.get("meta"),
        "element_counts": element_counts,
        "bob_translation_model": article.get("translation_model"),
    }


def resolve_untranslated_quote_issues(review: dict[str, Any], article: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, int]]:
    stats = {"calls": 0, "history_hits": 0, "allowed": 0, "blocked": 0, "failed": 0}
    issues = list(review.get("issues") if isinstance(review.get("issues"), list) else [])
    if not any(isinstance(i, dict) and i.get("code") in {"untranslated_quote", "untranslated_quotes"} for i in issues):
        return review, stats
    history = load_quote_history()
    kept: list[Any] = []
    resolvers: list[dict[str, Any]] = []
    call_budget = MAX_QUOTE_RESOLVER_CALLS_PER_ARTICLE
    for item in issues:
        if not (isinstance(item, dict) and item.get("code") in {"untranslated_quote", "untranslated_quotes"}):
            kept.append(item)
            continue
        expression = str(item.get("evidence") or "")
        before_source = None
        if is_short_ambiguous_quote(expression):
            hit_key, hit = history_lookup(history, expression)
            before_source = "history_hit" if hit else None
            if not hit:
                if call_budget <= 0:
                    kept.append(item)
                    stats["blocked"] += 1
                    continue
                call_budget -= 1
                stats["calls"] += 1
        resolution = resolve_possible_untranslated_quote(expression, article or review, history=history)
        resolvers.append({"expression": expression, "canonical": resolution.get("canonical"), "allow": resolution.get("allow"), "source": resolution.get("source"), "reason": resolution.get("reason")})
        if resolution.get("source") == "history_hit" or before_source == "history_hit":
            stats["history_hits"] += 1
        if resolution.get("allow") is True:
            stats["allowed"] += 1
            continue
        if resolution.get("source") == "error":
            stats["failed"] += 1
        stats["blocked"] += 1
        kept.append(item)
    if resolvers:
        review = dict(review)
        review["issues"] = kept
        review.setdefault("editorial_changes", [])
        review["editorial_changes"].append({
            "code": "alfred_quote_resolver_v95_3",
            "severity": "info",
            "message": "Applicato resolver normalizzato per possibili quote/catchphrase wrestling.",
        })
        review.setdefault("diagnostics", {})["quote_resolver"] = resolvers
        blockers = [x for x in kept if isinstance(x, dict) and x.get("severity") == "blocker"]
        warnings = review.get("warnings") if isinstance(review.get("warnings"), list) else []
        if not blockers:
            approved_article = review.get("approved_article") or _approved_article_from_source(review, article)
            if approved_article:
                review["decision"] = "approved"
                review["approved_article"] = approved_article
            else:
                review["decision"] = "needs_revision"
                missing_issue = {
                    "code": "missing_approved_article_after_quote_resolver",
                    "severity": "blocker",
                    "message": "Quote resolver ha rimosso i blocker, ma Alfred non ha un approved_article da consegnare.",
                }
                kept.append(missing_issue)
                review["issues"] = kept
                blockers = [x for x in kept if isinstance(x, dict) and x.get("severity") == "blocker"]
        review["quality_score"] = max(0, min(100, 100 - 25 * len(blockers) - 5 * len(warnings)))
    return review, stats


def refine_review(review: dict[str, Any], article: dict[str, Any] | None) -> tuple[dict[str, Any], int, dict[str, int]]:
    if not isinstance(review, dict):
        return review, 0, {"calls": 0, "history_hits": 0, "allowed": 0, "blocked": 0, "failed": 0}
    review, resolver_stats = resolve_untranslated_quote_issues(review, article)
    warnings = review.get("warnings") if isinstance(review.get("warnings"), list) else []
    kept: list[Any] = []
    removed = 0
    for warning in warnings:
        if isinstance(warning, dict) and warning.get("code") == "possible_missing_table" and not expected_tables_from_bob(article):
            removed += 1
            continue
        kept.append(warning)
    new_translation_warnings = translation_guardrail_warnings(review, article)
    if removed or new_translation_warnings:
        review = dict(review)
        existing_keys = {
            (w.get("code", ""), w.get("evidence", ""))
            for w in kept
            if isinstance(w, dict)
        }
        for warning in new_translation_warnings:
            key = (warning.get("code", ""), warning.get("evidence", ""))
            if key not in existing_keys:
                kept.append(warning)
                existing_keys.add(key)
        review["warnings"] = kept
        review.setdefault("editorial_changes", [])
        if removed:
            review["editorial_changes"].append({
                "code": "false_table_warning_removed",
                "severity": "info",
                "message": "Rimosso warning tabella: nessun segnale reale da Bob o Menzo.",
            })
        if new_translation_warnings:
            review["editorial_changes"].append({
                "code": "translation_guardrails_checked_v94_14",
                "severity": "info",
                "message": "Applicato controllo leggero Alfred sui guardrail linguistici v94.14.",
            })
        blockers = [x for x in review.get("issues", []) if isinstance(x, dict) and x.get("severity") == "blocker"] if isinstance(review.get("issues"), list) else []
        review["quality_score"] = max(0, min(100, 100 - 25 * len(blockers) - 5 * len(kept)))
    return review, removed, resolver_stats


def run_alfred(bob_result: dict[str, Any] | None = None) -> dict[str, Any]:
    bob = bob_result if isinstance(bob_result, dict) else {}
    result = base_run_alfred(bob_result)
    articles = bob_by_url(bob)
    total_removed = 0
    quote_resolver_totals = {"calls": 0, "history_hits": 0, "allowed": 0, "blocked": 0, "failed": 0}
    refined_reviews: list[dict[str, Any]] = []
    for review in result.get("reviews", []) if isinstance(result.get("reviews"), list) else []:
        refined, removed, resolver_stats = refine_review(review, articles.get(source_key(review.get("source_url", ""))) if isinstance(review, dict) else None)
        total_removed += removed
        for key in quote_resolver_totals:
            quote_resolver_totals[key] += int(resolver_stats.get(key, 0) or 0)
        refined_reviews.append(refined)
    if refined_reviews:
        result["reviews"] = refined_reviews
    approved = []
    for review in result.get("reviews", []) if isinstance(result.get("reviews"), list) else []:
        if isinstance(review, dict) and review.get("decision") == "approved" and review.get("approved_article"):
            approved.append(review.get("approved_article"))
    result["approved_articles"] = approved
    result["version"] = VERSION
    result.setdefault("policy", {})["possible_missing_table_requires_real_table_signal"] = True
    result.setdefault("policy", {})["translation_guardrail_warnings_v94_14"] = True
    result.setdefault("policy", {})["alfred_quote_resolver_v95_3"] = True
    result.setdefault("postprocess", {})["false_table_warnings_removed"] = total_removed
    result.setdefault("postprocess", {})["translation_guardrail_warning_count"] = sum(
        1
        for r in result.get("reviews", [])
        if isinstance(r, dict)
        for w in r.get("warnings", [])
        if isinstance(w, dict) and str(w.get("code", "")).endswith(("mistranslation", "calque", "warning", "translated"))
    )
    result["postprocess"].update({
        "quote_resolver_calls": quote_resolver_totals["calls"],
        "quote_resolver_history_hits": quote_resolver_totals["history_hits"],
        "quote_resolver_allowed": quote_resolver_totals["allowed"],
        "quote_resolver_blocked": quote_resolver_totals["blocked"],
        "quote_resolver_failed": quote_resolver_totals["failed"],
    })
    if isinstance(result.get("handoff"), dict):
        result["handoff"]["warnings"] = sum(len(r.get("warnings", [])) for r in result.get("reviews", []) if isinstance(r, dict))
        result["handoff"]["approved"] = len(approved)
        result["handoff"]["needs_revision"] = sum(1 for r in result.get("reviews", []) if isinstance(r, dict) and r.get("decision") == "needs_revision")
        result["handoff"]["blockers"] = sum(len([i for i in r.get("issues", []) if isinstance(i, dict) and i.get("severity") == "blocker"]) for r in result.get("reviews", []) if isinstance(r, dict))
    write_json(ARTIFACT_ALFRED_FILE, result)
    write_json(ALFRED_REVIEW_FILE, result)
    print(f"[ALFRED v95.3] Quote resolver + translation guardrails | removed={total_removed} quote_allowed={quote_resolver_totals['allowed']}", flush=True)
    return result
