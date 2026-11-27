"""Resolve ordinary news hyperlinks using exact published-source identity.

No semantic matching, external probes, cache across articles, or HTML
reserialization. The only network operation is one bounded anonymous WP
collection lookup if the current article contains known historical targets.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from modules.editorial_media_links import editorial_href, media_url

MAX_VERIFY_IDS = 20
_SOURCE_NEWS_HOSTS = {"wrestlinginc.com", "ringsidenews.com", "fightful.com"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCKED = {"figure", "iframe", "object", "embed", "script", "style", "pre", "code", "nav", "aside", "footer", "header", "textarea", "template", "noscript", "select", "svg", "math"}
_BLOCK_CLASS = re.compile(r"(?:^|\s)(?:owtv-source-attribution|wp-block-embed\S*|wp-block-image|owtv-report-media|owtv-media\S*)(?:\s|$)", re.I)
_ANCHOR = re.compile(r"""<a\s+href\s*=\s*(["'])(.*?)\1\s*>""", re.I | re.S)


def source_identity(raw: str, *, report: bool = False) -> tuple | None:
    """Preserve path case and queries; never guess a section/fragment match."""
    try:
        if not isinstance(raw, str) or not editorial_href(raw) or media_url(raw):
            return None
        p = urlsplit(raw)
        if p.fragment or not p.hostname or p.username is not None or p.password is not None:
            return None
        hosts = _SOURCE_NEWS_HOSTS | {"wrestleview.com"} if report else _SOURCE_NEWS_HOSTS
        host = p.hostname.lower()
        if host.startswith("www.") and host[4:] in hosts:
            host = host[4:]
        if host not in hosts:
            return None
        return (p.scheme.lower(), host, p.port, p.path.rstrip("/"), p.query)
    except (TypeError, ValueError):
        return None


def _internal_destination(raw: str, root: str) -> tuple | None:
    """Require a safe same-origin public permalink, not an arbitrary WP link."""
    try:
        if not isinstance(raw, str) or not raw or re.search(r"""[\s\\<>"'\[\]\x00-\x1f\x7f]""", raw):
            return None
        p, b = urlsplit(raw), urlsplit(root)
        if (p.scheme, p.hostname, p.port) != (b.scheme, b.hostname, b.port) or p.scheme not in {"http", "https"} or not p.hostname:
            return None
        if p.username is not None or p.password is not None or p.query or p.fragment:
            return None
        base_path = b.path.rstrip("/")
        if not p.path.startswith(base_path + "/") or p.path.rstrip("/") == base_path:
            return None
        if any(part in {".", ".."} for part in p.path.split("/")) or re.search(r"%(?:2f|5c|2e)", p.path, re.I):
            return None
        return (p.scheme, p.hostname, p.port, p.path.rstrip("/"))
    except (TypeError, ValueError):
        return None


def _published_target(record, root):
    if not isinstance(record, dict):
        return None
    post_id = record.get("wp_post_id")
    link = _internal_destination(record.get("wp_link", ""), root)
    if isinstance(post_id, str) and re.fullmatch(r"[1-9]\d{0,17}", post_id):
        post_id = int(post_id)
    return (post_id, link) if type(post_id) is int and post_id > 0 and link and record.get("status") == "publish" else None


class _OrdinaryAnchors(HTMLParser):
    """Collect raw href offsets only for Bob's plain prose anchors."""
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.content = content
        self.offsets = [0] + [m.end() for m in re.finditer("\n", content)]
        self.stack = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        attrs_map = dict(attrs)
        blocked = tag in _BLOCKED or bool(_BLOCK_CLASS.search(str(attrs_map.get("class") or ""))) or any(k.startswith("data-owtv-media") for k,v in attrs)
        if tag == "a" and len(attrs) == 1 and attrs[0][0] == "href" and attrs[0][1] and not blocked:
            if not any(entry[1] or entry[0] == "a" for entry in self.stack) and any(entry[0] in {"p", "blockquote", "li"} for entry in self.stack):
                raw = self.get_starttag_text()
                match = _ANCHOR.fullmatch(raw)
                if match:
                    line, col = self.getpos()
                    start = self.offsets[line-1] + col
                    self.anchors.append((start+match.start(2), start+match.end(2), attrs[0][1]))
        if tag not in _VOID:
            self.stack.append((tag, blocked))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def resolve_internal_links(content: str, history: dict, *, source_url: str, root: str, enabled: bool, fetch, report_records=None) -> tuple[str, dict]:
    """Prefer exact news history, then report identity; verify public WP once."""
    diag = {"eligible": 0, "matched": 0, "rewritten": 0, "unverified": 0, "budget_skipped": 0, "requests": 0, "reason": "disabled"}
    if report_records is not None:
        diag.update(report_matched=0, report_rewritten=0)
    if not enabled:
        return content, diag
    try:
        parser = _OrdinaryAnchors(content)
        parser.feed(content)
        parser.close()
        current = source_identity(source_url, report=report_records is not None)
        anchors = [(start,end,source_identity(href) or (source_identity(href, report=True) if report_records is not None else None)) for start,end,href in parser.anchors]
        anchors = [(start,end,key) for start,end,key in anchors if key is not None and key != current]
        diag["eligible"] = len(anchors)
        diag["reason"] = "no_match"
        if not anchors or not isinstance(history, dict):
            return content, diag
        wanted = {key for _,_,key in anchors}
        records = {}
        for record in history.values():
            if not isinstance(record, dict):
                continue
            key = source_identity(record.get("source_url", ""), report=report_records is not None)
            if key not in wanted:
                continue
            # Invalid or conflicting historical records are ambiguous.
            records.setdefault(key, set()).add(_published_target(record, root))
        report_keys = set()
        if isinstance(report_records, dict):
            for key in wanted - records.keys():
                rows = report_records.get(key)
                if not isinstance(rows, list) or not rows:
                    continue
                records[key] = {_published_target(row, root) for row in rows}
                report_keys.add(key)
        matches = {}
        for key, values in records.items():
            if len(values) == 1 and None not in values:
                matches[key] = next(iter(values))
        candidates = [(start,end,matches[key]) for start,end,key in anchors if key in matches]
        diag["matched"] = len(candidates)
        if report_records is not None:
            diag["report_matched"] = sum(key in matches and key in report_keys for _,_,key in anchors)
            diag["report_rewritten"] = 0
        if not candidates:
            return content, diag
        ids = list(dict.fromkeys(value[0] for _,_,value in candidates))
        ids = ids[:MAX_VERIFY_IDS]
        pending = [(start,end,value) for start,end,value in candidates if value[0] in ids]
        diag["budget_skipped"] = len(candidates)-len(pending)
        diag["unverified"] = len(pending)
        diag["requests"] = 1
        diag["reason"] = "wp_unavailable"
        response = fetch(root.rstrip("/") + "/wp-json/wp/v2/posts",
                         params={"include": ",".join(map(str, ids)), "status": "publish",
                                 "per_page": len(ids), "_fields": "id,status,link,type,content.protected"},
                         timeout=(3,5), allow_redirects=False,
                         headers={"Cache-Control": "no-cache"})
        if response.status_code != 200:
            return content, diag
        rows = response.json()
        if not isinstance(rows, list):
            return content, diag
        verified = {}
        duplicate_ids = set()
        for row in rows:
            if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] not in ids:
                continue
            post_id = row["id"]
            if post_id in verified:
                duplicate_ids.add(post_id)
            protected = row.get("content")
            link = row.get("link")
            verified[post_id] = link if (row.get("status") == "publish" and row.get("type") == "post" and isinstance(protected, dict) and protected.get("protected") is False and _internal_destination(link, root)) else None
        edits = []
        for start,end,(post_id,history_link) in pending:
            url = verified.get(post_id)
            if post_id not in duplicate_ids and url and _internal_destination(url, root) == history_link:
                edits.append((start,end,html.escape(url, quote=True)))
        out = content
        for start,end,href in sorted(edits, reverse=True):
            out = out[:start] + href + out[end:]
        diag["rewritten"] = len(edits)
        if report_records is not None:
            report_offsets = {start for start,_,key in anchors if key in report_keys}
            diag["report_rewritten"] = sum(start in report_offsets for start,_,_ in edits)
        diag["unverified"] = len(pending)-len(edits)
        diag["reason"] = "verified" if edits else "not_public_or_mismatch"
        return out, diag
    except Exception:
        # Link optimization must never stop an otherwise valid publication.
        diag["reason"] = "resolution_error"
        return content, diag
