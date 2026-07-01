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
    """#69 / #72 / #73: finish page must show the localized 'Setup Complete'
    title and success description, and the left-side decorative bitmap comes
    from MUI_WELCOMEFINISHPAGE_BITMAP (the official MUI2 macro for the
    shared 109x193 welcome/finish bitmap slot).

    The title/text are preprocessor !defines (set by MUI_DEFAULT inside
    LangSimpChinese.nsh) that we override after !insertmacro MUI_LANGUAGE
    so they survive the page callback's SendMessage WM_SETTEXT."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert '!define MUI_WELCOMEFINISHPAGE_BITMAP "contact-us.bmp"' in text, (
        "Finish page bitmap comes from MUI_WELCOMEFINISHPAGE_BITMAP (#72/#73)"
    )
    assert "!define MUI_FINISHPAGE_BITMAP" not in text, (
        "MUI_FINISHPAGE_BITMAP is not the MUI2 macro - the bitmap is shared with the welcome page via MUI_WELCOMEFINISHPAGE_BITMAP"
    )
    assert '!define MUI_TEXT_FINISH_INFO_TITLE "$(^Name) 安装程序结束"' in text, (
        "Finish page title must use the MUI_TEXT_FINISH_INFO_TITLE define with localized '安装程序结束' wording (#69)"
    )
    assert "已经成功安装到本机" in text, (
        "Finish text must use the localized '已经成功安装到本机' wording (#69)"
    )


def test_installer_contact_qr_source_is_png_not_jpg():
    """#74: the welcome/finish left-side artwork is generated from contact-us.png
    (a 704x1280 PNG with aspect 0.55). The target BMP is 109x193 to match the
    MUI2 left-side bitmap slot (aspect 0.56); Convert-ImageToBmp draws the
    QR at its native aspect ratio and centers it with negligible margin so
    the QR is not squashed into a different shape (#74)."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    generator = (ROOT / "installer" / "generate-bitmaps.ps1").read_text(encoding="utf-8")
    assert 'Convert-ImageToBmp -Source "contact-us.png"' in generator, (
        "generate-bitmaps.ps1 must read the QR from contact-us.png, not contact-us.jpg (#74)"
    )
    assert 'Convert-ImageToBmp -Source "contact-us.png" -Destination "contact-us.bmp" -Width 109 -Height 193' in generator, (
        "generate-bitmaps.ps1 must render the BMP at 109x193 to match the MUI2 left-side slot (#74)"
    )
    assert 'contact-us.jpg' not in generator, (
        "Stale contact-us.jpg reference in generate-bitmaps.ps1 (#74)"
    )
    png_path = ROOT / "installer" / "contact-us.png"
    assert png_path.is_file(), (
        f"contact-us.png must exist at {png_path} (#74)"
    )
    assert not (ROOT / "installer" / "contact-us.jpg").exists(), (
        "contact-us.jpg must be removed once contact-us.png replaces it (#74)"
    )
    import struct
    raw = png_path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "contact-us.png must be a real PNG"
    width = struct.unpack(">I", raw[16:20])[0]
    height = struct.unpack(">I", raw[20:24])[0]
    assert height >= width, (
        f"contact-us.png must be taller than wide (got {width}x{height}) so the "
        "QR keeps its native aspect when scaled into the 109x193 BMP (#74)"
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
    import re

    lang_macro_idx = text.find('!insertmacro MUI_LANGUAGE "SimpChinese"')
    components_page_match = re.search(r'^\s*!insertmacro MUI_PAGE_COMPONENTS\s*$', text, re.M)
    components_page_idx = components_page_match.start() if components_page_match else -1
    core_desc_idx = text.find("LangString DESC_SEC_CORE ${LANG_SIMPCHINESE}")
    welcome_title_idx = text.find("!define MUI_TEXT_WELCOME_INFO_TITLE")

    assert lang_macro_idx != -1 and components_page_idx != -1, (
        "Both MUI_LANGUAGE and MUI_PAGE_COMPONENTS must be present"
    )
    # MUI_LANGUAGE is intentionally placed AFTER all MUI_PAGE_* macros so
    # that mui.FinishPage.GUIInit (registered by MUI_PAGE_FINISH) is alive
    # when .onGUIInit is generated. The page-text overrides (now
    # !define MUI_TEXT_*_*) come right after MUI_LANGUAGE.
    assert lang_macro_idx > components_page_idx, (
        "MUI_LANGUAGE must be registered AFTER all MUI_PAGE_* macros so the "
        "finish-page left bitmap GUIInit callback survives (#73)"
    )
    assert welcome_title_idx != -1 and welcome_title_idx > lang_macro_idx, (
        "MUI_TEXT_WELCOME_INFO_TITLE must be defined as a !define after MUI_LANGUAGE so "
        "LANG_SIMPCHINESE is in scope (#72/#73)"
    )
    assert core_desc_idx != -1 and core_desc_idx < components_page_idx, (
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


def test_installer_drops_quantide_logo_from_title_bar_and_header():
    """#71: the user explicitly asked to drop the quantide brand logo from the
    title bar, taskbar, and wizard header. quantide.png is a square stamp and
    turns into a blurry red rectangle when stretched into the installer's icon
    slots. We let NSIS use its default icon everywhere instead."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "!define MUI_HEADERIMAGE" not in text, (
        "MUI_HEADERIMAGE must stay disabled; quantide.png is a square stamp and "
        "turns into a blurry red rectangle when stretched into the header strip"
    )
    assert "MUI_HEADERIMAGE_BITMAP" not in text, (
        "No header bitmap reference allowed; the wizard has no decorative header"
    )
    assert 'MUI_ICON "quantide.ico"' not in text, (
        "Title-bar icon must use NSIS default; the quantide stamp renders as a "
        "blurry red square on the title bar (#71)"
    )
    assert 'MUI_UNICON "quantide.ico"' not in text, (
        "Uninstaller icon must use NSIS default for the same reason (#71)"
    )
    assert "Convert-PngToIco" not in (ROOT / "installer" / "generate-bitmaps.ps1").read_text(encoding="utf-8"), (
        "quantide.ico is no longer used; generate-bitmaps.ps1 must not produce it"
    )


def test_installer_no_language_picker_for_chinese_only_install():
    """#70: the installer ships only SimpChinese. MUI_LANGDLL_DISPLAY would still
    pop a single-entry language picker, which is pointless and confusing."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "MUI_LANGDLL_DISPLAY" not in text, (
        "Do not call MUI_LANGDLL_DISPLAY - we ship only one language table"
    )
    assert '!insertmacro MUI_LANGUAGE "English"' not in text, (
        "Installer must not register the English language table"
    )
    assert 'LangString WELCOME_TEXT ${LANG_ENGLISH}' not in text, (
        "Do not provide an English WELCOME_TEXT - users see only the registered tables"
    )
    assert "This software requires the Xuntou QMT" not in text, (
        "Welcome text must not contain the English paragraph - users asked to drop it"
    )


def test_installer_extracts_python_embed_via_native_tar():
    """PowerShell5.1's Expand-Archive intermittently fails with 'Cannot access path'
    under CJK install paths and silently returns 0, leaving the next stage with no
    python.exe. The installer must extract python-embed.zip via the built-in
    Windows tar.exe (ships with Windows 10 1803+ / Server 2019+) and let PowerShell
    only patch python313._pth."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    helper = INSTALLER_PS1.read_text(encoding="utf-8")
    assert "tar -xf" in text, (
        "Installer must extract python-embed.zip via the built-in tar.exe"
    )
    assert "ZipDLL::Extract" not in text, (
        "ZipDLL is not part of the default NSIS 3.x install - avoid relying on it"
    )
    assert "Expand-Archive -Path $zipPath" not in helper, (
        "PowerShell helper must not call Expand-Archive - extraction is the installer's job"
    )
    assert "python313._pth" in helper, (
        "PowerShell helper still owns the python313._pth normalization"
    )


def test_installer_welcome_page_prompts_user_to_install_qmt_with_contact_qr():
    """#67 / #70 / #71 / #72 / #73: welcome page must show the pre-install QMT
    prompt and the contact-us QR on the left. MUI2's left-side bitmap is
    controlled by MUI_WELCOMEFINISHPAGE_BITMAP, and the page title/subtitle/
    body are preprocessor !defines (MUI_TEXT_WELCOME_INFO_TITLE etc.) that
    we override AFTER !insertmacro MUI_LANGUAGE so they survive until the
    page callback's SendMessage WM_SETTEXT runs."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert "本软件需要配置迅投 QMT 交易客户端使用" in text, (
        "Welcome text must explain QMT must be installed first (#67)"
    )
    assert '!define MUI_WELCOMEFINISHPAGE_BITMAP "contact-us.bmp"' in text, (
        "Welcome page must use MUI_WELCOMEFINISHPAGE_BITMAP for the contact-us QR (#72)"
    )
    assert "!define MUI_WELCOMEPAGE_BITMAP" not in text, (
        "MUI_WELCOMEPAGE_BITMAP does not exist in MUI2 - use MUI_WELCOMEFINISHPAGE_BITMAP instead"
    )
    assert '!define MUI_TEXT_WELCOME_INFO_TITLE "请先安装 QMT 交易客户端"' in text, (
        "Welcome page must override MUI_TEXT_WELCOME_INFO_TITLE with the localized title (#72/#73)"
    )
    assert "!define MUI_TEXT_WELCOME_INFO_SUBTITLE" in text, (
        "Welcome page must override MUI_TEXT_WELCOME_INFO_SUBTITLE for the localized subtitle (#72)"
    )
    assert "!define MUI_TEXT_WELCOME_INFO_TEXT" in text, (
        "Welcome page must override MUI_TEXT_WELCOME_INFO_TEXT for the localized body (#72)"
    )
    assert "Xuntou QMT" not in text, (
        "Welcome text must not contain the English Xuntou QMT paragraph (#70)"
    )
    assert "This software requires" not in text, (
        "Welcome text must not contain any English sentence (#70)"
    )
    assert "ApplySpacedWelcomePageText" not in text, (
        "The 10pt-font hack for the welcome body was removed - MUI2 ships MUI_TEXT_WELCOME_INFO_TEXT (#72)"
    )
    assert "LangString MUI_TEXT_WELCOME_INFO" not in text, (
        "MUI_TEXT_WELCOME_INFO_* are MUI2 preprocessor defines, not LangStrings; "
        "defining them as LangStrings falls back to LANG_ENGLISH and produces mojibake"
    )


def test_installer_standard_pages_have_chinese_title_and_subtitle():
    """#72 / #73: every standard MUI2 page (directory / components /
    startmenu / instfiles / finish) renders a two-row header "big title +
    small subtitle". The MUI_TEXT_*_TITLE / MUI_TEXT_*_SUBTITLE constants are
    preprocessor !defines (see MUI_DEFAULT in Interface.nsh) that we
    override AFTER !insertmacro MUI_LANGUAGE so they survive the page
    callback's SendMessage WM_SETTEXT."""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    expected_pairs = [
        ("MUI_TEXT_DIRECTORY_TITLE", "选择安装位置"),
        ("MUI_TEXT_DIRECTORY_SUBTITLE", "选择"),
        ("MUI_TEXT_COMPONENTS_TITLE", "选择安装组件"),
        ("MUI_TEXT_COMPONENTS_SUBTITLE", "勾选"),
        ("MUI_TEXT_STARTMENU_TITLE", "选择开始菜单文件夹"),
        ("MUI_TEXT_STARTMENU_SUBTITLE", "开始菜单"),
        ("MUI_TEXT_INSTFILES_TITLE", "正在安装"),
        ("MUI_TEXT_INSTFILES_SUBTITLE", "安装"),
        ("MUI_TEXT_FINISH_INFO_TITLE", "安装程序结束"),
    ]
    for lang_id, snippet in expected_pairs:
        define_line = f"!define {lang_id}"
        assert define_line in text, (
            f"Installer must define {lang_id} so the page renders its Chinese title (#72/#73)"
        )
        assert snippet in text, (
            f"{lang_id} must contain the Chinese snippet {snippet!r} so the page actually shows it (#72)"
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
    assert "[ValidateSet('InitLogs', 'Runtime', 'BootstrapPip', 'InstallDependencies', 'WaitForBrowser')]" in helper


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


def test_app_assets_are_served_locally():
    """前端依赖（tailwind / htmx / daisyui）必须从本地 /static/ 提供，避开
    跨域 Tracking Prevention 拦截 localStorage 导致 htmx 历史缓存失效。

    当前用 Tailwind Play CDN（cdn.tailwindcss.com）的本地拷贝——
    ~400 KB 的 v3 JIT 运行时，与原 CDN 渲染完全一致，比 v2 预编译 CSS
    （~3 MB，缺 v3 原子类）更小更保真。
    """
    from pathlib import Path

    app_py = ROOT / "qmt_gateway" / "app.py"
    theme_py = ROOT / "qmt_gateway" / "web" / "theme.py"
    static_dir = ROOT / "qmt_gateway" / "web" / "static"

    for src in (app_py, theme_py):
        text = src.read_text(encoding="utf-8")
        assert "cdn.tailwindcss.com" not in text, (
            f"{src.name}: Tailwind must be served from local /static/"
        )
        assert "unpkg.com" not in text, (
            f"{src.name}: htmx must be served from local /static/"
        )
        assert "cdn.jsdelivr.net" not in text, (
            f"{src.name}: daisyui must be served from local /static/"
        )
        assert "/static/htmx.min.js" in text, (
            f"{src.name}: must reference local /static/htmx.min.js"
        )
        assert "/static/daisyui.min.css" in text, (
            f"{src.name}: must reference local /static/daisyui.min.css"
        )
        assert "/static/tailwind.min.js" in text, (
            f"{src.name}: must reference local /static/tailwind.min.js"
        )

    assert static_dir.is_dir(), f"Missing static assets dir: {static_dir}"


def test_fetch_static_assets_script_exists():
    """fetch-static-assets.py 由 CI 在 makensis 之前调用，把 tailwind /
    htmx / daisyui 下载到 qmt_gateway/web/static/。"""
    script = ROOT / "installer" / "fetch-static-assets.py"
    assert script.is_file(), f"Missing fetch script: {script}"
    text = script.read_text(encoding="utf-8")
    assert "unpkg.com/htmx.org" in text
    assert "daisyui" in text
    assert "cdn.tailwindcss.com" in text, (
        "fetch script must download Tailwind Play CDN (cdn.tailwindcss.com) "
        "for local v3 JIT rendering"
    )
    assert "tailwind.min.js" in text
    assert "web/static" in text


def test_ci_workflow_runs_fetch_static_assets():
    """CI 必须在 makensis 之前调用 fetch-static-assets.py，否则安装包
    里就没有 htmx.min.js / daisyui.min.css。"""
    workflow = ROOT / ".github" / "workflows" / "build-installer.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "fetch-static-assets" in text, (
        "build-installer.yml must call fetch-static-assets.py before makensis"
    )
    # 必须出现在 makensis 之前
    fetch_pos = text.find("fetch-static-assets")
    makensis_pos = text.find("makensis")
    assert fetch_pos != -1 and makensis_pos != -1
    assert fetch_pos < makensis_pos, (
        "fetch-static-assets.py must run before makensis"
    )


def test_create_shortcuts_script_exists():
    """NSIS 自带 CreateShortCut 写出的 .lnk 文件名会落到系统 ANSI 代码页，
    中文系统下显示为乱码。create-shortcuts.ps1 走 WScript.Shell 写 UTF-16 LE。
    """
    script = ROOT / "installer" / "create-shortcuts.ps1"
    assert script.is_file(), f"Missing create-shortcuts.ps1: {script}"
    text = script.read_text(encoding="utf-8-sig")
    assert "WScript.Shell" in text
    assert "CreateShortcut" in text
    # 必须包含中文名称
    assert "匡醍" in text, "Shortcut names must use the 匡醍 brand"
    assert "停止" in text, "Stop action must produce a 停止 shortcut"
    assert "卸载" in text, "Uninstall action must produce a 卸载 shortcut"


def test_tray_module_exists():
    """托盘模块：qmt_gateway.tray 提供 pystray 菜单和子进程入口。"""
    tray = ROOT / "qmt_gateway" / "tray.py"
    assert tray.is_file(), f"Missing tray module: {tray}"
    text = tray.read_text(encoding="utf-8")
    # 关键功能：菜单动作、子进程启动、读 .port
    for needle in (
        "pystray",
        "打开管理界面",
        "重启 QMT Gateway",
        "停止 QMT Gateway",
        "_kill_gateway",
        "_spawn_gateway",
        "_read_port",
        "QMT_GATEWAY_HOME",
        "taskkill",
    ):
        assert needle in text, f"tray.py missing: {needle}"


def test_icon_file_and_generator():
    """托盘图标 + 生成脚本：红底"匡"字。"""
    ico = ROOT / "installer" / "qmt-gateway.ico"
    gen = ROOT / "installer" / "generate-icon.py"
    assert ico.is_file(), f"Missing icon: {ico}"
    assert ico.stat().st_size > 0, "icon is empty"
    assert gen.is_file(), f"Missing icon generator: {gen}"
    text = gen.read_text(encoding="utf-8")
    assert "匡" in text, "Icon must use 匡 character"
    assert "D13527" in text or (209, 53, 39, 255) in text, (
        "Icon must use brand red (#D13527 or 209,53,39)"
    )


def test_installer_nsi_bundles_tray_assets():
    """托盘相关文件（图标 + 生成脚本）必须打包进安装器。"""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    assert 'File "qmt-gateway.ico"' in text, (
        "installer.nsi must bundle the tray icon"
    )
    assert 'File "generate-icon.py"' in text, (
        "installer.nsi must bundle the icon generator"
    )
    # stop.bat 已经被托盘取代，不应再打包
    assert 'File "stop.bat"' not in text, (
        "stop.bat is obsolete (tray menu handles stop)"
    )


def test_installer_nsi_no_ansi_create_shortcut():
    """# 乱码修复：installer.nsi 必须不再直接用 CreateShortCut 写开始菜单
    快捷方式（中文系统下显示乱码），改成调 create-shortcuts.ps1。"""
    text = INSTALLER_NSI.read_text(encoding="utf-8-sig")
    product_token = "${PRODUCT_NAME}"
    for line_no, line in enumerate(text.splitlines(), start=1):
        if "CreateShortCut" in line and product_token in line:
            pytest.fail(
                "installer.nsi line " + str(line_no) + ": CreateShortCut with "
                + product_token + " still present (causes garbled Chinese)"
            )
    assert "create-shortcuts.ps1" in text, (
        "installer.nsi must invoke create-shortcuts.ps1 to build start menu"
    )

