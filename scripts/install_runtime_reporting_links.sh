#!/usr/bin/env bash
set -euo pipefail

repo_root="${OWTV_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
repo_root="$(cd "${repo_root}" && pwd)"
source_path="${repo_root}/scripts/owtv_gemini_ledger_report.py"
target_path="${OWTV_RUNTIME_REPORT_TARGET:-/opt/owtv/owtv_gemini_ledger_report.py}"

if [ ! -f "${source_path}" ]; then
  echo "[REPORTING] Canonical script missing: ${source_path}" >&2
  exit 1
fi

if [ -e "${target_path}" ] && [ ! -L "${target_path}" ]; then
  stamp="$(date +%Y%m%d_%H%M%S)"
  backup="${target_path}.pre_versioned_${stamp}"
  cp -a "${target_path}" "${backup}"
  echo "[REPORTING] Existing runtime script backed up to ${backup}"
fi

ln -sfn "${source_path}" "${target_path}"
chmod +x "${source_path}"

echo "[REPORTING] Installed symlink:"
ls -l "${target_path}"
