; QMT Gateway Windows Installer (NSIS)
; Issue #48: NSIS installer with embedded Python
;
; Prerequisites:
;   - NSIS 3.x installed (makensis in PATH)
;   - Python 3.13 embeddable package downloaded to installer\python-3.13-embed-amd64.zip
;
; Build: makensis installer\installer.nsi

Unicode True
!define PRODUCT_NAME "迅投 QMT 交易网关"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "quantclaws"
!define PRODUCT_WEB_SITE "https://github.com/quantclaws/qmt-gateway"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\qmt-gateway.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"
!define PRODUCT_STARTMENU_REGVAL "NSIS:StartMenuDir"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

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

; Finish page - text strings set per-language in .onInit
!define MUI_FINISHPAGE_RUN "$INSTDIR\start.bat"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION "OpenBrowser"
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
OutFile "QMT-Gateway-Setup-${PRODUCT_VERSION}.exe"
InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
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
    ; Set finish page text per language (avoid inline Unicode in compiled binary)
    ${If} $LANGUAGE == ${LANG_SIMPCHINESE}
        StrCpy $MUI_FINISHPAGE_RUN_TEXT "立即启动 ${PRODUCT_NAME}"
        StrCpy $MUI_FINISHPAGE_SHOWREADME_TEXT "在浏览器中打开 ${PRODUCT_NAME}"
    ${Else}
        StrCpy $MUI_FINISHPAGE_RUN_TEXT "Launch ${PRODUCT_NAME}"
        StrCpy $MUI_FINISHPAGE_SHOWREADME_TEXT "Open ${PRODUCT_NAME} in browser"
    ${EndIf}
    ; Override welcome text
    ${If} $LANGUAGE == ${LANG_SIMPCHINESE}
        MessageBox MB_OK|MB_ICONINFORMATION "$(WELCOME_TEXT)"
    ${Else}
        MessageBox MB_OK|MB_ICONINFORMATION "$(WELCOME_TEXT)"
    ${EndIf}
FunctionEnd

; Components - use English section names (NSIS limitation), descriptions are localized
Section "!Core" SEC_CORE
    SectionIn RO
    SetOutPath "$INSTDIR"
    SetOverwrite on

    ; Create directories
    CreateDirectory "$INSTDIR\python"
    CreateDirectory "$INSTDIR\app"
    CreateDirectory "$INSTDIR\data"

    ; Extract embedded Python
    DetailPrint "正在解压内嵌 Python 3.13..."
    nsExec::ExecToLog '"$INSTDIR\python\python.exe" --version'
    ${If} ${Errors}
        ; Need to extract Python embeddable package
        DetailPrint "解压 python-3.13-embed-amd64.zip..."
        nsExec::ExecToLog 'powershell -Command "Expand-Archive -Path \'$INSTDIR\python-embed.zip\' -DestinationPath \'$INSTDIR\python\' -Force"'
    ${EndIf}

    ; Copy application source
    DetailPrint "正在复制项目源码..."
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\qmt_gateway\*.*"
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\pyproject.toml"
    File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
         "..\README.md"
    ; LICENSE file - include only if available
    ; File /r /x ".venv" /x "__pycache__" /x ".git" /x "data" /x "installer" \
    ;      "..\LICENSE"

    ; Copy startup scripts
    File "start.bat"
    File "start-silent.vbs"

    ; Create venv
    DetailPrint "正在创建 Python 虚拟环境..."
    nsExec::ExecToLog '"$INSTDIR\python\python.exe" -m venv "$INSTDIR\.venv"'

    ; Write pip.conf (国内镜像源)
    DetailPrint "正在配置 pip 国内镜像源..."
    nsExec::ExecToLog 'powershell -Command "Set-Content -Path \'$INSTDIR\.venv\pip.conf\' -Value \'[global]$\nindex-url = https://pypi.tuna.tsinghua.edu.cn/simple$\ntrusted-host = pypi.tuna.tsinghua.edu.cn\' -Encoding UTF8"'

    ; Install dependencies
    DetailPrint "正在安装 Python 依赖 (使用国内镜像源)..."
    nsExec::ExecToLog '"$INSTDIR\.venv\Scripts\pip.exe" install -e "$INSTDIR\app" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn'

    ; Shortcuts
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    CreateDirectory "$SMPROGRAMS\$ICONS_GROUP"
    CreateShortCut "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME}.lnk" "$INSTDIR\start.bat"
    CreateShortCut "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME} (静默启动).lnk" "$INSTDIR\start-silent.vbs"
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\start-silent.vbs"
    !insertmacro MUI_STARTMENU_WRITE_END
SectionEnd

Section "Autostart" SEC_AUTOSTART
    DetailPrint "正在注册开机自启任务..."
    nsExec::ExecToLog 'schtasks /create /tn "QMT Gateway" /tr "wscript.exe \"$INSTDIR\start-silent.vbs\"" /sc onlogon /rl limited /f'
SectionEnd

Section "Firewall" SEC_FIREWALL
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
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\.venv\Scripts\qmt-gateway.exe"
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

    ; Remove install directory
    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\.venv"
    RMDir /r "$INSTDIR\app"
    Delete "$INSTDIR\start.bat"
    Delete "$INSTDIR\start-silent.vbs"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$INSTDIR\${PRODUCT_NAME}.url"
    RMDir "$INSTDIR"

    ; Remove registry keys
    DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
    SetAutoClose true
SectionEnd