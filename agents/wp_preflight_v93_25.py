from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
WP_PREFLIGHT_FILE = NEWSROOM_STATE_DIR / "wp_preflight_latest.json"
ARTIFACT_WP_PREFLIGHT_FILE = ARTIFACT_DIR / "wp_preflight.json"

VERSION = "v93_37_manual_like_wp_preflight_gate"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
TIMEOUT = int(os.getenv("V93_WP_PREFLIGHT_TIMEOUT", os.getenv("V92_WP_HEALTH_TIMEOUT", "10")))
RETRIES = int(os.getenv("V93_WP_PREFLIGHT_RETRIES", os.getenv("V92_WP_HEALTH_RETRIES", "2")))
SLEEP_SECONDS = int(os.getenv("V93_WP_PREFLIGHT_RETRY_SLEEP", "2"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def wp_root() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in raw:
        raw = raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def wp_auth() -> tuple[str, str]:
    return os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")


def dns_ips(root: str) -> list[str]:
    try:
        host = urlparse(root).netloc
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        out: list[str] = []
        for info in infos:
            ip = info[4][0]
            if ip not in out:
                out.append(ip)
        return out
    except Exception:
        return []


def probe(endpoint: str, *, use_auth: bool) -> tuple[bool, str, float]:
    start = time.monotonic()
    try:
        kwargs: dict[str, Any] = {"headers": HEADERS, "timeout": TIMEOUT}
        if use_auth:
            kwargs["auth"] = wp_auth()
        res = requests.get(endpoint, **kwargs)
        elapsed = time.monotonic() - start
        if res.status_code in {200, 201, 401, 403}:
            return True, f"status_{res.status_code}", elapsed
        return False, f"status_{res.status_code}", elapsed
    except Exception as exc:
        elapsed = time.monotonic() - start
        return False, f"wp_error:{exc}", elapsed


def run_wp_preflight() -> dict[str, Any]:
    root = wp_root()
    result: dict[str, Any] = {
        "version": VERSION,
        "checked_at": utc_now(),
        "root": root,
        "ready": False,
        "reason": "unknown",
        "attempts": [],
        "dns_ips": dns_ips(root) if root else [],
        "handoff": {"ready": 0, "skipped_expensive_agents": 0},
        "policy": {
            "skip_menzo_bob_alfred_publisher_when_wp_down": True,
            "skip_gemini_when_wp_down": True,
            "manual_like_health_check": True,
            "home_probe_warms_wordpress": True,
            "timeout_seconds": TIMEOUT,
            "retries": RETRIES,
        },
    }
    if str(os.getenv("V93_ASSUME_WP_READY", "")).strip().lower() in {"1", "true", "yes", "on"}:
        result["ready"] = True
        result["reason"] = "assume_ready_env_override"
        result["handoff"]["ready"] = 1
        write_json(WP_PREFLIGHT_FILE, result)
        write_json(ARTIFACT_WP_PREFLIGHT_FILE, result)
        return result
    if not root:
        result["reason"] = "missing_wp_url"
        write_json(WP_PREFLIGHT_FILE, result)
        write_json(ARTIFACT_WP_PREFLIGHT_FILE, result)
        return result
    if not all(wp_auth()):
        result["reason"] = "missing_wp_auth"
        write_json(WP_PREFLIGHT_FILE, result)
        write_json(ARTIFACT_WP_PREFLIGHT_FILE, result)
        return result

    endpoints = [
        (f"{root}/", False, "home"),
        (f"{root}/wp-json/", False, "rest_root"),
        (f"{root}/wp-json/wp/v2/posts?per_page=1", True, "posts_auth"),
    ]
    last_reason = "wp_unavailable"
    had_home_ok = False
    for attempt in range(1, RETRIES + 1):
        for endpoint, use_auth, label in endpoints:
            ok, status, elapsed = probe(endpoint, use_auth=use_auth)
            result["attempts"].append({"attempt": attempt, "label": label, "endpoint": endpoint, "status": status, "elapsed_seconds": round(elapsed, 2)})
            last_reason = status
            if ok and label == "home":
                had_home_ok = True
                continue
            if ok and label in {"rest_root", "posts_auth"}:
                result["ready"] = True
                result["reason"] = status
                result["handoff"]["ready"] = 1
                result["policy"]["home_ok_before_ready"] = had_home_ok
                write_json(WP_PREFLIGHT_FILE, result)
                write_json(ARTIFACT_WP_PREFLIGHT_FILE, result)
                print(f"[WP PREFLIGHT v93.37] ready=True reason={status} home_ok={had_home_ok}", flush=True)
                return result
        if attempt < RETRIES:
            time.sleep(SLEEP_SECONDS)
    result["reason"] = last_reason
    result["policy"]["home_ok_but_rest_failed"] = had_home_ok
    result["handoff"]["skipped_expensive_agents"] = 1
    write_json(WP_PREFLIGHT_FILE, result)
    write_json(ARTIFACT_WP_PREFLIGHT_FILE, result)
    print(f"[WP PREFLIGHT v93.37] ready=False reason={last_reason} home_ok={had_home_ok}", flush=True)
    return result


if __name__ == "__main__":
    print(json.dumps(run_wp_preflight(), ensure_ascii=False, indent=2))
