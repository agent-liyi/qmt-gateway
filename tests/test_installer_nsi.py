"""NSIS installer script regression tests."""

from pathlib import Path

INSTALLER_NSI = Path(__file__).resolve().parents[1] / "installer" / "installer.nsi"
INSTALLER_PS1 = Path(__file__).resolve().parents[1] / "installer" / "install-python.ps1"


def test_installer_nsi_exists():
    assert INSTALLER_NSI.is_file(), f"Missing installer script: {INSTALLER_NSI}"


def test_installer_powershell_helper_exists():
    assert INSTALLER_PS1.is_file(), f"Missing installer PowerShell helper: {INSTALLER_PS1}"


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
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\python' not in text, (
        "Do not use -File with a script path that contains $INSTDIR"
    )
    assert "${INSTALLER_SCRIPT_PATH}" in text and "C:\\Temp" in text, (
        "Installer must invoke the helper from a stable ASCII C:\\Temp path"
    )
    assert "Get-ItemProperty" in helper and "InstallLocation" in helper, (
        "PowerShell helper must read the install path from the Windows registry via Get-ItemProperty"
    )
    assert "HKLM:\\SOFTWARE\\qmt-gateway" in helper, (
        "PowerShell helper must read an ASCII registry key to avoid CJK path encoding issues"
    )


def test_installer_uses_external_powershell_helper():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "-Command" not in "\n".join(
        line for line in text.splitlines() if "powershell.exe" in line
    ), (
        "Do not put complex PowerShell bodies in NSIS -Command strings"
    )
    assert "File /oname=${INSTALLER_SCRIPT_NAME} \"install-python.ps1\"" in text
    assert '-File "${INSTALLER_SCRIPT_PATH}" -Stage InitLogs' in text
    assert '-File "${INSTALLER_SCRIPT_PATH}" -Stage Runtime' in text
    assert '-File "${INSTALLER_SCRIPT_PATH}" -Stage BootstrapPip' in text
    assert '-File "${INSTALLER_SCRIPT_PATH}" -Stage InstallDependencies' in text


def test_installer_powershell_commands_use_normal_single_quotes():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    powershell_lines = [line for line in text.splitlines() if "powershell.exe" in line]
    assert powershell_lines, "Expected installer.nsi to contain PowerShell commands"
    assert all("''" not in line for line in powershell_lines), (
        "Wrap -Command with NSIS $\\\"...$\\\" so PowerShell can keep plain single-quoted literals"
    )
    assert "[ValidateSet('InitLogs', 'Runtime', 'BootstrapPip', 'InstallDependencies')]" in helper


def test_installer_aborts_on_critical_exec_failures():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert '!macro AbortOnExecFailure LABEL' in text, (
        "Critical nsExec steps must check and react to child-process exit codes"
    )
    assert text.count('!insertmacro AbortOnExecFailure "') >= 4, (
        "Log init/runtime/bootstrap/install helper stages must stop the installer when they fail"
    )


def test_installer_preserves_temp_log_for_failed_runs():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert '!define INSTALLER_DIAGNOSTIC_DIR "C:\\Temp"' in text
    assert '!define TEMP_INSTALL_LOG_BASENAME "qmt-gateway-installer.log"' in text
    assert '!define TEMP_INSTALL_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_INSTALL_LOG_BASENAME}"' in text, (
        "Installer must mirror logs to C:\\Temp so failed installs leave diagnostics in a stable location"
    )
    assert "$TempInstallLog = Join-Path $DiagnosticDir 'qmt-gateway-installer.log'" in helper, (
        "PowerShell helper must append diagnostics to the fixed C:\\Temp summary log"
    )
    assert "$env:TEMP" not in helper, "Installer diagnostics should no longer be written under %TEMP%"
    assert 'Function .onInstFailed' in text and 'INSTALL_FAILED_LOG_MESSAGE' in text, (
        "Failed installs must surface the preserved temp log path to the user"
    )


def test_installer_streams_detail_output_to_dedicated_temp_logs():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert 'qmt-gateway-extract.log' in text
    assert 'qmt-gateway-bootstrap-pip.log' in text
    assert 'qmt-gateway-install-deps.log' in text
    assert '!define TEMP_EXTRACT_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_EXTRACT_LOG_BASENAME}"' in text
    assert '!define TEMP_BOOTSTRAP_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_BOOTSTRAP_LOG_BASENAME}"' in text
    assert '!define TEMP_INSTALL_DEPS_LOG_PATH "${INSTALLER_DIAGNOSTIC_DIR}\\${TEMP_INSTALL_DEPS_LOG_BASENAME}"' in text
    assert 'Tee-Object' not in text
    assert 'Tee-Object' not in helper


def test_installer_updates_python313_pth_without_utf8_bom():
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "python313._pth" in helper
    assert "[System.IO.File]::WriteAllText($pthPath, $content, [System.Text.UTF8Encoding]::new($false))" in helper, (
        "python313._pth must be written without a BOM so embedded Python can still import encodings"
    )
    assert "Lib\\site-packages" in helper, (
        "Embedded Python must add Lib\\site-packages to python313._pth so pip-installed packages are importable"
    )
    assert "'import site'" in helper and "'#import site'" in helper, (
        "Helper must normalize python313._pth so import site is enabled even when the embeddable zip ships it commented out"
    )
    assert "Set-Content -LiteralPath $pthPath" not in helper, (
        "Do not rewrite python313._pth with PowerShell Set-Content in Windows PowerShell; it adds a BOM and breaks python313.zip lookup"
    )


def test_installer_no_inline_powershell_dollar_risks():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    powershell_lines = [line for line in text.splitlines() if "powershell.exe" in line]
    assert all("$false" not in line for line in powershell_lines)
    assert all("LASTEXITCODE" not in line for line in powershell_lines)
    assert all("if (" not in line for line in powershell_lines)


def test_installer_avoids_last_exit_code_if_statements():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    powershell_lines = [line for line in text.splitlines() if "powershell.exe" in line]
    assert all("LASTEXITCODE" not in line for line in powershell_lines), (
        "Avoid inline LASTEXITCODE handling in NSIS PowerShell strings"
    )
    assert "$exitCode = $LASTEXITCODE" in helper


def test_installer_bootstraps_pip_before_using_it():
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "-m pip config set" not in helper, (
        "Installer must not invoke pip config before get-pip.py has installed pip"
    )
    assert "'--no-warn-script-location'" in helper and "$PipIndexUrl" in helper and "$PipTrustedHost" in helper, (
        "Bootstrap pip by running get-pip.py directly with mirror arguments"
    )
    assert "'pip'" in helper and "'install'" in helper and "$AppDir" in helper, (
        "Dependency installation should use explicit mirror flags instead of relying on preconfigured pip state"
    )


def test_installer_logs_absolute_paths_in_utf8_from_helper():
    """The helper should initialize the summary logs in UTF-8 after the install
    path is written to the registry. NSIS must avoid writing the CJK install path
    directly, because mixing ANSI and UTF-8 in the same file causes mojibake."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "WriteRegStr" in text and "InstallLocation" in text, (
        "Must write InstallLocation to registry early so PowerShell can read it"
    )
    assert 'FileWrite $0 "InstallDir=$INSTDIR$\\r$\\n"' not in text, (
        "Do not write the CJK install path from NSIS; it mixes ANSI bytes into the UTF-8 summary log"
    )
    assert 'FileWrite $0 "TempLog=${TEMP_INSTALL_LOG_PATH}$\\r$\\n"' not in text, (
        "Summary logs should be initialized by the helper instead of split across NSIS and PowerShell encodings"
    )
    assert "Set-Content -LiteralPath $InstallLog -Encoding UTF8" in helper, (
        "install.log must be initialized by PowerShell with explicit UTF-8 encoding"
    )
    assert "Set-Content -LiteralPath $TempInstallLog -Encoding UTF8" in helper, (
        "Temp installer log must be initialized by PowerShell with explicit UTF-8 encoding"
    )


def test_installer_preserves_qmt_gateway_package_layout():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'SetOutPath "$INSTDIR\\app\\qmt_gateway"' in text, (
        "Installer must preserve the qmt_gateway package directory so python -m qmt_gateway works"
    )
    assert 'File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \\\n         "..\\qmt_gateway\\*.*"' in text
    assert 'SetOutPath "$INSTDIR\\app"' in text, (
        "Project metadata files should live at the app root next to pyproject.toml"
    )

