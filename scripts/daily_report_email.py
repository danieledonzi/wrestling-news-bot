"""Versioned noon-mail runner. Observes only; --preview never connects to SMTP.

No legacy volume judgment, hard/soft estimates, lexical story clusters or
news-versus-report duplicate recommendations are generated or attached.
"""
from __future__ import annotations

import argparse
import json
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from scripts.current_editorial_report import ROOT, generate_outputs, render_summary


def diagnostic_bundle(root: Path, output_dir: Path, now: datetime) -> tuple[str, list[Path]]:
    """Attach exact artifacts of this invocation, never a previous latest/glob."""
    from scripts import translation_quality_audit as audit
    from scripts import translation_warning_analysis as investigation
    from scripts import build_weekly_pattern_report as weekly
    attachments: list[Path] = []
    failures = []
    quality_report = {}
    state = root / "state/reports"
    state.mkdir(parents=True, exist_ok=True)
    try:
        _payload, audit_json, audit_md = audit.build_audit(
            hours=24, limit=None, output_dir=output_dir, root=root,
            latest_path=state / "owtv_translation_quality_audit_latest.json")
        attachments += [audit_md, audit_json]
        investigated = investigation.generate_outputs(audit_path=audit_json, output_dir=output_dir,
            state_dir=state, hours=24)
        quality_report = json.loads(investigated["json"].read_text(encoding="utf-8"))
        attachments += [investigated["markdown"], investigated["json"]]
    except Exception as exc:
        failures.append(f"Controlli di traduzione non disponibili: {type(exc).__name__}")
    try:
        result = weekly.generate_outputs(root=root, output_dir=output_dir, state_dir=state)
        attachments += [result["markdown"], result["json"]]
    except Exception as exc:
        failures.append(f"Segnali settimanali di traduzione non disponibili: {type(exc).__name__}")
    try:
        result = generate_outputs(root, until=now, output_dir=output_dir, quality_report=quality_report)
        payload = json.loads(result["json"].read_text(encoding="utf-8"))
        body = render_summary(payload)
        attachments = [result["markdown"], result["json"]] + attachments
    except Exception as exc:
        body = f"OSSERVAZIONE REDAZIONALE NON DISPONIBILE: {type(exc).__name__}.\nNessuna azione proposta: dati insufficienti."
        failures.append("Report e nota corrente non generati; nessun allegato precedente riutilizzato.")
    preface = "I segnali di traduzione allegati richiedono verifica: un controllo riprodotto non certifica un errore."
    if failures:
        preface += "\n" + "\n".join(failures)
    return preface + "\n\n" + body, list(dict.fromkeys(attachments))


def build_message(body: str, attachments: list[Path], now: datetime, config: dict[str, str]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"OWTV — Osservazione redazionale delle 12 — {now.astimezone(ZoneInfo('Europe/Rome')).date()}"
    message["From"] = config.get("MAIL_FROM") or config.get("SMTP_USER") or "preview@example.invalid"
    message["To"] = config.get("MAIL_TO") or "preview@example.invalid"
    message["Date"] = format_datetime(now)
    message.set_content(body)
    for path in attachments:
        if not path.is_file():
            raise FileNotFoundError(f"current_attachment_missing:{path.name}")
        message.add_attachment(path.read_bytes(), maintype="application", subtype="json" if path.suffix == ".json" else "octet-stream", filename=path.name)
    return message


def load_config(path: Path) -> dict[str, str]:
    config = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def send_message(message: EmailMessage, config: dict[str, str]) -> None:
    # Uses the existing production account and recipients; does not change them.
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"):
        if not config.get(key):
            raise ValueError(f"Missing mail setting: {key}")
    port = int(config.get("SMTP_PORT", "465"))
    context = ssl.create_default_context()
    if port == 465:
        client = smtplib.SMTP_SSL(config["SMTP_HOST"], port, context=context, timeout=60)
    else:
        client = smtplib.SMTP(config["SMTP_HOST"], port, timeout=60)
    with client:
        if port != 465:
            client.starttls(context=context)
        client.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
        client.send_message(message)


def main(argv: list[str] | None = None, *, root: Path = ROOT, bundle: Callable = diagnostic_bundle) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="Generate artifacts and an .eml; do not read SMTP credentials or send.")
    parser.add_argument("--output-dir", type=Path, default=root / "reports")
    parser.add_argument("--env-file", type=Path, default=Path("/opt/owtv/report_email.env"))
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    body, attachments = bundle(root, args.output_dir, now)
    config = {} if args.preview else load_config(args.env_file)
    message = build_message(body, attachments, now, config)
    if args.preview:
        path = args.output_dir / f"owtv_noon_preview_{now:%Y%m%d_%H%M%S}.eml"
        path.write_bytes(message.as_bytes())
        print(f"Preview generated: {path}; {len(attachments)} current attachments; no email sent.")
    else:
        send_message(message, config)
        print(f"Noon report sent; {len(attachments)} current attachments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
