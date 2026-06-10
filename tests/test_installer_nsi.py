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
    assert '!define INSTALL_LOG_NAME "install.log"' in text
    assert 'MUI_FINISHPAGE_SHOWREADME "$INSTDIR\\${INSTALL_LOG_NAME}"' in text, (
        "Finish page must wire the '查看安装日志' checkbox to the installer log in $INSTDIR"
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
    assert 'qmt-gateway-installer.log' in text
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
    """The installer reads $INSTDIR from the Windows registry so PowerShell never
    has to deal with NSIS string encoding of CJK characters. The registry key is
    written early in the Core section so all subsequent nsExec calls can read it."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\python' not in text, (
        "Do not use -File with a script path that contains $INSTDIR"
    )
    assert "Get-ItemProperty" in text and "InstallLocation" in text, (
        "nsExec commands must read the install path from the Windows registry via Get-ItemProperty"
    )
    assert "HKLM" in text and "Uninstall" in text, (
        "Registry key must be under HKLM Uninstall path"
    )


def test_installer_powershell_uses_escaped_dollar():
    """In NSIS command strings, $$ produces a literal '$' so
    PowerShell receives intact $-variables. Bare $name would be expanded by NSIS
    to empty (or the NSIS register value), corrupting the PowerShell script and
    causing 'MissingEndParenthesisInExpression' errors at runtime."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "$$base" in text, (
        "PowerShell variables in NSIS literal strings must be escaped as $$name"
    )


def test_installer_powershell_commands_use_normal_single_quotes():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    powershell_lines = [line for line in text.splitlines() if "powershell.exe" in line]
    assert powershell_lines, "Expected installer.nsi to contain PowerShell commands"
    assert all("''" not in line for line in powershell_lines), (
        "Wrap -Command with NSIS $\\\"...$\\\" so PowerShell can keep plain single-quoted literals"
    )


def test_installer_aborts_on_critical_exec_failures():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert '!macro AbortOnExecFailure LABEL' in text, (
        "Critical nsExec steps must check and react to child-process exit codes"
    )
    assert text.count('!insertmacro AbortOnExecFailure "') >= 6, (
        "Core extraction/bootstrap/install steps must stop the installer when a child process fails"
    )


def test_installer_preserves_temp_log_for_failed_runs():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert '!define INSTALLER_DIAGNOSTIC_DIR "C:\\Temp"' in text
    assert '!define TEMP_INSTALL_LOG_BASENAME "qmt-gateway-installer.log"' in text
    assert '!define TEMP_INSTALL_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_INSTALL_LOG_BASENAME}"' in text, (
        "Installer must mirror logs to C:\\Temp so failed installs leave diagnostics in a stable location"
    )
    assert "$$tempLog = '${TEMP_INSTALL_LOG_PATH}'" in text, (
        "PowerShell child processes must append diagnostics to the fixed C:\\Temp summary log"
    )
    assert "$$env:TEMP" not in text, "Installer diagnostics should no longer be written under %TEMP%"
    assert 'Function .onInstFailed' in text and 'INSTALL_FAILED_LOG_MESSAGE' in text, (
        "Failed installs must surface the preserved temp log path to the user"
    )


def test_installer_streams_detail_output_to_dedicated_temp_logs():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'qmt-gateway-extract.log' in text
    assert 'qmt-gateway-bootstrap-pip.log' in text
    assert 'qmt-gateway-install-deps.log' in text
    assert '!define TEMP_EXTRACT_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_EXTRACT_LOG_BASENAME}"' in text
    assert '!define TEMP_BOOTSTRAP_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_BOOTSTRAP_LOG_BASENAME}"' in text
    assert '!define TEMP_INSTALL_DEPS_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_INSTALL_DEPS_LOG_BASENAME}"' in text
    assert 'Tee-Object -FilePath $$log' not in text
    assert 'Tee-Object -FilePath $$tempLog' not in text


def test_installer_updates_python313_pth_without_utf8_bom():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "python313._pth" in text
    assert "[System.IO.File]::WriteAllText($$p, $$content, [System.Text.UTF8Encoding]::new($false))" in text, (
        "python313._pth must be written without a BOM so embedded Python can still import encodings"
    )
    assert "Set-Content -LiteralPath $$p -Encoding UTF8" not in text, (
        "Do not rewrite python313._pth with PowerShell UTF8 in Windows PowerShell; it adds a BOM and breaks python313.zip lookup"
    )


def test_installer_logs_absolute_paths_in_log():
    """The installer must write the absolute install path into install.log *before*
    invoking PowerShell, so the log still contains the path even if every PowerShell
    call fails. The path is passed via Windows registry (WriteRegStr + Get-ItemProperty)
    rather than env vars, to avoid NSIS ANSI code page corruption of CJK characters."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "WriteRegStr" in text and "InstallLocation" in text, (
        "Must write InstallLocation to registry early so PowerShell can read it"
    )
    assert "Add-Content -LiteralPath" in text and "install.log" in text, (
        "install.log must be written by PowerShell with explicit UTF-8 encoding"
    )

