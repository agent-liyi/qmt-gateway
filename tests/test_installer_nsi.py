"""NSIS installer script regression tests."""

from pathlib import Path

INSTALLER_NSI = Path(__file__).resolve().parents[1] / "installer" / "installer.nsi"


def test_installer_nsi_exists():
    assert INSTALLER_NSI.is_file(), f"Missing installer script: {INSTALLER_NSI}"


def test_installer_nsi_uses_unicode_and_utf8_bom():
    raw = INSTALLER_NSI.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "installer.nsi must be saved with UTF-8 BOM"
    text = raw.decode("utf-8-sig")
    assert "Unicode True" in text, "NSIS script must enable Unicode mode"


def test_installer_finish_page_does_not_define_conflicting_readme_macro():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "!define MUI_FINISHPAGE_SHOWREADME_FUNCTION" in text
    assert 'MUI_FINISHPAGE_SHOWREADME "' not in text, (
        "MUI_FINISHPAGE_SHOWREADME and MUI_FINISHPAGE_SHOWREADME_FUNCTION are mutually exclusive"
    )


def test_installer_uses_64bit_program_files():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'InstallDir "$PROGRAMFILES64' in text, (
        "InstallDir must use $PROGRAMFILES64 to avoid 32-bit Program Files (x86) on 64-bit OS"
    )


def test_installer_components_section_descriptions_present():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "LangString DESC_SEC_CORE ${LANG_SIMPCHINESE}" in text
    assert "LangString DESC_SEC_AUTOSTART ${LANG_SIMPCHINESE}" in text
    assert "LangString DESC_SEC_FIREWALL ${LANG_SIMPCHINESE}" in text


def test_ci_workflow_writes_nsi_with_bom():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-installer.yml"
    )
    text = workflow.read_text(encoding="utf-8")
    assert "New-Object System.Text.UTF8Encoding $true" in text, (
        "CI must write installer.nsi with UTF-8 BOM so mui2 langfile is read correctly"
    )
