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
    assert "!define MUI_FINISHPAGE_SHOWREADME_FUNCTION" not in text, (
        "MUI_FINISHPAGE_SHOWREADME_FUNCTION is not a real NSIS macro and breaks MUI"
    )
    assert 'MUI_FINISHPAGE_SHOWREADME "$INSTDIR\\install.log"' in text, (
        "Finish page must wire the '查看安装日志' checkbox to $INSTDIR\\install.log"
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


def test_installer_does_not_persist_install_dir_registry():
    """MUI_DIRECTORY pre-fills $INSTDIR from InstallDirRegKey. Persisting the
    install path (or anything nested) breaks subsequent reinstalls (#61)."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "InstallDirRegKey" not in text, (
        "Do not pre-fill $INSTDIR from registry - previous broken path may persist"
    )
    assert 'WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}"' not in text, (
        "Do not write App Paths entry from installer - it stores a derived path"
    )


def test_installer_bundles_python_embed_zip():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "python-embed.zip" in text, (
        "installer must include the embedded Python zip so venv creation can succeed"
    )
    assert "File \"python-embed.zip\"" in text


def test_installer_section_starts_with_setoutpath_instdir():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    core_idx = text.index('Section "-Core" SEC_CORE')
    next_section = text.index("Section \"Autostart\"", core_idx)
    core_body = text[core_idx:next_section]
    setoutpath_lines = [
        line.strip() for line in core_body.splitlines()
        if line.strip().startswith("SetOutPath")
    ]
    assert setoutpath_lines[0] == 'SetOutPath "$INSTDIR"', (
        "Core section must explicitly reset SetOutPath to $INSTDIR at the top"
    )


def test_installer_logs_each_step():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert '!insertmacro LogInit' in text
    assert '!insertmacro LogStep' in text
    assert 'install.log' in text
    assert '查看安装日志' in text


def test_installer_pip_conf_uses_native_file_writes():
    """nsExec commands are NSIS literal strings; $INSTDIR is expanded at compile time
    so the PowerShell call sees an absolute C:\\ path, not a PowerShell variable."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "Set-Content $INSTDIR" not in text or text.count("Set-Content") == text.count("Set-Content $INSTDIR"), (
        "Avoid mixing PowerShell Set-Content with literal $INSTDIR; use -Command with absolute path"
    )


def test_installer_does_not_create_venv():
    """Embedded Python does not ship venv. Installer must pip-install into the
    embedded site-packages instead of creating a .venv directory."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "-m venv" not in text, (
        "Embedded Python 3.13 zip does not include the venv module; pip-install into python\\Lib\\site-packages instead"
    )
    assert "site-packages" in text
    assert "get-pip.py" in text, (
        "Bootstrap pip with get-pip.py before pip install -e ."
    )


def test_installer_powershell_calls_pass_absolute_paths():
    """NSIS quoted strings expand $INSTDIR at compile time. nsExec commands must use
    the quoted-string form so PowerShell receives a literal absolute path."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\python' not in text, (
        "Do not use -File with a script path that contains $INSTDIR"
    )
    assert r'$\"$INSTDIR\python$\"' in text, (
        "nsExec command must use the NSIS quoted-string form so $INSTDIR is replaced at compile time"
    )


def test_installer_logs_absolute_paths_in_log():
    """The installer must write the absolute install path into install.log *before*
    invoking PowerShell, so the log still contains the path even if every PowerShell
    call fails."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'FileWrite $0 "INSTDIR=$INSTDIR$\\r$\\n"' in text, (
        "Must write INSTDIR=... into install.log before any PowerShell call"
    )
    assert 'FileWrite $0 "PYTHON_ZIP=$INSTDIR\\python\\python-embed.zip$\\r$\\n"' in text

