from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import agents.bob as bob_base
from agents.bob import run_bob as base_run_bob

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"
ARTIFACT_BOB_FILE = ARTIFACT_DIR / "bob_articles.json"

VERSION = "v94_14_translation_guardrails_from_v92"

TRANSLATION_STYLE_GUARDRAILS_V94_14 = """
GUARDRAIL LINGUISTICI OBBLIGATORI v94.14:
- Scrivi come una news wrestling italiana reale: diretto, concreto, asciutto. Evita tono AI, formule enfatiche, chiusure speculative e frasi di riempimento.
- Non tradurre mai i nomi ufficiali di titoli/cinture: World Heavyweight Championship, Intercontinental Championship, United States Championship, WWE Championship, WWE Women's Championship, Women's World Championship, NXT Championship, AEW World Championship, AEW World Tag Team Championship, TNA Knockouts Title, TNA Knockouts World Championship, AAA Mega Championship, Money in the Bank.
- Non tradurre mai i nomi ufficiali di stipulazioni/match type: Last Man Standing Match, Last Woman Standing Match, WarGames Match, Royal Rumble Match, Hell in a Cell Match, Steel Cage Match, Ladder Match, Street Fight, No Disqualification Match, Triple Threat Match, Fatal 4-Way Match, 6-Man Tag Team Match, 8-Woman Tag Team Match, title match.
- Nel wrestling italiano, match resta match: mai partita, gara o gioco. Promo e' maschile: un promo. Chop e' femminile: le chop, delle chop.
- Mantieni normalmente in inglese: promo, segment, storyline, push, turn, feud, stable, heel, face, main event, main eventer, tag team.
- Le mosse riconoscibili restano in inglese, ma la frase deve essere italiana naturale: connected with a Spear -> ha colpito con una Spear / ha messo a segno una Spear; connected a flurry -> ha messo a segno una raffica; tide turned -> l'inerzia del match e' cambiata; well-connected backstage -> ben introdotto nel backstage / con agganci nel backstage.
- release/released/roster cuts -> licenziamento, licenziato/licenziata, addio o uscita secondo contesto; mai rilascio/rilasciato. retirement -> ritiro/ritirarsi; mai pensione/pensionamento. cleared/not cleared -> autorizzato/non autorizzato a lottare; mai pulito/non pulito.
- Evita calchi e parole innaturali: si e' aperto riguardo, ha affrontato una sfida, coinvolto in una dinamica, all'interno della compagnia, televisione nazionale, rivelatrice, prevalenza, stella se il senso e' wrestler/fighter/top name.
- Se non sei sicuro su un nome proprio, titolo, show, stable, evento, cintura, stipulazione, numero, data o sigla, copialo esattamente dal sorgente.
""".strip()

_ORIGINAL_BUILD_TRANSLATION_PROMPT = bob_base.build_translation_prompt


def build_translation_prompt_with_v94_14_guardrails(item: dict[str, Any], meta: dict[str, str], units: list[dict[str, str]]) -> str:
    prompt = _ORIGINAL_BUILD_TRANSLATION_PROMPT(item, meta, units)
    marker = "Forma richiesta:"
    if marker in prompt:
        return prompt.replace(marker, f"{TRANSLATION_STYLE_GUARDRAILS_V94_14}\n\n{marker}", 1)
    return f"{prompt.rstrip()}\n\n{TRANSLATION_STYLE_GUARDRAILS_V94_14}\n"


bob_base.build_translation_prompt = build_translation_prompt_with_v94_14_guardrails

RESIDUAL_BIO_PATTERNS = [
    # Known Ringside boilerplate authors.
    re.compile(r"\b(felix\s+upton|steve\s+carrier|derek\s+holloway|steve\s+malone|aaron\s+varble)\b.*\b(ringside\s+news|esperienza|fondatore|giornalismo|wrestling|autore|notizie|indiscrezioni|risultati)\b", re.I),
    # Generic Ringside News author bio patterns, independent from author name.
    re.compile(r"\b[\wÀ-ÿ'’.-]+(?:\s+[\wÀ-ÿ'’.-]+){0,3}\s+è\s+un(?:a)?\s+(?:autore|autrice|giornalista|redattore|redattrice|writer|contributor|collaboratore|collaboratrice)\s+di\s+ringside\s+news\b", re.I),
    re.compile(r"\b(?:autore|autrice|giornalista|redattore|redattrice|writer|contributor|collaboratore|collaboratrice)\s+di\s+ringside\s+news\b", re.I),
    re.compile(r"\b(?:specializzato|specializzata|specialist|specializes?)\s+(?:in|nel|nella|nelle)\s+(?:notizie|news|indiscrezioni|rumor|risultati|copertura|wrestling)\b.*\b(ringside\s+news|wwe|aew|wrestling)\b", re.I),
    re.compile(r"\bsi\s+occupa\s+di\s+fornire\s+una\s+copertura\s+(?:affidabile|costante|accurata)\b", re.I),
    re.compile(r"\b(?:fornisce|offre|porta)\s+una\s+copertura\s+(?:affidabile|costante|accurata)\b.*\b(wwe|aew|wrestling|ringside\s+news)\b", re.I),
    re.compile(r"\b(?:covering|covers)\s+(?:wwe|aew|professional\s+wrestling|pro\s+wrestling)\b.*\b(ringside\s+news|news|rumors|results)\b", re.I),
    re.compile(r"\b(?:wwe|aew|tna|professional\s+wrestling|pro\s+wrestling)\b.*\b(?:news|rumors|results|coverage)\b.*\b(?:ringside\s+news|writer|author|contributor)\b", re.I),
    # Legacy specific bio clues.
    re.compile(r"\b(ha\s+oltre|vanta\s+oltre)\s+\d+\s+anni\s+di\s+esperienza\b", re.I),
    re.compile(r"\bfondatore\s+di\s+ringside\s+news\b", re.I),
    re.compile(r"\b(le|i)\s+sue\s+(storie|articoli|notizie)\s+sono\s+state\s+pubblicate\b", re.I),
    re.compile(r"\b(tmz|forbes|bleacher\s+report)\b.*\b(ringside\s+news|pubblicate|riprese)\b", re.I),
    re.compile(r"\bsegu(i|ilo|ici)\s+.+\s+su\s+(x|twitter|instagram|facebook|bluesky)\b", re.I),
]
CTA_PATTERNS = [
    re.compile(r"\bfateci\s+sapere\b|\bdicci\s+la\s+tua\b|\bcosa\s+ne\s+pensate\b", re.I),
    re.compile(r"\bcommenti\s+qui\s+sotto\b|\blascia\s+un\s+commento\b", re.I),
    re.compile(r"\bpensi\s+che\b.*\b(d[iì]\s+la\s+tua|commenti|nei\s+commenti)\b", re.I),
    re.compile(r"\bche\s+ne\s+pensi\b.*\b(commenti|facci\s+sapere|dicci)\b", re.I),
    re.compile(r"\b(drop|leave)\s+(your\s+)?(thoughts|comments?)\b.*\bcomments?\b", re.I),
    re.compile(r"\blet\s+us\s+know\b.*\bcomments?\b", re.I),
    re.compile(r"\bsound\s+off\b.*\bcomments?\b", re.I),
]
P_RE = re.compile(r"<p>(.*?)</p>", re.S | re.I)
BLOCKQUOTE_RE = re.compile(r"<blockquote>(.*?)</blockquote>", re.S | re.I)
EMBED_LINE_RE = re.compile(r"(?m)^\s*(https?://(?:www\.)?(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com|threads\.net|facebook\.com|bsky\.app)/\S+)\s*$", re.I)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or ""))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(value)).strip()


def should_remove_paragraph(inner: str) -> str:
    text = clean_text(inner)
    lower = text.lower()
    for pattern in RESIDUAL_BIO_PATTERNS:
        if pattern.search(text):
            return "residual_author_bio"
    # Additional high-confidence generic guard: a final short paragraph that combines Ringside News
    # with role/coverage language is almost always an author box residue, not article content.
    if "ringside news" in lower and any(x in lower for x in ["autore", "autrice", "giornalista", "redattore", "redattrice", "writer", "contributor", "collaboratore", "specializzato", "specializzata", "copertura", "notizie", "indiscrezioni", "risultati"]):
        return "residual_author_bio"
    for pattern in CTA_PATTERNS:
        if pattern.search(text):
            return "residual_cta"
    return ""


def move_leading_embeds_after_first_paragraph(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []
    text = body_html or ""
    leading: list[str] = []
    while True:
        stripped = text.lstrip()
        m = EMBED_LINE_RE.match(stripped)
        if not m:
            break
        url = m.group(1).strip()
        leading.append(url)
        text = stripped[m.end():].lstrip("\n\r ")
    if not leading:
        return body_html, changes
    first_p = P_RE.search(text)
    if not first_p:
        return body_html, changes
    insert = "\n" + "\n\n".join(leading) + "\n"
    text = text[: first_p.end()] + insert + text[first_p.end():]
    changes.append({"code": "leading_embed_moved_after_first_paragraph", "severity": "info", "message": "Embed iniziale spostato dopo il primo paragrafo.", "evidence": leading[0]})
    return text, changes


def unwrap_probable_fake_blockquotes(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        text = clean_text(inner)
        starts_with_quote = text.startswith(("\"", "“", "'"))
        ends_with_quote = text.endswith(("\"", "”", "'"))
        if starts_with_quote or ends_with_quote:
            return match.group(0)
        if any(token in text.lower() for token in ["milioni", "ascolti", "visualizzazioni", "ore di visione", "classificato", "netflix", "viewership", "hours watched"]):
            changes.append({"code": "fake_data_quote_unwrapped", "severity": "info", "message": "Blocco dati non virgolettato convertito da blockquote a paragrafo.", "evidence": text[:300]})
            return f"<p>{html.escape(text)}</p>"
        return match.group(0)

    return BLOCKQUOTE_RE.sub(repl, body_html or ""), changes


def postprocess_body(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []
    body_html, moved_changes = move_leading_embeds_after_first_paragraph(body_html)
    changes.extend(moved_changes)
    body_html, quote_changes = unwrap_probable_fake_blockquotes(body_html)
    changes.extend(quote_changes)

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        remove_reason = should_remove_paragraph(inner)
        if remove_reason:
            changes.append({"code": remove_reason, "severity": "info", "message": "Paragrafo residuo rimosso da Bob v93.33.", "evidence": clean_text(inner)[:300]})
            return ""
        # v93.27+: do not split inline quotation marks into blockquotes.
        # Only blocks that were already <blockquote> in the source remain styled as quotes.
        return match.group(0)

    body_html = P_RE.sub(repl, body_html or "")
    body_html = re.sub(r"\n{3,}", "\n\n", body_html).strip()
    return body_html, changes


def run_bob(menzo_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    result = base_run_bob(menzo_decision)
    total_changes = 0
    for article in result.get("articles", []) if isinstance(result, dict) else []:
        if not isinstance(article, dict):
            continue
        body, changes = postprocess_body(str(article.get("body_html") or ""))
        if changes:
            article["body_html"] = body
            article.setdefault("editorial_changes", []).extend(changes)
            article.setdefault("diagnostic_warnings", [])
            total_changes += len(changes)
    result["version"] = VERSION
    result.setdefault("policy", {})["v94_14_translation_guardrails_in_prompt"] = True
    result.setdefault("policy", {})["v92_translation_prompt_policy_embedded_compact"] = True
    result.setdefault("policy", {})["residual_author_bio_cleanup"] = True
    result.setdefault("policy", {})["generic_ringside_author_bio_cleanup"] = True
    result.setdefault("policy", {})["residual_cta_cleanup"] = True
    result.setdefault("policy", {})["split_inline_quoted_text"] = False
    result.setdefault("policy", {})["source_blockquote_only"] = True
    result.setdefault("policy", {})["move_leading_embeds_after_first_paragraph"] = True
    result.setdefault("policy", {})["unwrap_fake_data_blockquotes"] = True
    result.setdefault("postprocess", {})["bob_v94_14_prompt_guardrails"] = True
    result.setdefault("postprocess", {})["bob_v93_33_changes"] = total_changes
    # Backward-compatible metric used by the master log.
    result.setdefault("postprocess", {})["bob_v93_16_changes"] = total_changes
    write_json(ARTIFACT_BOB_FILE, result)
    write_json(BOB_ARTICLES_FILE, result)
    print(f"[BOB v94.14] Cleanup finale + guardrail traduzione applicati | changes={total_changes}", flush=True)
    return result
