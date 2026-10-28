import stat

from scripts.install_lite_fallback_env import LITE, install, migrate


def test_inserts_lite_before_pro_and_other_existing_fallbacks_without_touching_keys():
    source = '# comment\nGEMINI_API_KEY=private\nREPORT_GEMINI_MODEL_CHAIN="gemini-3.1-flash-lite,gemini-2.5-pro,gemini-3.5-flash"\nBOB_STANDARD_MODEL_CHAIN=a,b\nOTHER=unchanged\n'
    updated, changed = migrate(source)
    assert changed == ["REPORT_GEMINI_MODEL_CHAIN", "BOB_STANDARD_MODEL_CHAIN"]
    assert f"REPORT_GEMINI_MODEL_CHAIN=gemini-3.1-flash-lite,{LITE},gemini-2.5-pro,gemini-3.5-flash\n" in updated
    assert "GEMINI_API_KEY=private\n" in updated and "OTHER=unchanged\n" in updated
    assert migrate(updated) == (updated, [])


def test_explicit_primary_and_single_model_contracts_are_preserved():
    source = f'export GEMINI_MODEL_CHAIN=primary,pro,{LITE}\nREPORT_GEMINI_MODEL_CHAIN={LITE},pro\nBOB_STANDARD_MODEL_CHAIN=single'
    updated, changed = migrate(source)
    assert updated == f'export GEMINI_MODEL_CHAIN=primary,{LITE},pro\nREPORT_GEMINI_MODEL_CHAIN={LITE},pro\nBOB_STANDARD_MODEL_CHAIN=single'
    assert changed == ["GEMINI_MODEL_CHAIN"]


def test_preview_is_read_only_and_install_is_atomic_with_same_permissions(tmp_path):
    path = tmp_path / "runtime.env"
    path.write_text("GEMINI_MODEL_CHAIN=a,b\nTOKEN=untouched\n")
    path.chmod(0o600)
    assert install(path) == ["GEMINI_MODEL_CHAIN"]
    assert path.read_text() == "GEMINI_MODEL_CHAIN=a,b\nTOKEN=untouched\n"
    assert install(path, apply=True) == ["GEMINI_MODEL_CHAIN"]
    assert path.read_text() == f"GEMINI_MODEL_CHAIN=a,{LITE},b\nTOKEN=untouched\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert install(path, apply=True) == []
