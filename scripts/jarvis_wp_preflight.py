#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

VERSION = "v93_25_jarvis_wp_preflight_script"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write(path: str, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def root_url() -> str:
    root = os.environ.get("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in root:
        root = root.split("/wp-json", 1)[0].rstrip("/")
    return root


def dns_ips(root: str) -> list[str]:
    try:
        host = urlparse(root).netloc
        out: list[str] = []
        for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
        return out
    except Exception:
        return []


def preflight() -> dict:
    root = root_url()
    result = {"version": VERSION, "checked_at": now(), "root": root, "ready": False, "reason": "unknown", "dns_ips": dns_ips(root) if root else [], "attempts": []}
    if not root:
        result["reason"] = "missing_wp_url"
        return result
    if not os.environ.get("WP_USER") or not os.environ.get("WP_PASSWORD"):
        result["reason"] = "missing_wp_auth"
        return result
    endpoints = [(f"{root}/wp-json/", False, "rest_root"), (f"{root}/wp-json/wp/v2/posts?per_page=1", True, "posts_auth")]
    last = "wp_unavailable"
    timeout = int(os.environ.get("V93_WP_PREFLIGHT_TIMEOUT", "6"))
    for endpoint, use_auth, label in endpoints:
        start = time.monotonic()
        try:
            kwargs = {"timeout": timeout, "headers": {"User-Agent": "OpenWrestlingTV-v93-JarvisPreflight/1.0"}}
            if use_auth:
                kwargs["auth"] = (os.environ.get("WP_USER", ""), os.environ.get("WP_PASSWORD", ""))
            response = requests.get(endpoint, **kwargs)
            status = f"status_{response.status_code}"
            last = status
            result["attempts"].append({"label": label, "status": status, "elapsed_seconds": round(time.monotonic() - start, 2)})
            if response.status_code in {200, 201, 401, 403}:
                result["ready"] = True
                result["reason"] = status
                return result
        except Exception as exc:
            last = f"wp_error:{exc}"
            result["attempts"].append({"label": label, "status": last, "elapsed_seconds": round(time.monotonic() - start, 2)})
    result["reason"] = last
    return result


def main() -> int:
    result = preflight()
    write("artifacts/newsroom/wp_preflight.json", result)
    write("state/newsroom/wp_preflight_latest.json", result)
    if result.get("ready"):
        print(f"[JARVIS v93.25] wp_preflight_ready - ready=True reason={result.get('reason')}", flush=True)
        return 0
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/newsroom_master.log").open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== NEWSROOM MASTER RUN {now()} | v93_25_jarvis_wp_preflight | run_id={os.environ.get('GITHUB_RUN_ID', '')} =====\n")
        fh.write(f"Jarvis: wp_preflight=false reason={result.get('reason')}\n")
        fh.write("Publisher: published=0 wp_not_ready=1 errors=0\n")
        fh.write("Selected: -\nPublished news: -\nPublished reports: -\n")
    Path(".bot_exit_code").write_text("0", encoding="utf-8")
    print(f"[JARVIS v93.25] expensive_pipeline_skipped - WordPress not ready, Gemini avoided: {result.get('reason')}", flush=True)
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
