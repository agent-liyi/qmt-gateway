"""NSIS installer script regression tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_NSI = ROOT / "installer" / "installer.nsi"
INSTALLER_PS1 = ROOT / "installer" / "install-python.ps1"


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


def test_installer_finish_page_renders_title_text_and_bitmap():
    """#69: finish page must show the localized 'Setup Complete' title, the
    success description, and the left-side decorative bitmap."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert '!define MUI_FINISHPAGE_TITLE "$(FINISH_TITLE)"' in text, (
        "Finish page must override MUI_FINISHPAGE_TITLE so the success title is visible (#69)"
    )
    assert '!define MUI_FINISHPAGE_TEXT "$(FINISH_TEXT)"' in text, (
        "Finish page must override MUI_FINISHPAGE_TEXT with the success description (#69)"
    )
    assert '!define MUI_FINISHPAGE_BITMAP "contact-us.bmp"' in text, (
        "Finish page must render the left-side decorative bitmap (#69)"
    )
    finish_title_idx = text.find("LangString FINISH_TITLE ${LANG_SIMPCHINESE}")
    finish_text_idx = text.find("LangString FINISH_TEXT ${LANG_SIMPCHINESE}")
    finish_page_idx = text.find("!insertmacro MUI_PAGE_FINISH")
    assert 0 < finish_title_idx < finish_page_idx, (
        "FINISH_TITLE LangString must be defined before MUI_PAGE_FINISH (#69/#51)"
    )
    assert 0 < finish_text_idx < finish_page_idx, (
        "FINISH_TEXT LangString must be defined before MUI_PAGE_FINISH (#69/#51)"
    )
    assert "$(^Name) 安装程序结束" in text, (
        "Finish title must use the localized '安装程序结束' wording (#69)"
    )
    assert "已经成功安装到本机" in text, (
        "Finish text must use the localized '已经成功安装到本机' wording (#69)"
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


def test_installer_lang_strings_defined_before_components_page():
    """#51: MUI_DESCRIPTION_TEXT expands to a numeric id ('1' or '1+2') if the
    LangString is not yet defined when MUI_PAGE_COMPONENTS is inserted.
    Lock the source order so the component selection page never renders
    mojibake again."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")

    lang_macro_idx = text.find('!insertmacro MUI_LANGUAGE "SimpChinese"')
    components_page_idx = text.find("!insertmacro MUI_PAGE_COMPONENTS")
    core_desc_idx = text.find("LangString DESC_SEC_CORE ${LANG_SIMPCHINESE}")
    welcome_lang_idx = text.find("LangString WELCOME_TEXT ${LANG_SIMPCHINESE}")

    assert lang_macro_idx != -1 and components_page_idx != -1, (
        "Both MUI_LANGUAGE and MUI_PAGE_COMPONENTS must be present"
    )
    assert lang_macro_idx < components_page_idx, (
        "MUI_LANGUAGE must be registered before MUI_PAGE_COMPONENTS so LangString lookups resolve"
    )
    assert welcome_lang_idx < components_page_idx, (
        "WELCOME_TEXT / INSTALL_FAILED_LOG_MESSAGE LangStrings must be defined before MUI_PAGE_COMPONENTS"
    )
    assert core_desc_idx < components_page_idx, (
        "DESC_SEC_* LangStrings must be defined before MUI_PAGE_COMPONENTS to avoid mojibake (#51)"
    )

    # No duplicate definitions of the same LangString later in the file
    core_count = text.count("LangString DESC_SEC_CORE ${LANG_SIMPCHINESE}")
    assert core_count == 1, (
        f"DESC_SEC_CORE must be defined exactly once, found {core_count} times"
    )


def test_installer_component_descriptions_use_brand_new_name():
    """#51/#59: PRODUCT_NAME must use the new 匡醍 brand. The pre-install prompt
    legitimately mentions 迅投 QMT because that is the real name of the trading
    client we depend on."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "匡醍" in text, "Installer must reference 匡醍 brand (#59)"
    assert '!define PRODUCT_NAME "匡醍 QMT 交易网关"' in text, (
        "PRODUCT_NAME must use the new 匡醍 brand (#59)"
    )
    product_name_idx = text.index('!define PRODUCT_NAME "匡醍 QMT 交易网关"')
    page_idx = text.index("!insertmacro MUI_PAGE_COMPONENTS")
    assert product_name_idx < page_idx, (
        "PRODUCT_NAME must be defined before MUI_PAGE_COMPONENTS so MUI2 sees the brand (#51/#59)"
    )


def test_installer_documents_makensis_dependency():
    """#50: developers must be able to discover the NSIS dependency from the repo."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    readme = (ROOT / "installer" / "README.md").read_text(encoding="utf-8")
    assert "makensis" in text, (
        "NSIS script must document the makensis requirement in its header"
    )
    assert "makensis" in readme, (
        "installer/README.md must describe how to install NSIS locally (#50)"
    )
    assert "choco install nsis" in readme, (
        "installer/README.md must provide a working install command for developers (#50)"
    )


def test_installer_uses_quantide_logo_as_header_image():
    """#68: top-left logo of every page must come from installer/quantide.png."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "!define MUI_HEADERIMAGE" in text, (
        "MUI_HEADERIMAGE must be enabled so the brand logo renders on every page"
    )
    assert '!define MUI_HEADERIMAGE_BITMAP "quantide.bmp"' in text, (
        "Header bitmap must be quantide.bmp (generated from quantide.png)"
    )
    assert "quantide.png" in (ROOT / "installer" / "generate-bitmaps.ps1").read_text(encoding="utf-8"), (
        "generate-bitmaps.ps1 must include quantide.png as a source image"
    )
    assert '!define MUI_ICON "quantide.ico"' in text, (
        "Installer/uninstaller icon must come from quantide.ico so the title bar shows the brand logo (#68)"
    )
    assert '!define MUI_UNICON "quantide.ico"' in text, (
        "Uninstaller icon must also use quantide.ico so uninstaller windows show the brand logo (#68)"
    )
    assert "Convert-PngToIco" in (ROOT / "installer" / "generate-bitmaps.ps1").read_text(encoding="utf-8"), (
        "generate-bitmaps.ps1 must produce quantide.ico from quantide.png (#68)"
    )


def test_installer_welcome_page_prompts_user_to_install_qmt_with_contact_qr():
    """#67: welcome page must show the pre-install QMT prompt and the contact QR."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "本软件需要配置迅投 QMT 交易客户端使用" in text, (
        "Welcome text must explain QMT must be installed first (#67)"
    )
    assert "安装本软件之前，就需要安装好 QMT" in text, (
        "Welcome text must warn that QMT is required before installation (#67)"
    )
    assert "联系我们" in text, (
        "Welcome text must mention contacting us for help (#67)"
    )
    assert '!define MUI_WELCOMEPAGE_BITMAP "contact-us.bmp"' in text, (
        "Welcome page must display the contact-us QR via MUI_WELCOMEPAGE_BITMAP (#67)"
    )
    assert "!define MUI_WELCOMEPAGE_TITLE" in text, (
        "Welcome page must override MUI_WELCOMEPAGE_TITLE so the prompt is visible"
    )
    assert "!define MUI_WELCOMEPAGE_TEXT" in text, (
        "Welcome page must override MUI_WELCOMEPAGE_TEXT with the localized prompt"
    )
    assert "cdn.jsdelivr.net/gh/zillionare/images@main/images/hot/contact-us.jpg" in text, (
        "Installer must reference the canonical CDN URL for the contact QR (#67)"
    )


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
    assert "qmt-gateway-installer.log" not in text, (
        "Installer logs must live under the chosen install directory (#65); do not mirror to C:\\Temp"
    )


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
    assert "${INSTALLER_SCRIPT_PATH}" in text and "$INSTDIR\\${INSTALLER_SCRIPT_NAME}" in text, (
        "Installer must invoke the helper from $INSTDIR so logs and helper stay under the user's install directory (#65)"
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


def test_installer_logs_reside_under_install_directory():
    """Install logs must live under the user-selected install directory (#65).

    If the installer fails before the user can select a directory, we should not
    be writing any log at all; the user is instructed to capture a screenshot.
    """
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "INSTALLER_DIAGNOSTIC_DIR" not in text, (
        "Installer must not use a hard-coded diagnostic directory like C:\\Temp"
    )
    assert "qmt-gateway-installer.log" not in text
    assert "qmt-gateway-installer.log" not in helper
    assert "qmt-gateway-extract.log" not in text
    assert "qmt-gateway-bootstrap-pip.log" not in text
    assert "qmt-gateway-install-deps.log" not in text
    assert "C:\\Temp" not in text
    assert "C:\\Temp" not in helper
    assert "DiagnosticDir" not in helper
    assert "$env:TEMP" not in helper
    assert "New-Item -ItemType Directory -Path $directory -Force" in helper, (
        "InitLogs must create $INSTDIR/python/app before writing detail logs so clean installs do not fail"
    )
    assert 'Function .onInstFailed' in text and 'INSTALL_FAILED_LOG_MESSAGE' in text, (
        "Failed installs must surface the install-directory log path to the user"
    )


def test_installer_streams_detail_output_to_install_directory():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "_extract.log" in helper
    assert "_bootstrap_pip.log" in helper
    assert "_install_deps.log" in helper
    assert "_extract.log" not in text
    assert "_bootstrap_pip.log" not in text
    assert "_install_deps.log" not in text
    assert 'Tee-Object' not in text
    assert 'Tee-Object' not in helper


def test_installer_updates_python313_pth_without_utf8_bom():
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "python313._pth" in helper
    assert "[System.IO.File]::WriteAllText($pthPath, $content, [System.Text.UTF8Encoding]::new($false))" in helper, (
        "python313._pth must be written without a BOM so embedded Python can still import encodings"
    )
    assert r"Lib\site-packages" in helper, (
        "Embedded Python must add Lib\\site-packages to python313._pth so pip-installed packages are importable"
    )
    assert r"..\app" in helper, (
        "Embedded Python ignores PYTHONPATH when python313._pth exists; add ..\\app so python -m qmt_gateway works"
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
    assert "setuptools>=68" in helper and "'wheel'" in helper, (
        "Installer must install setuptools/wheel after get-pip.py so pip can build/install dependencies if needed"
    )
    assert "qmt-gateway-requirements.txt" not in helper and "tomllib" not in helper, (
        "Dependency extraction belongs to the build workflow, not the installer runtime"
    )
    assert "requirements.txt" in helper and "'-r'" in helper and "$requirementsPath" in helper, (
        "Installer should pip install third-party dependencies from the packaged requirements file"
    )
    assert "'-e'" not in helper and "'--no-build-isolation'" not in helper, (
        "Do not editable-install the app itself; embedded Python imports the copied package via python313._pth"
    )


def test_installer_generates_requirements_at_build_time():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    generator = (ROOT / "installer" / "generate-requirements.py").read_text(encoding="utf-8")
    assert "!system" in text and "generate-requirements.py" in text, (
        "NSIS build must generate installer/requirements.txt from pyproject.toml before packaging"
    )
    assert 'File "requirements.txt"' in text, (
        "Installer must package the build-time generated requirements.txt"
    )
    assert "tomllib" in generator, (
        "Build-time generator should read dependencies from pyproject.toml"
    )
    assert "tomllib" not in helper, (
        "Installer runtime must not parse pyproject.toml to generate requirements"
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


def test_installer_preserves_qmt_gateway_package_layout():
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'SetOutPath "$INSTDIR\\app\\qmt_gateway"' in text, (
        "Installer must preserve the qmt_gateway package directory so python -m qmt_gateway works"
    )
    assert 'File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \\\n         "..\\qmt_gateway\\*.*"' in text
    assert 'SetOutPath "$INSTDIR\\app"' in text, (
        "Project metadata files should live at the app root next to pyproject.toml"
    )


def test_installer_brand_and_website_link():
    """#59 (branding) and #64 (link target) use 匡醍 + the zillionare repo URL."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "匡醍 QMT 交易网关" in text, (
        "Installer title must use 匡醍 QMT 交易网关 (#59)"
    )
    assert "迅投 QMT 交易网关" not in text, (
        "Old 迅投 brand string must no longer appear in the installer (#59)"
    )
    assert "https://github.com/zillionare/qmt-gateway" in text, (
        "Website link must point to zillionare/qmt-gateway (#64)"
    )
    assert "https://github.com/quantclaws/qmt-gateway" not in text, (
        "Old quantclaws website must be replaced (#64)"
    )

