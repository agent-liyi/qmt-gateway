; QMT Gateway Windows Installer (NSIS)
; Issue #48: NSIS installer with embedded Python
;
; Prerequisites:
;   - NSIS 3.x installed (makensis in PATH) - see installer/README.md
;   - Python 3.11+ on PATH (used to generate installer\requirements.txt)
;   - Python 3.13 embeddable package downloaded to installer\python-embed.zip
;
; Build: makensis /INPUTCHARSET UTF8 installer\installer.nsi

Unicode True
SetCompress off
!define PRODUCT_NAME "匡醍 QMT 交易网关"
!define PRODUCT_VERSION "0.1.0"
!define BUILD_NUMBER "0"  ; Replaced by CI with github.run_number
!define PRODUCT_PUBLISHER "zillionare"
!define PRODUCT_WEB_SITE "https://github.com/zillionare/qmt-gateway"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\qmt-gateway.exe"
!define PRODUCT_DIR_REGKEY_WOW "Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\qmt-gateway.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"
!define PRODUCT_STARTMENU_REGVAL "NSIS:StartMenuDir"
!define PRODUCT_INSTALL_STATE_KEY "Software\qmt-gateway"
!define INSTALLER_SCRIPT_NAME "qmt-gateway-install-python.ps1"
!define INSTALLER_SCRIPT_PATH "$INSTDIR\${INSTALLER_SCRIPT_NAME}"
!define PIP_INDEX_URL "https://pypi.tuna.tsinghua.edu.cn/simple"
!define PIP_TRUSTED_HOST "pypi.tuna.tsinghua.edu.cn"
!define INSTALL_LOG_NAME "install.log"
!define REQUIREMENTS_NAME "requirements.txt"
!define REQUIREMENTS_PATH "${__FILEDIR__}\${REQUIREMENTS_NAME}"

; #67 / #68: build-time preprocessor steps. Run BEFORE ReserveFile so the
; generated bitmaps are present on disk.
;   - generate-requirements.py writes installer\requirements.txt from pyproject.toml.
;   - generate-bitmaps.ps1 converts quantide.png / contact-us.jpg to the BMP
;     format that MUI2 requires for MUI_WELCOMEPAGE_BITMAP and produces
;     quantide.ico for MUI_ICON / MUI_UNICON.
!system 'python ".\generate-requirements.py" "..\pyproject.toml" ".\requirements.txt"' = 0
!system 'powershell -NoProfile -ExecutionPolicy Bypass -File ".\generate-bitmaps.ps1"' = 0

; Reserve contact-us.bmp so it is available to every custom Page callback.
ReserveFile "contact-us.bmp"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "nsDialogs.nsh"
!define WM_GETCLIENTRECT "0x0083"


!macro LogInit
    FileOpen $0 "$INSTDIR\${INSTALL_LOG_NAME}" w
    FileClose $0
!macroend


!macro LogLine TEXT
    FileOpen $0 "$INSTDIR\${INSTALL_LOG_NAME}" a
    FileWrite $0 "${TEXT}$\r$\n"
    FileClose $0
!macroend


!macro LogStep LABEL
    Push $0
    Push $1
    FileOpen $0 "$INSTDIR\${INSTALL_LOG_NAME}" a
    FileWrite $0 "==== ${LABEL} ====$\r$\n"
    FileClose $0
    Pop $1
    Pop $0
!macroend


!macro AbortOnExecFailure LABEL
    Pop $1
    ${If} $1 != "0"
        !insertmacro LogLine "ERROR: ${LABEL} failed with exit code $1"
        Abort "${LABEL} failed"
    ${EndIf}
!macroend

; MUI Settings
!define MUI_ABORTWARNING
; #68: use the quantide brand icon for the installer and uninstaller
; (this is the logo the user explicitly asked for in the title bar and
; taskbar). Without MUI_ICON / MUI_UNICON NSIS falls back to its default
; globe-and-arrow icon, which is NOT our brand. quantide.png is converted
; to quantide.ico at build time by installer\generate-bitmaps.ps1.
!define MUI_ICON "quantide.ico"
!define MUI_UNICON "quantide.ico"
;
; Header image is disabled - the brand mark lives in the title bar / taskbar
; only, not as a strip on every wizard page. The welcome page custom layout
; is built with nsDialogs (see show_welcome_dialog) so we have full control
; over the left-text / right-bitmap layout.
;
; #67: contact-us QR code shown on the welcome page. The source lives at
; https://cdn.jsdelivr.net/gh/zillionare/images@main/images/hot/contact-us.jpg
; We ship a local copy in installer\contact-us.jpg; generate-bitmaps.ps1
; converts it to 280x280 installer\contact-us.bmp at build time so it
; stays sharp when displayed on the welcome page.
; !define MUI_WELCOMEFINISHPAGE_BITMAP "installer\welcome.bmp"

; #68: header image disabled - brand logo shows only in title bar / taskbar
; via MUI_ICON and MUI_UNICON. The welcome page custom layout is built with
; nsDialogs (see show_welcome_dialog) so we have full control over the
; left-text / right-bitmap layout.
;
; #67: contact-us QR code shown on the welcome page. The source lives at
; https://cdn.jsdelivr.net/gh/zillionare/images@main/images/hot/contact-us.jpg
; We ship a local copy in installer\contact-us.jpg; generate-bitmaps.ps1
; converts it to 280x280 installer\contact-us.bmp at build time so it
; stays sharp when displayed on the welcome page.

; IMPORTANT: register language tables and define every LangString BEFORE the
; MUI page macros. Otherwise MUI_DESCRIPTION_TEXT expands the language id
; to its numeric code (e.g. "1" or "1+2") and the component selection page
; shows mojibake instead of the description (#51). Chinese only - the
; installer ships only the SimpChinese language table; if the user is on
; an English system, NSIS falls back to the OS language pack and the
; built-in MUI strings still render in Chinese here.
!insertmacro MUI_LANGUAGE "SimpChinese"

; #67: pre-install prompt about QMT (Chinese only, per product decision). The
; QR code on the right of the welcome page is rendered from
; installer\contact-us.bmp inside a custom nsDialogs page (see show_welcome_dialog).
LangString WELCOME_TEXT ${LANG_SIMPCHINESE} \
    "本软件需要配置迅投 QMT 交易客户端使用。在安装本软件之前，就需要安装好 QMT。请联系您的券商客服，获得 QMT 软件下载方式。您也可以联系我们获得协助。$\n$\n\
     安装目录将由您在本向导下一步选择。"

LangString WELCOME_TITLE ${LANG_SIMPCHINESE} "请先安装 QMT 交易客户端"
LangString INSTALL_FAILED_LOG_MESSAGE ${LANG_SIMPCHINESE} \
    "安装失败。请查看安装目录下的 ${INSTALL_LOG_NAME}。如果尚未选择安装目录，请截屏反馈。"

; Section descriptions (must be defined before MUI_PAGE_COMPONENTS)
LangString DESC_SEC_CORE ${LANG_SIMPCHINESE} "核心组件（必须安装）"
LangString DESC_SEC_AUTOSTART ${LANG_SIMPCHINESE} "开机自启（用户登录时自动启动）"
LangString DESC_SEC_FIREWALL ${LANG_SIMPCHINESE} "防火墙入站规则（允许局域网访问）"

; Finish page localized text (#69)
LangString FINISH_TITLE ${LANG_SIMPCHINESE} "$(^Name) 安装程序结束"
LangString FINISH_TEXT ${LANG_SIMPCHINESE} "$(^Name) 已经成功安装到本机。$\r$\n点击『完成(F)』关闭安装程序。"

; Welcome page - custom nsDialogs page so the layout can be left-text /
; right-bitmap (the built-in MUI_WELCOME page only supports a left-side
; decorative strip, not a right-side QR code) (#67).
Page custom show_welcome_dialog leave_welcome_dialog "$(WELCOME_TITLE)"

Function show_welcome_dialog
    ; Make sure $PLUGINSDIR exists, then stage contact-us.bmp from the
    ; installer payload into it. The File directive inside this function is
    ; a compile-time payload addition that extracts at runtime when the
    ; function is called.
    InitPluginsDir
    SetOutPath $PLUGINSDIR
    File "contact-us.bmp"

    nsDialogs::Create 1018
    Pop $0
    ${If} $0 == error
        Abort
    ${EndIf}

    ; Measure the dialog's client area so we can place the QR code without
    ; cropping. nsDialogs exposes the parent HWND via the value popped from
    ; nsDialogs::Create; SendMessage with WM_GETCLIENTRECT fills a RECT in
    ; screen coordinates of the parent.
    System::Alloc 16
    Pop $1
    SendMessage $0 ${WM_GETCLIENTRECT} 0 $1
    System::Call "*$1(i.r2, i.r3, i.r4, i.r5)"  ; left, top, right, bottom
    System::Free $1
    ; $2 = left, $3 = top, $4 = right, $5 = bottom (all in dialog units)
    IntOp $4 $4 - $2
    IntOp $5 $5 - $3
    ; $4 = width, $5 = height

    ; Lay out the prompt on the left (~60% of the width) and the QR on the
    ; right (~40% of the width). The label reserves the entire right column
    ; so the prompt text never overlaps the bitmap, even if it wraps.
    ${NSD_CreateLabel} 0 0 60% 100% "$(WELCOME_TEXT)"
    Pop $1
    CreateFont $0 "$(^Font)" "10" "400"
    SendMessage $1 ${WM_SETFONT} $0 0

    ; The QR is square. Compute the largest square that fits the right 40%
    ; column AND the dialog's inner height, then offset it from the top so
    ; the QR sits roughly in the middle of the column. nsDialogs' Create*
    ; coordinates are in dialog units, but SetWindowPos works in pixels
    ; relative to the parent client area, so we re-issue a SetWindowPos to
    ; resize the control to that exact square.
    IntOp $6 $4 * 40
    IntOp $6 $6 / 100                  ; right column width
    StrCpy $7 $6                        ; square starts as column width
    ${If} $7 > $5
        StrCpy $7 $5                     ; clamp to height
    ${EndIf}
    ; 60% of the dialog width = left column width. The bitmap's top-left
    ; x is that value; the bitmap is left at 0 so it stays at the top of
    ; the right column.
    IntOp $8 $4 * 60
    IntOp $8 $8 / 100
    ${NSD_CreateBitmap} $8 0 $6 $7 ""
    Pop $2
    ${NSD_SetBitmap} $2 "$PLUGINSDIR\contact-us.bmp" $3
    ; Center the bitmap vertically inside the right column.
    IntOp $9 $5 - $7
    IntOp $9 $9 / 2
    System::Call "User32::SetWindowPos(i r2, i 0, i $8, i $9, i $6, i $7, i 0x40)"

    nsDialogs::Show
FunctionEnd

Function leave_welcome_dialog
FunctionEnd

; License page
; !insertmacro MUI_PAGE_LICENSE "LICENSE"

; Directory page
!insertmacro MUI_PAGE_DIRECTORY

; Components / Options page
!define MUI_COMPONENTSPAGE_SMALLDESC
!insertmacro MUI_PAGE_COMPONENTS

; Start menu page
var ICONS_GROUP
!define MUI_STARTMENUPAGE_DEFAULTFOLDER "${PRODUCT_NAME}"
!define MUI_STARTMENUPAGE_REGISTRY_ROOT "${PRODUCT_UNINST_ROOT_KEY}"
!define MUI_STARTMENUPAGE_REGISTRY_KEY "${PRODUCT_UNINST_KEY}"
!define MUI_STARTMENUPAGE_REGISTRY_VALUENAME "${PRODUCT_STARTMENU_REGVAL}"
!insertmacro MUI_PAGE_STARTMENU Application $ICONS_GROUP

; Instfiles page
!insertmacro MUI_PAGE_INSTFILES

; Finish page - title/text/bitmap inline (#69)
!define MUI_FINISHPAGE_TITLE "$(FINISH_TITLE)"
!define MUI_FINISHPAGE_TEXT "$(FINISH_TEXT)"
!define MUI_FINISHPAGE_BITMAP "contact-us.bmp"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 $(^Name)"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看安装日志"
!define MUI_FINISHPAGE_RUN "$INSTDIR\start.bat"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\${INSTALL_LOG_NAME}"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_INSTFILES

; MUI reserve files
; MUI_RESERVEFILE_INSTALLOPTIONS is not supported in MUI2
; !insertmacro MUI_RESERVEFILE_INSTALLOPTIONS

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "QMT-Gateway-Setup-${PRODUCT_VERSION}-build${BUILD_NUMBER}.exe"
InstallDir "$PROGRAMFILES64\${PRODUCT_NAME}"
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin

Function .onInit
    ; Chinese only - no language picker.

    ; WM_SETICON is sent later, in show_welcome_dialog, after the dialog
    ; window has actually been created. .onInit runs before any UI exists
    ; so sending WM_SETICON there has nothing to act on.
FunctionEnd

Function .onInstFailed
    MessageBox MB_OK|MB_ICONEXCLAMATION "$(INSTALL_FAILED_LOG_MESSAGE)"
FunctionEnd

; Components - use English section names (NSIS limitation), descriptions are localized
Section "-Core" SEC_CORE
    SectionIn RO
    SetOverwrite on
    SetOutPath "$INSTDIR"

    CreateDirectory "$INSTDIR"
    SetOutPath "$INSTDIR"
    File /oname=${INSTALLER_SCRIPT_NAME} "install-python.ps1"
    !insertmacro LogInit
    !insertmacro LogStep "Core: create install dir"
    !insertmacro LogStep "Core: write uninstall registry"
    ; Publish InstallLocation immediately so PowerShell child processes can
    ; recover the install path from the registry without going through NSIS
    ; string expansion (which corrupts CJK under the system ANSI code page).
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_INSTALL_STATE_KEY}" "InstallLocation" "$INSTDIR"
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage InitLogs'
    !insertmacro AbortOnExecFailure "Initialize install logs"
    !insertmacro LogStep "Core: create directories"

    ; Create directories
    CreateDirectory "$INSTDIR\python"
    CreateDirectory "$INSTDIR\app"
    CreateDirectory "$INSTDIR\data"

    !insertmacro LogStep "Core: copy embedded Python"
    ; Copy embedded Python distribution
    DetailPrint "正在释放内嵌 Python 3.13..."
    SetOutPath "$INSTDIR\python"
    File "python-embed.zip"

    !insertmacro LogStep "Core: extract embedded Python"
    SetOutPath "$INSTDIR\python"
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage Runtime'
    !insertmacro AbortOnExecFailure "Extract embedded Python"

    !insertmacro LogStep "Core: copy application source"
    ; Copy application source to $INSTDIR\app
        SetOutPath "$INSTDIR\app\qmt_gateway"
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\qmt_gateway\*.*"
        SetOutPath "$INSTDIR\app"
        File "..\pyproject.toml"
        File "..\README.md"
        File "requirements.txt"
    SetOutPath "$INSTDIR"

    !insertmacro LogStep "Core: copy startup scripts"
    ; Copy startup scripts
    File "start.bat"
    File "start-silent.vbs"

    !insertmacro LogStep "Core: bootstrap pip"
    ; Embed Python does not ship with venv/pip. Bootstrap pip with get-pip.py and
    ; install dependencies into the embedded Python's site-packages directly.
    SetOutPath "$INSTDIR\python"
    File "get-pip.py"
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage BootstrapPip'
    !insertmacro AbortOnExecFailure "Bootstrap pip"

    !insertmacro LogStep "Core: install dependencies"
    ; Install dependencies into the embedded Python's site-packages.
    DetailPrint "正在安装 Python 依赖 (使用国内镜像源)..."
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage InstallDependencies'
    !insertmacro AbortOnExecFailure "Install Python dependencies"

    !insertmacro LogStep "Core: write shortcuts"
    ; Shortcuts
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    CreateDirectory "$SMPROGRAMS\$ICONS_GROUP"
    CreateShortCut "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME}.lnk" "$INSTDIR\start.bat"
    CreateShortCut "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME} (静默启动).lnk" "$INSTDIR\start-silent.vbs"
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\start-silent.vbs"
    !insertmacro MUI_STARTMENU_WRITE_END

    !insertmacro LogStep "Core: done"
SectionEnd

Section "Autostart" SEC_AUTOSTART
    !insertmacro LogStep "Autostart: register scheduled task"
    DetailPrint "正在注册开机自启任务..."
    nsExec::ExecToLog 'schtasks /create /tn "QMT Gateway" /tr "wscript.exe \"$INSTDIR\start-silent.vbs\"" /sc onlogon /rl limited /f'
SectionEnd

Section "Firewall" SEC_FIREWALL
    !insertmacro LogStep "Firewall: add inbound rule"
    DetailPrint "正在添加防火墙入站规则..."
    nsExec::ExecToLog 'netsh advfirewall firewall add rule name="QMT Gateway" dir=in action=allow protocol=tcp localport=8130 profile=private enable=yes'
SectionEnd

; Section descriptions are defined earlier, before MUI_PAGE_COMPONENTS,
; so MUI_DESCRIPTION_TEXT can resolve the localized strings at compile time
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE} $(DESC_SEC_CORE)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_AUTOSTART} $(DESC_SEC_AUTOSTART)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_FIREWALL} $(DESC_SEC_FIREWALL)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function OpenBrowser
    ExecShell "open" "http://localhost:8130"
FunctionEnd


Section -AdditionalIcons
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    WriteIniStr "$INSTDIR\${PRODUCT_NAME}.url" "InternetShortcut" "URL" "${PRODUCT_WEB_SITE}"
    CreateShortCut "$SMPROGRAMS\$ICONS_GROUP\Website.lnk" "$INSTDIR\${PRODUCT_NAME}.url"
    CreateShortCut "$SMPROGRAMS\$ICONS_GROUP\Uninstall.lnk" "$INSTDIR\uninstall.bat"
    !insertmacro MUI_STARTMENU_WRITE_END
SectionEnd

Section -Post
    WriteUninstaller "$INSTDIR\uninstall.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
SectionEnd

; Uninstaller
Function un.onInit
    !insertmacro MUI_UNGETLANGUAGE
FunctionEnd

Section Uninstall
    ; Stop running processes
    DetailPrint "正在停止 qmt-gateway 进程..."
    nsExec::ExecToLog 'taskkill /F /IM "qmt-gateway.exe"'
    nsExec::ExecToLog 'taskkill /F /IM "python.exe" /FI "WINDOWTITLE eq QMT*"'

    ; Remove scheduled task
    DetailPrint "正在删除开机自启任务..."
    nsExec::ExecToLog 'schtasks /delete /tn "QMT Gateway" /f'

    ; Remove firewall rule
    DetailPrint "正在删除防火墙规则..."
    nsExec::ExecToLog 'netsh advfirewall firewall delete rule name="QMT Gateway"'

    ; Remove shortcuts
    !insertmacro MUI_STARTMENU_GETFOLDER Application $ICONS_GROUP
    Delete "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME} (静默启动).lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\Website.lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\Uninstall.lnk"
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
    RMDir "$SMPROGRAMS\$ICONS_GROUP"

    ; Ask about data directory
    MessageBox MB_YESNO|MB_ICONQUESTION \
        "是否删除数据目录？$\n$\n选择「否」将保留数据以便将来恢复。" \
        /SD IDNO IDYES DeleteData IDNO KeepData

    DeleteData:
        RMDir /r "$INSTDIR\data"
        RMDir /r "$APPDATA\qmt-gateway"
        DetailPrint "数据目录已删除"

    KeepData:
        DetailPrint "数据目录已保留"

    ; Remove install directory (everything except data/, which user chose above)
    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\.venv"
    RMDir /r "$INSTDIR\app"
    Delete "$INSTDIR\start.bat"
    Delete "$INSTDIR\start-silent.vbs"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$INSTDIR\${PRODUCT_NAME}.url"
    ; Clean any other top-level files (e.g. qmt_gateway sources installed at root)
    Delete "$INSTDIR\__init__.py"
    Delete "$INSTDIR\__main__.py"
    Delete "$INSTDIR\app.py"
    Delete "$INSTDIR\config.py"
    Delete "$INSTDIR\init_wizard.py"
    Delete "$INSTDIR\pyproject.toml"
    Delete "$INSTDIR\qmt_init_helpers.py"
    Delete "$INSTDIR\qmt_login_automation.py"
    Delete "$INSTDIR\qmt_restart_helper.py"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\runtime.py"
    Delete "$INSTDIR\trading.py"
    Delete "$INSTDIR\xtquant_probe.py"
    RMDir "$INSTDIR\apis"
    RMDir "$INSTDIR\core"
    RMDir "$INSTDIR\db"
    RMDir "$INSTDIR\services"
    RMDir "$INSTDIR\web"
    RMDir "$INSTDIR"

    ; Remove registry keys
    DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY_WOW}"
    SetAutoClose true
SectionEnd