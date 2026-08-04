from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
VERSION = "v94_15_andrea_pre_bob_content_sufficiency_guard"
STATE_FILE = STATE_DIR / "andrea_pre_bob_latest.json"
ARTIFACT_FILE = ARTIFACT_DIR / "andrea_pre_bob_latest.json"

BOILERPLATE_PATTERNS = [
    re.compile(r"\b(subscribe|newsletter|follow us|share your thoughts|sound off|comments section|privacy policy)\b", re.I),
    re.compile(r"\b(add .* preferred source|google news|stay tuned)\b", re.I),
]
EXTRACTION_FAILURE_PATTERNS = [
    re.compile(r"\b(access denied|enable javascript|403 forbidden|not found|page unavailable)\b", re.I),
    re.compile(r"\b(cloudflare|checking your browser|captcha)\b", re.I),
]
QUOTE_HINT_PATTERNS = [re.compile(r"\b(said|told|stated|revealed|explained|interview|quote|comments?)\b", re.I)]
BREAKING_PATTERNS = [re.compile(r"\b(breaking|update|official|announced|announcement|confirmed)\b", re.I)]
MAJOR_HARD_NEWS_PATTERNS = [
    re.compile(r"\b(death|dead|dies|passed away|passes away)\b", re.I),
    re.compile(r"\b(arrest|arrested|lawsuit|sued|legal|charged|court)\b", re.I),
    re.compile(r"\b(major injury|injured|injury|surgery|hospital)\b", re.I),
    re.compile(r"\b(released|release|departure|departs|signing|signs|contract)\b", re.I),
    re.compile(r"\b(return|returns|returning|debut|debuts)\b", re.I),
    re.compile(r"\b(title change|new champion|wins .* championship|championship win)\b", re.I),
    re.compile(r"\b(post[- ]show|major angle|turns heel|turns face|attack angle)\b", re.I),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def text_from_candidate(candidate: dict[str, Any]) -> str:
    for key in ("body_text", "text", "extracted_text", "article_text", "content", "summary"):
        if clean_text(candidate.get(key)):
            return clean_text(candidate.get(key))
    blocks = candidate.get("ordered_blocks") or candidate.get("elements") or candidate.get("text_blocks") or []
    parts: list[str] = []
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict):
                parts.append(clean_text(block.get("text") or block.get("markdown") or block.get("content")))
            else:
                parts.append(clean_text(block))
    return clean_text("\n".join(p for p in parts if p))


def existing_blocks(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("ordered_blocks", "elements", "clean_elements", "blocks"):
        value = candidate.get(key)
        if isinstance(value, list) and value:
            return [x for x in value if isinstance(x, dict)]
    return []


def fetch_and_extract_if_needed(candidate: dict[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    text = text_from_candidate(candidate)
    blocks = existing_blocks(candidate)
    diagnostics: dict[str, Any] = {"andrea_fetch_performed": False, "bob_reuse_supported": False, "bob_may_reextract": False}
    if blocks or len(text) >= 500:
        diagnostics["source"] = "candidate_payload"
        return text, blocks, diagnostics
    url = str(candidate.get("url") or candidate.get("source_url") or "")
    if not url:
        return text, blocks, {"stage": "missing_url", "andrea_fetch_performed": False, "bob_reuse_supported": False, "bob_may_reextract": False}
    try:
        from agents.bob import extract_elements, fetch_html
        raw = fetch_html(url)
        _meta, _raw_elements, elements, _removed, diagnostics = extract_elements(url, raw)
        diagnostics.update({
            "andrea_fetch_performed": True,
            "andrea_extracted_reusable_elements": bool(elements),
            "bob_reuse_supported": False,
            "bob_may_reextract": True,
            "reuse_note": "Andrea reused Bob extraction helpers for pre-Bob metrics; current Bob article_package does not accept pre-extracted elements, so Bob may fetch/extract again for passed candidates.",
        })
        extracted = clean_text("\n".join(str(e.get("text") or e.get("markdown") or "") for e in elements if e.get("type") in {"text", "heading", "quote", "table"}))
        return extracted or text, elements, diagnostics
    except Exception as exc:
        return text, blocks, {"stage": "andrea_extract_error", "error": str(exc)[:500], "andrea_fetch_performed": True, "bob_reuse_supported": False, "bob_may_reextract": False}


def count_sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+\s+", text) if len(clean_text(s)) >= 20])


def pre_bob_content_sufficiency_check(candidate: dict[str, Any]) -> dict[str, Any]:
    text, blocks, diagnostics = fetch_and_extract_if_needed(candidate)
    block_texts = [clean_text(b.get("text") or b.get("markdown") or b.get("content")) for b in blocks if isinstance(b, dict)]
    meaningful_text_blocks = sum(1 for t in block_texts if len(t) >= 80)
    paragraph_count = sum(1 for t in block_texts if len(t) >= 40) or len([p for p in re.split(r"\n+", text) if len(clean_text(p)) >= 40])
    quote_count = sum(1 for b in blocks if b.get("type") == "quote")
    embed_count = sum(1 for b in blocks if b.get("type") == "embed")
    image_count = sum(1 for b in blocks if b.get("type") == "image")
    body_chars = len(text)
    body_words = len(re.findall(r"\b\w+\b", text))
    sentence_count = count_sentences(text)
    title_blob = clean_text(" ".join([candidate.get("title") or "", candidate.get("source_title") or "", candidate.get("summary") or "", text[:1200]]))
    has_only_image_or_embed = body_chars < 250 and (image_count + embed_count) > 0 and meaningful_text_blocks == 0
    has_extraction_failure_signals = any(p.search(title_blob) for p in EXTRACTION_FAILURE_PATTERNS) or diagnostics.get("stage") in {"andrea_extract_error", "missing_url"}
    has_source_boilerplate_only = body_chars < 700 and bool(text) and sum(1 for p in BOILERPLATE_PATTERNS if p.search(text)) >= 2
    is_quote_based_exception = quote_count >= 1 and body_chars >= 350 or (any(p.search(title_blob) for p in QUOTE_HINT_PATTERNS) and quote_count >= 1)
    is_breaking_exception = any(p.search(title_blob) for p in BREAKING_PATTERNS)
    is_major_hard_news_exception = any(p.search(title_blob) for p in MAJOR_HARD_NEWS_PATTERNS)
    exceptions = []
    if is_quote_based_exception:
        exceptions.append("quote_based_exception")
    if is_breaking_exception:
        exceptions.append("breaking_exception")
    if is_major_hard_news_exception:
        exceptions.append("major_hard_news_exception")
    hard_fail = body_chars < 250 and quote_count == 0 and embed_count == 0
    soft_signals = [body_chars < 500, meaningful_text_blocks < 2, paragraph_count < 2, sentence_count < 4, quote_count == 0, embed_count == 0, has_only_image_or_embed, has_extraction_failure_signals, has_source_boilerplate_only]
    soft_fail = sum(1 for x in soft_signals if x) >= 6 or (body_chars < 500 and meaningful_text_blocks < 2 and paragraph_count < 2 and sentence_count < 4 and quote_count == 0 and embed_count == 0)
    if exceptions and not (body_chars < 120 and quote_count == 0 and embed_count == 0):
        ok, decision, reason, saved = True, "passed_with_exception", "editorial_exception_prevents_false_block", False
    elif hard_fail or soft_fail:
        ok, decision, reason, saved = False, "blocked_before_bob", "pre_bob_content_insufficient", True
    else:
        ok, decision, reason, saved = True, "pass_to_bob", "sufficient_content", False
    return {"ok": ok, "decision": decision, "reason": reason, "body_chars": body_chars, "body_words": body_words, "meaningful_text_blocks": meaningful_text_blocks, "paragraph_count": paragraph_count, "sentence_count": sentence_count, "quote_count": quote_count, "embed_count": embed_count, "image_count": image_count, "has_only_image_or_embed": has_only_image_or_embed, "has_extraction_failure_signals": has_extraction_failure_signals, "has_source_boilerplate_only": has_source_boilerplate_only, "is_quote_based_exception": is_quote_based_exception, "is_breaking_exception": is_breaking_exception, "is_major_hard_news_exception": is_major_hard_news_exception, "exceptions": exceptions, "saved_gemini_call": saved, "andrea_fetch_performed": bool(diagnostics.get("andrea_fetch_performed")), "andrea_extracted_reusable_elements": bool(diagnostics.get("andrea_extracted_reusable_elements")), "bob_reuse_supported": bool(diagnostics.get("bob_reuse_supported")), "bob_may_reextract": bool(diagnostics.get("bob_may_reextract")), "reuse_note": diagnostics.get("reuse_note", ""), "source_title": candidate.get("source_title") or candidate.get("title"), "source_url": candidate.get("source_url") or candidate.get("url"), "menzo_score": candidate.get("score") or candidate.get("menzo_score"), "menzo_article_type": candidate.get("article_type") or candidate.get("category_hint"), "extraction_diagnostics": diagnostics}


def run_andrea(menzo_output: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = menzo_output.get("selected", []) if isinstance(menzo_output, dict) else []
    selected = selected if isinstance(selected, list) else []
    passed: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for candidate in selected:
        if not isinstance(candidate, dict):
            continue
        check = pre_bob_content_sufficiency_check(candidate)
        items.append(check)
        if check["ok"]:
            enriched = dict(candidate)
            enriched["andrea_pre_bob"] = {k: v for k, v in check.items() if k not in {"extraction_diagnostics"}}
            passed.append(enriched)
        else:
            print(f"[ANDREA v94.15] blocked_before_bob | reason={check['reason']} body_chars={check['body_chars']} text_blocks={check['meaningful_text_blocks']} paragraphs={check['paragraph_count']} sentences={check['sentence_count']} quotes={check['quote_count']} embeds={check['embed_count']} url={check.get('source_url')}", flush=True)
    exception_reason_counts: Counter[str] = Counter()
    for item in items:
        if item.get("decision") != "passed_with_exception":
            continue
        reasons = item.get("exceptions") if isinstance(item.get("exceptions"), list) else []
        exception_reason_counts.update(str(reason) for reason in reasons if str(reason).strip())
    summary = {"checked": len(items), "passed": len(passed), "blocked": sum(1 for x in items if not x.get("ok")), "passed_with_exception": sum(1 for x in items if x.get("decision") == "passed_with_exception"), "exception_reasons": dict(sorted(exception_reason_counts.items())), "saved_gemini_calls": sum(1 for x in items if x.get("saved_gemini_call")), "andrea_fetch_performed": sum(1 for x in items if x.get("andrea_fetch_performed")), "bob_may_reextract": sum(1 for x in items if x.get("bob_may_reextract"))}
    result = {"agent": "Andrea", "version": VERSION, "generated_at": utc_now(), "input": {"selected_count": len(selected), "menzo_version": menzo_output.get("version") if isinstance(menzo_output, dict) else None}, "summary": summary, "items": items, "handoff": {"to_bob": len(passed), "blocked_before_bob": summary["blocked"], "saved_gemini_calls": summary["saved_gemini_calls"]}}
    filtered = dict(menzo_output)
    filtered["selected"] = passed
    filtered["andrea"] = result
    filtered["handoff"] = dict(filtered.get("handoff") if isinstance(filtered.get("handoff"), dict) else {})
    filtered["handoff"].update({"to_bob_or_v92": len(passed), "andrea_checked": summary["checked"], "andrea_passed": summary["passed"], "andrea_blocked": summary["blocked"], "andrea_saved_gemini_calls": summary["saved_gemini_calls"], "andrea_passed_with_exception": summary["passed_with_exception"], "andrea_exception_reasons": summary["exception_reasons"], "andrea_fetch_performed": summary["andrea_fetch_performed"], "andrea_bob_may_reextract": summary["bob_may_reextract"], "andrea_block_reasons": sorted({x.get("reason") for x in items if not x.get("ok")})})
    result["menzo_handoff_to_bob"] = filtered["handoff"]
    write_json(ARTIFACT_FILE, result)
    write_json(STATE_FILE, result)
    print(f"[ANDREA v94.15] Pre-Bob content sufficiency guard | checked={summary['checked']} passed={summary['passed']} blocked={summary['blocked']} passed_with_exception={summary['passed_with_exception']} saved_gemini_calls={summary['saved_gemini_calls']} andrea_fetch_performed={summary['andrea_fetch_performed']} bob_may_reextract={summary['bob_may_reextract']}", flush=True)
    return filtered
