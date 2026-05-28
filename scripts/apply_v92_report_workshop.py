from pathlib import Path
import subprocess
import sys

p = Path("bot_v92.py")
text = p.read_text(encoding="utf-8")

if "v92_0_2_report_workshop_publish" in text:
    print("[V92 PATCH] report workshop gia applicato")
else:
    text = text.replace(
        'BOT_VERSION = "v92_0_1_report_scheduler_and_matcher"',
        'BOT_VERSION = "v92_0_2_report_workshop_publish"',
    )

    import_marker = "import requests\n"
    if "from modules.report_workshop_v92 import run_report_workshop" not in text:
        text = text.replace(
            import_marker,
            import_marker + "from modules.report_workshop_v92 import run_report_workshop\n",
            1,
        )

    old = '''        pending = [p for p in pending if p.get("report_key") != report_key]
        pending.append(job)
        status[report_key] = {
            "status": job["status"],
            "source": job["source"],
            "source_url": job["source_url"],
            "source_title": job["source_title"],
            "title": title,
            "categories": categories,
            "updated_at": utcnow().isoformat(),
        }
'''

    new = '''        if wp_ok:
            try:
                log(f"[REPORT v92] Avvio workshop pubblicazione: {report_key}")
                post_id, _post_json = run_report_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
                status[report_key] = {
                    "status": "published",
                    "source": job["source"],
                    "source_url": job["source_url"],
                    "source_title": job["source_title"],
                    "title": title,
                    "categories": categories,
                    "wp_post_id": post_id,
                    "published_at": utcnow().isoformat(),
                    "updated_at": utcnow().isoformat(),
                }
                pending = [p for p in pending if p.get("report_key") != report_key]
                published += 1
                continue
            except Exception as exc:
                log(f"[REPORT v92] Errore workshop report {report_key}: {exc}")
                job["status"] = "failed_technical"
                job["error"] = str(exc)[:1000]

        pending = [p for p in pending if p.get("report_key") != report_key]
        pending.append(job)
        status[report_key] = {
            "status": job["status"],
            "source": job["source"],
            "source_url": job["source_url"],
            "source_title": job["source_title"],
            "title": title,
            "categories": categories,
            "updated_at": utcnow().isoformat(),
            "error": job.get("error"),
        }
'''

    if old not in text:
        raise SystemExit("[V92 PATCH] blocco pending report non trovato")

    text = text.replace(old, new, 1)

    if 'PUBLISHED_DIR = ROOT / "published"' not in text:
        text = text.replace(
            'CONFIG_DIR = ROOT / "config"\n',
            'CONFIG_DIR = ROOT / "config"\nPUBLISHED_DIR = ROOT / "published"\nREVIEW_DIR = ROOT / "published_html_review"\n',
            1,
        )

    text = text.replace(
        '    LOG_DIR.mkdir(parents=True, exist_ok=True)\n',
        '    LOG_DIR.mkdir(parents=True, exist_ok=True)\n    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)\n    REVIEW_DIR.mkdir(parents=True, exist_ok=True)\n',
        1,
    )

    p.write_text(text, encoding="utf-8")
    print("[V92 PATCH] report workshop applicato")

for patch_name in [
    "scripts/apply_v92_report_quality_patch.py",
    "scripts/apply_v92_report_runtime_tweaks.py",
    "scripts/apply_v92_report_legacy_translation_prompt.py",
    "scripts/apply_v92_report_source_intro_filter.py",
    "scripts/apply_v92_ringside_embed_recovery.py",
    "scripts/apply_v92_ringside_base64_embed_patch.py",
    "scripts/apply_v92_ringside_broad_embed_final_cleanup.py",
    "scripts/apply_v92_report_chunked_translation.py",
    "scripts/apply_v92_wp_resilience_patch.py",
    "scripts/apply_v92_news_pipeline.py",
    "scripts/apply_v92_news_scoring_v2.py",
    "scripts/apply_v92_stability_patch.py",
    "scripts/apply_v92_business_ple_card_patch.py",
]:
    patch = Path(patch_name)
    if patch.exists():
        subprocess.run([sys.executable, str(patch)], check=True)
    else:
        print(f"[V92 PATCH] patch non presente: {patch_name}")
