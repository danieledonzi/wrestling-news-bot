from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

LOG_PATH = Path("logs/master_log.log")
METRICS_PATH = Path("logs/v90_metrics.jsonl")
LATEST_PATH = Path("logs/v90_metrics_latest.json")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _latest_run_block(log_text: str) -> tuple[str, str | None, str | None, str | None]:
    starts = list(re.finditer(r"===== RUN START \[(.*?)\] VERSION \[(.*?)\] =====", log_text))
    if not starts:
        return "", None, None, None
    start = starts[-1]
    end = re.search(r"===== RUN END \[(.*?)\] VERSION \[(.*?)\] =====", log_text[start.end():])
    if end:
        block = log_text[start.start(): start.end() + end.end()]
    else:
        block = log_text[start.start():]
    return block, start.group(1), start.group(2), end.group(1) if end else None


def _parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _strip_html_words(html: str) -> list[str]:
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    text = unescape(html)
    return re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9'’\-]*", text)


def _html_metrics(path: Path) -> dict:
    html = _read_text(path)
    words = _strip_html_words(html)
    return {
        "path": str(path),
        "exists": path.exists(),
        "word_count": len(words),
        "paragraph_count": len(re.findall(r"<p\b", html, flags=re.I)),
        "blockquote_count": len(re.findall(r"<blockquote\b", html, flags=re.I)),
        "image_count": len(re.findall(r"<img\b", html, flags=re.I)),
        "iframe_count": len(re.findall(r"<iframe\b", html, flags=re.I)),
        "embed_hint_count": len(re.findall(r"(?:twitter\.com|x\.com|instagram\.com|youtube\.com|blockquote)", html, flags=re.I)),
    }


def _published_paths(block: str) -> list[str]:
    paths = []
    for m in re.finditer(r"\[PUBLISHED v[\d.]+\] Articolo salvato:\s*(\S+)", block):
        paths.append(m.group(1).strip())
    return paths


def _published_titles(block: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[OK\] Pubblicato:\s*(.+)", block)]


def _duration_map(block: str) -> dict:
    values = {}
    for label, sec in re.findall(r"\[PERF v71\]\s+([^:\n]+):\s+([0-9]+(?:\.[0-9]+)?)s", block):
        values.setdefault(label.strip(), []).append(float(sec))
    return {k: {"count": len(v), "total_seconds": round(sum(v), 2), "max_seconds": round(max(v), 2)} for k, v in values.items()}


def _extract_daily_counts(log_text: str, run_start: str | None) -> dict:
    if not run_start:
        return {}
    try:
        dt = datetime.strptime(run_start, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return {}
    today = dt.date().isoformat()
    last4 = dt - timedelta(hours=4)
    counts = {"published_today": 0, "published_last_4h": 0, "runs_today": 0}
    # Split by run starts so we can roughly assign publish events to a run timestamp.
    run_iter = list(re.finditer(r"===== RUN START \[(.*?)\] VERSION \[(.*?)\] =====", log_text))
    for i, m in enumerate(run_iter):
        try:
            rdt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        next_start = run_iter[i + 1].start() if i + 1 < len(run_iter) else len(log_text)
        block = log_text[m.start():next_start]
        published = len(re.findall(r"\[OK\] Pubblicato:", block))
        if rdt.date().isoformat() == today:
            counts["runs_today"] += 1
            counts["published_today"] += published
        if last4 <= rdt <= dt:
            counts["published_last_4h"] += published
    return counts


def collect() -> dict:
    log_text = _read_text(LOG_PATH)
    block, run_start, version, run_end = _latest_run_block(log_text)
    model_tasks = re.findall(r"\[MODEL v88\]\s+task=([a-zA-Z0-9_\-]+)\s+chain=([^\n]+)", block)
    gemini_uses = re.findall(r"\[GEMINI\]\s+Uso modello:\s*([^\n]+)", block)
    gemini_discarded = re.findall(r"\[GEMINI\]\s+Modello\s+([^\s]+)\s+scartato", block)
    candidates = re.search(r"News candidate totali:\s*(\d+)\s*\|\s*mode=([^|]+)\|\s*max nuove=(\d+)", block)
    published_summary = re.search(r"Pubblicati\s+(\d+)\s+articoli\s+\((\d+)\s+pending\s+\+\s+(\d+)\s+nuove\)\s+su\s+(\d+)\s+candidati provati", block)
    score_lines = re.findall(r"^\[SCORE\]\s+([^\n]+)$", block, flags=re.M)
    skips_v89 = re.findall(r"\[SKIP v89\]\s+([^\n]+)", block)
    skips_all = re.findall(r"\[SKIP[^\]]*\]\s+([^\n]+)", block)
    published_paths = _published_paths(block)
    article_metrics = []
    titles = _published_titles(block)
    for idx, p in enumerate(published_paths):
        m = _html_metrics(Path(p))
        if idx < len(titles):
            m["title"] = titles[idx]
        article_metrics.append(m)
    result = {
        "schema_version": "v90.0",
        "collected_at": _now_iso(),
        "run_start": run_start,
        "run_end": run_end,
        "bot_version": version,
        "candidate_count": _parse_int(candidates.group(1) if candidates else None),
        "mode": (candidates.group(2).strip() if candidates else None),
        "max_new": _parse_int(candidates.group(3) if candidates else None),
        "published_total": _parse_int(published_summary.group(1) if published_summary else str(len(titles))),
        "published_pending": _parse_int(published_summary.group(2) if published_summary else None),
        "published_new": _parse_int(published_summary.group(3) if published_summary else None),
        "candidates_tried": _parse_int(published_summary.group(4) if published_summary else None),
        "score_lines_count": len(score_lines),
        "skip_count": len(skips_all),
        "skip_v89_count": len(skips_v89),
        "gemini_calls_observed": len(gemini_uses),
        "gemini_models": dict(Counter(gemini_uses)),
        "gemini_discarded_models": dict(Counter(gemini_discarded)),
        "model_tasks": [{"task": t, "chain": c.strip()} for t, c in model_tasks],
        "model_task_counts": dict(Counter(t for t, _ in model_tasks)),
        "perf": _duration_map(block),
        "article_metrics": article_metrics,
        "daily_counts": _extract_daily_counts(log_text, run_start),
    }
    return result


def main() -> int:
    LOG_PATH.parent.mkdir(exist_ok=True)
    metrics = collect()
    LATEST_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with METRICS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False, sort_keys=True) + "\n")
    print(
        "[METRICS v90.0] "
        f"published={metrics.get('published_total')} "
        f"candidates={metrics.get('candidate_count')} "
        f"gemini_calls={metrics.get('gemini_calls_observed')} "
        f"models={metrics.get('gemini_models')} "
        f"daily={metrics.get('daily_counts')}"
    )
    for article in metrics.get("article_metrics", []):
        print(
            "[METRICS v90.0] article "
            f"words={article.get('word_count')} images={article.get('image_count')} "
            f"quotes={article.get('blockquote_count')} title={article.get('title','')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
