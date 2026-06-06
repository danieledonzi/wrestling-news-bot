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
ARTIFACT_WP_PREFLIGHT_FILE = ARTIFACT_DIR / "artifacts" / "newsroom" / "wp_preflight.json"
if not ARTIFACT_WP_PREFLIGHT_FILE.parent.exists():
    ARTIFACT_WP_PREFLIGHT_FILE = ARTIFACT_DIR / "wp_preflight.json"

VERSION = "v93_38_verbose_wp_preflight_with_runner_ip"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
TIMEOUT = int(os.getenv("V93_WP_PREFLIGHT_TIMEOUT", os.getenv("V92_WP_HEALTH_TIMEOUT", "10")))
RETRIES = int(os.getenv("V93_WP_PREFLIGHT_RETRIES", os.getenv("V92_WP_HEALTH_RETRIES", "2")))
SLEEP_SECONDS = int(os.getenv("V93_WP_PREFLIGHT_RETRY_SLEEP", "2"))
PUBLIC_IP_TIMEOUT = int(os.getenv("V93_PUBLIC_IP_TIMEOUT", "6"))


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


def runner_public_ips() -> list[str]:
    endpoints = [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://ifconfig.me/ip",
    ]
    out: list[str] = []
    for endpoint in endpoints:
        try:
            res = requests.get(endpoint, headers=HEADERS, timeout=PUBLIC_IP_TIMEOUT)
            value = (res.text or "").strip()
            if res.status_code == 200 and value and len(value) < 80 and value not in out:
                out.append(value)
        except Exception as exc:
            print(f"[WP PREFLIGHT v93.38] runner_ip_probe_error endpoint={endpoint}: {exc}", flush=True)
    return out


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
    wp_ips = dns_ips(root) if root else []
    runner_ips = runner_public_ips()
    result: dict[str, Any] = {
        "version": VERSION,
        "checked_at": utc_now(),
        "root": root,
        "ready": False,
        "reason": "unknown",
        "attempts": [],
        "dns_ips": wp_ips,
        "runner_public_ips": runner_ips,
        "handoff": {"ready": 0, "skipped_expensive_agents": 0},
        "policy": {
            "skip_menzo_bob_alfred_publisher_when_wp_down": True,
            "skip_gemini_when_wp_down": True,
            "manual_like_health_check": True,
            "home_probe_warms_wordpress": True,
            "verbose_probe_logging": True,
            "runner_public_ip_logged": True,
            "timeout_seconds": TIMEOUT,
            "retries": RETRIES,
        },
    }
    print(f"[WP PREFLIGHT v93.38] runner_public_ips={', '.join(runner_ips) if runner_ips else 'unknown'}", flush=True)
    print(f"[WP PREFLIGHT v93.38] target_dns_ips={', '.join(wp_ips) if wp_ips else 'unknown'} root={root or 'missing'}", flush=True)

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
        print(f"[WP PREFLIGHT v93.38] attempt {attempt}/{RETRIES} timeout={TIMEOUT}s", flush=True)
        for endpoint, use_auth, label in endpoints:
            ok, status, elapsed = probe(endpoint, use_auth=use_auth)
            row = {"attempt": attempt, "label": label, "endpoint": endpoint, "status": status, "elapsed_seconds": round(elapsed, 2), "ok": ok}
            result["attempts"].append(row)
            print(f"[WP PREFLIGHT v93.38] probe label={label} ok={ok} status={status} elapsed={elapsed:.2f}s endpoint={endpoint}", flush=True)
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
                print(f"[WP PREFLIGHT v93.38] ready=True reason={status} home_ok={had_home_ok}", flush=True)
                return result
        if attempt < RETRIES:
            print(f"[WP PREFLIGHT v93.38] sleep before retry seconds={SLEEP_SECONDS}", flush=True)
            time.sleep(SLEEP_SECONDS)
    result["reason"] = last_reason
    result["policy"]["home_ok_but_rest_failed"] = had_home_ok
    result["handoff"]["skipped_expensive_agents"] = 1
    write_json(WP_PREFLIGHT_FILE, result)
    write_json(ARTIFACT_WP_PREFLIGHT_FILE, result)
    print(f"[WP PREFLIGHT v93.38] ready=False reason={last_reason} home_ok={had_home_ok}", flush=True)
    return result


if __name__ == "__main__":
    print(json.dumps(run_wp_preflight(), ensure_ascii=False, indent=2))
