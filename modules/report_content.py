"""Ordered, report-only extraction and WordPress-safe presentation.

Source scripts are never executed or published. Lazy embed markup supplies only
allowlisted permalinks; WordPress performs its own native oEmbed rendering.
"""
from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

CONTENT_SELECTORS = (
    "article.rsn-single-article .entry-content", ".cntn-wrp.artl-cnt .sp-cnt",
    ".cntn-wrp.artl-cnt", "div.sp-cnt", ".entry-content", ".article-content", ".article-body",
    ".live-article", "article",
)
NOISE_SELECTOR = (
    "script,style,noscript,nav,aside,form,.live-header,.author-bio,.author-box,"
    ".rsn-author-box,.sharedaddy,.share-buttons,.related-posts,.ad-container,"
    ".advertisement,.connatix,.rsn-google-preferred-source"
)
SERVICE_SENTENCE = re.compile(
    r"^(?:welcome to (?:ringside news|wrestling\s*inc)|"
    r"(?:ringside news|wrestling\s*inc) (?:will provide|brings you|provides|has you covered)|"
    r"(?:keep|be sure to|make sure to|please) (?:refresh|check back|follow|leave|subscribe)|"
    r"refresh (?:this|the) page|follow (?:us|along with (?:ringside|wrestling))|"
    r"(?:let us know|share your thoughts|leave (?:a|your) comment)|"
    r"(?:thanks|thank you) for (?:reading|following|joining)|"
    r"(?:what (?:do|did) you think|sound off|stay tuned to (?:ringside|this page)))", re.I,
)
PRESHOW_RE = re.compile(r"\b(?:pre[\s-]?show|countdown|zero hour|buy[\s-]?in|kick[\s-]?off)\b", re.I)


def clean_source_prose(text: str) -> str:
    # Sentence-level removal preserves real broadcast details in a mixed intro.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return " ".join(s for s in sentences if not SERVICE_SENTENCE.search(s)).strip()


def safe_embed_url(raw: str, base_url: str) -> str:
    p = urlsplit(urljoin(base_url, raw.strip()))
    host = (p.hostname or "").lower().removeprefix("www.")
    if p.scheme not in {"http", "https"} or p.username or p.password:
        return ""
    path = p.path.rstrip("/")
    if host in {"x.com", "twitter.com"} and re.fullmatch(r"/[A-Za-z0-9_]+/status/\d+", path):
        return f"https://twitter.com{path}"
    if host == "youtu.be" and re.fullmatch(r"/[A-Za-z0-9_-]+", path):
        return f"https://www.youtube.com/watch?v={path[1:]}"
    if host in {"youtube.com", "youtube-nocookie.com"}:
        from urllib.parse import parse_qs
        video = (parse_qs(p.query).get("v") or [""])[0] if path == "/watch" else path.rsplit("/", 1)[-1] if path.startswith(("/embed/", "/shorts/")) else ""
        if re.fullmatch(r"[A-Za-z0-9_-]+", video):
            return f"https://www.youtube.com/watch?v={video}"
    if ((host == "instagram.com" and re.fullmatch(r"/(?:p|reel|tv)/[A-Za-z0-9_-]+", path))
            or (host == "tiktok.com" and re.fullmatch(r"/@[^/]+/video/\d+", path))
            or (host == "bsky.app" and path.startswith("/profile/") and "/post/" in path)
            or (host in {"threads.net", "threads.com"} and "/post/" in path)):
        return urlunsplit(("https", p.netloc, path + "/", "", ""))
    return ""


def media_urls(node: Tag, base_url: str) -> list[str]:
    urls = []
    for el in [node, *node.find_all(["a", "iframe", "blockquote"])]:
        for attr in ("cite", "href", "src", "data-instgrm-permalink"):
            url = safe_embed_url(str(el.get(attr) or ""), base_url)
            if url and url not in urls:
                urls.append(url)
    return urls


def extract_report_blocks(source_html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(source_html, "html.parser")
    root = next((soup.select_one(sel) for sel in CONTENT_SELECTORS if soup.select_one(sel)), None)
    if root is None:
        raise ValueError("Report body container not found")
    for node in root.select(NOISE_SELECTOR):
        node.decompose()
    blocks: list[dict] = []

    def emit_text(node: Tag, kind: str, **metadata) -> None:
        text = clean_source_prose(node.get_text(" ", strip=True))
        if text:
            blocks.append({"type": kind, "text": text, **metadata})

    def walk(node: Tag) -> None:
        lazy = node.get("data-rsn-html")
        if lazy is not None:
            try:
                fragment = base64.b64decode(str(lazy), validate=True).decode("utf-8")
            except (ValueError, UnicodeError, binascii.Error) as exc:
                raise ValueError("Invalid lazy report media") from exc
            urls = media_urls(BeautifulSoup(fragment, "html.parser"), source_url)
            if not urls:
                raise ValueError("Unsupported lazy report media; refusing silent omission")
            blocks.extend({"type": "embed", "url": url} for url in urls)
            return
        classes = " ".join(node.get("class", []))
        if (node.name in {"iframe", "blockquote"} or
                node.name in {"figure", "div"} and re.search(r"(?:wp-block-embed|twitter-tweet|instagram-media)", classes)):
            # A lazy child must be visited at this very position, not recovered later.
            if not node.find(attrs={"data-rsn-html": True}):
                urls = media_urls(node, source_url)
                if urls:
                    blocks.extend({"type": "embed", "url": url} for url in urls)
                    return
        if node.name in {"h2", "h3", "h4", "h5", "h6"}:
            emit_text(node, "heading", level=node.name)
        elif node.name == "li":
            # One item, even if WordPress nests a paragraph inside it.
            emit_text(node, "paragraph", list_type=node.parent.name if node.parent.name in {"ul", "ol"} else "ul")
        elif node.name in {"p", "blockquote"}:
            kind = "quote" if node.name == "blockquote" else "paragraph"
            if not node.find(["img", "iframe"]) and not node.find(attrs={"data-rsn-html": True}):
                emit_text(node, kind)
            else:
                # Mixed inline text/media must not swallow an image or lazy embed.
                pending: list[str] = []

                def flush() -> None:
                    text = clean_source_prose(" ".join(pending))
                    if text:
                        blocks.append({"type": kind, "text": text})
                    pending.clear()

                def inline(child) -> None:
                    if isinstance(child, NavigableString):
                        pending.append(str(child))
                    elif isinstance(child, Tag):
                        if child.name in {"img", "iframe"} or child.get("data-rsn-html") is not None:
                            flush()
                            walk(child)
                        else:
                            for descendant in child.children:
                                inline(descendant)

                for child in node.children:
                    inline(child)
                flush()
        elif node.name == "img":
            src = node.get("data-src") or node.get("data-lazy-src") or node.get("src")
            if src and not str(src).startswith("data:"):
                from modules.report_workshop_v92 import is_bad_inline_image
                src = urljoin(source_url, str(src))
                if not is_bad_inline_image(src, node):
                    blocks.append({"type": "image", "src": src, "alt": node.get("alt") or ""})
        else:
            for child in node.children:
                if isinstance(child, Tag):
                    walk(child)

    walk(root)
    from modules.simone_report_integrity import cleanup_blocks
    blocks, _diagnostics = cleanup_blocks(blocks, source_url)
    if not any(b["type"] == "paragraph" for b in blocks):
        raise ValueError("Report has no substantive text")
    return blocks


def preshow_range(blocks: list[dict], job: dict) -> tuple[int, int] | None:
    if job.get("report_type") == "weekly":
        return None
    if str(job.get("event_type") or "").upper() not in {"PLE", "PPV"}:
        return None
    for start, block in enumerate(blocks):
        if block.get("type") != "heading" or not PRESHOW_RE.search(block.get("text", "")):
            continue
        level = int(block.get("level", "h2")[1])
        for end in range(start + 1, len(blocks)):
            next_block = blocks[end]
            if next_block.get("type") == "heading" and int(next_block.get("level", "h2")[1]) <= level and not PRESHOW_RE.search(next_block.get("text", "")):
                return start, end
    return None


def preshow_open(label: str) -> str:
    import html
    return (
        '<details class="owtv-report-preshow" style="margin:24px 0;border:2px solid #b71c1c;border-radius:8px;overflow:hidden">'
        '<summary style="cursor:pointer;background:#fff1f1;color:#821313;padding:18px;font-size:18px;font-weight:700;line-height:1.5">'
        f'{html.escape(label)}<br><span style="font-size:14px;font-weight:600">'
        'Clicca qui per espandere e leggere il pre-show</span></summary>'
        '<div style="padding:16px">'
    )
