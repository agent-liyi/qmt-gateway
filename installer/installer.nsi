; QMT Gateway Windows Installer (NSIS)
; Issue #48: NSIS installer with embedded Python
;
; Prerequisites:
;   - NSIS 3.x installed (makensis in PATH)
;   - Python 3.13 embeddable package downloaded to installer\python-embed.zip
;
; Build: makensis /INPUTCHARSET UTF8 installer\installer.nsi

Unicode True
SetCompress off
!define PRODUCT_NAME "迅投 QMT 交易网关"
!define PRODUCT_VERSION "0.1.0"
!define BUILD_NUMBER "0"  ; Replaced by CI with github.run_number
!define PRODUCT_PUBLISHER "quantclaws"
!define PRODUCT_WEB_SITE "https://github.com/quantclaws/qmt-gateway"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\qmt-gateway.exe"
!define PRODUCT_DIR_REGKEY_WOW "Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\qmt-gateway.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"
!define PRODUCT_STARTMENU_REGVAL "NSIS:StartMenuDir"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"


!macro LogInit
    FileOpen $0 "$INSTDIR\install.log" w
    FileWrite $0 "[Install]$\r$\n"
    FileWrite $0 "Started: $\r$\n"
    FileClose $0
!macroend


!macro LogLine TEXT
    FileOpen $0 "$INSTDIR\install.log" a
    FileWrite $0 "${TEXT}$\r$\n"
    FileClose $0
!macroend


!macro LogStep LABEL
    Push $0
    Push $1
    FileOpen $0 "$INSTDIR\install.log" a
    FileWrite $0 "==== ${LABEL} ====$\r$\n"
    FileClose $0
    Pop $1
    Pop $0
!macroend

; MUI Settings
!define MUI_ABORTWARNING
; Icon and bitmap are optional - comment out if files not available
; !define MUI_ICON "installer\icon.ico"
; !define MUI_UNICON "installer\icon.ico"
; !define MUI_WELCOMEFINISHPAGE_BITMAP "installer\welcome.bmp"

; Welcome page
!insertmacro MUI_PAGE_WELCOME

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

; Finish page - text strings inline (Unicode mode handles UTF-8 encoding)
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 $(^Name)"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看安装日志"
!define MUI_FINISHPAGE_RUN "$INSTDIR\start.bat"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\install.log"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_INSTFILES

; Language files
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; MUI reserve files
; MUI_RESERVEFILE_INSTALLOPTIONS is not supported in MUI2
; !insertmacro MUI_RESERVEFILE_INSTALLOPTIONS

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "QMT-Gateway-Setup-${PRODUCT_VERSION}-build${BUILD_NUMBER}.exe"
InstallDir "$PROGRAMFILES64\${PRODUCT_NAME}"
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin

; Custom welcome text
LangString WELCOME_TEXT ${LANG_SIMPCHINESE} \
    "本软件需要配合迅投 QMT 交易客户端使用。如果您尚未安装 QMT，请先前往券商官网下载安装。$\n$\n\
     QMT 安装路径将在初始化向导中配置。"
LangString WELCOME_TEXT ${LANG_ENGLISH} \
    "This software requires the Xuntou QMT trading client. If you haven't installed QMT, \
     please download it from your broker's website first.$\n$\n\
     The QMT installation path will be configured in the initialization wizard."

Function .onInit
    !insertmacro MUI_LANGDLL_DISPLAY
    ; Override welcome text
    ${If} $LANGUAGE == ${LANG_SIMPCHINESE}
        MessageBox MB_OK|MB_ICONINFORMATION "$(WELCOME_TEXT)"
    ${Else}
        MessageBox MB_OK|MB_ICONINFORMATION "$(WELCOME_TEXT)"
    ${EndIf}
FunctionEnd

; Components - use English section names (NSIS limitation), descriptions are localized
Section "-Core" SEC_CORE
    SectionIn RO
    SetOverwrite on
    SetOutPath "$INSTDIR"

    !insertmacro LogInit
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
    nsExec::ExecToLog 'cmd.exe /C "tar -xf "$INSTDIR\python\python-embed.zip" -C "$INSTDIR\python""'

    !insertmacro LogStep "Core: copy application source"
    ; Copy application source to $INSTDIR\app
    SetOutPath "$INSTDIR\app"
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\qmt_gateway\*.*"
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\pyproject.toml"
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\README.md"
    SetOutPath "$INSTDIR"

    !insertmacro LogStep "Core: copy startup scripts"
    ; Copy startup scripts
    File "start.bat"
    File "start-silent.vbs"

    !insertmacro LogStep "Core: create venv"
    ; Create venv
    DetailPrint "正在创建 Python 虚拟环境..."
    SetOutPath "$INSTDIR"
    nsExec::ExecToLog '"$INSTDIR\python\python.exe" -m venv "$INSTDIR\.venv"'

    !insertmacro LogStep "Core: write pip.conf"
    ; Write pip.conf (国内镜像源)
    DetailPrint "正在配置 pip 国内镜像源..."
    FileOpen $0 "$INSTDIR\.venv\pip.conf" w
    FileWrite $0 "[global]$$\nindex-url = https://pypi.tuna.tsinghua.edu.cn/simple$$\ntrusted-host = pypi.tuna.tsinghua.edu.cn"
    FileClose $0

    !insertmacro LogStep "Core: install dependencies"
    ; Install dependencies
    DetailPrint "正在安装 Python 依赖 (使用国内镜像源)..."
    nsExec::ExecToLog '"$INSTDIR\.venv\Scripts\python.exe" -m pip install -e "$INSTDIR\app" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn'

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

; Section descriptions
LangString DESC_SEC_CORE ${LANG_SIMPCHINESE} "核心组件（必须安装）"
LangString DESC_SEC_CORE ${LANG_ENGLISH} "Core components (required)"
LangString DESC_SEC_AUTOSTART ${LANG_SIMPCHINESE} "开机自启（用户登录时自动启动）"
LangString DESC_SEC_AUTOSTART ${LANG_ENGLISH} "Auto-start on login"
LangString DESC_SEC_FIREWALL ${LANG_SIMPCHINESE} "防火墙入站规则（允许局域网访问）"
LangString DESC_SEC_FIREWALL ${LANG_ENGLISH} "Firewall inbound rule (allow LAN access)"

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