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
!define PRODUCT_VERSION "0.2.0"
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

; #67 / #68: build-time preprocessor steps.
;   - generate-requirements.py writes installer\requirements.txt from pyproject.toml.
;   - generate-bitmaps.ps1 converts quantide.png / contact-us.png to the BMP
;     format that MUI2 requires for MUI_WELCOMEFINISHPAGE_BITMAP and produces
;     quantide.ico for MUI_ICON / MUI_UNICON.
!system 'python ".\generate-requirements.py" "..\pyproject.toml" ".\requirements.txt"' = 0
!system 'powershell -NoProfile -ExecutionPolicy Bypass -File ".\generate-bitmaps.ps1"' = 0

; The NSIS built-in zip plugin is not part of the default choco NSIS 3.x
; install, so we do not rely on it. python-embed.zip is extracted with the
; built-in Windows tar.exe below.

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"


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
; #71: the user explicitly asked to drop the quantide brand logo from the
; title bar, taskbar, and wizard header. quantide.png is a square stamp that
; turns into a blurry red rectangle when stretched into the installer's
; icon/header slots, so we let NSIS use its default icon everywhere. The
; welcome page still shows contact-us.bmp (the QR) on the left and the
; install/finish pages use the standard NSIS art.
;
; #67 / #72: the welcome page and the finish page share a 109x193 left-side
; bitmap slot, drawn from MUI_WELCOMEFINISHPAGE_BITMAP. This is the official
; MUI2 macro name; MUI_WELCOMEPAGE_BITMAP does not exist. MUI loads the
; bitmap into $PLUGINSDIR\modern-wizard.bmp via File /oname and the welcome
; /finish page callbacks bind it to NSD_CreateBitmap 0u 0u 109u 193u.
; We render contact-us.bmp (180x180) and let MUI draw it scaled into the
; 109x193 slot.
!define MUI_WELCOMEFINISHPAGE_BITMAP "contact-us.bmp"

; MUI_LANGUAGE is intentionally placed AFTER all !insertmacro MUI_PAGE_*
; so that the finish page's left-side bitmap GUIInit callback
; (mui.FinishPage.GUIInit) is registered before .onGUIInit is generated
; (MUI2 inserts .onGUIInit when the first MUI_LANGUAGE expands). The
; section description LangStrings below are looked up at runtime, but
; NSIS resolves ${LANG_SIMPCHINESE} at compile time, so we pre-define it
; here so the lookup is stable before MUI_LANGUAGE is expanded.
!define LANG_SIMPCHINESE "2052"

; MUI2 standard page titles + subtitles. Each LangString id is read by
; Section descriptions MUST be LangStrings that are looked up at runtime via
; MUI_DESCRIPTION_TEXT - they have to be registered before any
; !insertmacro MUI_PAGE_COMPONENTS, otherwise MUI_DESCRIPTION_TEXT expands
; the language id to a numeric code and the component selection page
; shows mojibake instead of the description (#51).
LangString DESC_SEC_CORE ${LANG_SIMPCHINESE} "核心组件（必须安装）"
LangString DESC_SEC_AUTOSTART ${LANG_SIMPCHINESE} "开机自启（用户登录时自动启动）"
LangString DESC_SEC_FIREWALL ${LANG_SIMPCHINESE} "防火墙入站规则（允许局域网访问）"

; Failure dialog
LangString INSTALL_FAILED_LOG_MESSAGE ${LANG_SIMPCHINESE} \
    "安装失败。请查看安装目录下的 ${INSTALL_LOG_NAME}。如果尚未选择安装目录，请截屏反馈。"

; Welcome page - MUI2 reads MUI_TEXT_WELCOME_INFO_TITLE/TEXT defined above.
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

; Finish page - MUI2 reads MUI_TEXT_FINISH_INFO_TITLE/TEXT defined above.
;
; #66: the gateway is launched at logon by the scheduled task, so the "run
; now" checkbox is removed.  The browser is opened automatically by
; Section -Post once the service is reachable on http://localhost:8130,
; so the user does not have to click anything to see the gateway UI.
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看安装日志"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\${INSTALL_LOG_NAME}"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_INSTFILES

; IMPORTANT: !insertmacro MUI_LANGUAGE must come AFTER every !insertmacro
; MUI_PAGE_* / !insertmacro MUI_UNPAGE_*. MUI2 inserts .onGUIInit (and
; therefore the install-time call to mui.FinishPage.GUIInit) when the
; first MUI_LANGUAGE is expanded. If MUI_LANGUAGE runs before
; MUI_PAGE_FINISH, mui.FinishPage.GUIInit has not been registered yet and
; NSIS prunes it as dead code (warning 6010), leaving the welcome/finish
; left-side bitmap slot empty (#73).
!insertmacro MUI_LANGUAGE "SimpChinese"

; MUI2's standard page titles and subtitles are preprocessor !defines (see
; MUI_DEFAULT in Interface.nsh), not LangStrings. Override them AFTER
; !insertmacro MUI_LANGUAGE so they survive until each page callback sends
; them to the header / subtitle static controls via SendMessage WM_SETTEXT.
; Without these overrides the headers collapse to a single button-high
; strip with no subtitle row (#72).
!define MUI_TEXT_WELCOME_INFO_TITLE "请先安装 QMT 交易客户端"
!define MUI_TEXT_WELCOME_INFO_SUBTITLE "请先确认本机已经安装迅投 QMT 交易客户端，然后继续。"
!define MUI_TEXT_WELCOME_INFO_TEXT \
    "本软件需要配置迅投 QMT 交易客户端使用。在安装本软件之前，就需要安装好 QMT。请联系您的券商客服，获取 QMT 软件的下载方式。$\n$\n\
     如果需要帮助，请扫描左侧二维码联系我们。"

!define MUI_TEXT_DIRECTORY_TITLE "选择安装位置"
!define MUI_TEXT_DIRECTORY_SUBTITLE "请选择 $(^NameDA) 的安装文件夹"

!define MUI_TEXT_COMPONENTS_TITLE "选择安装组件"
!define MUI_TEXT_COMPONENTS_SUBTITLE "请勾选需要安装的可选组件"

!define MUI_TEXT_STARTMENU_TITLE "选择开始菜单文件夹"
!define MUI_TEXT_STARTMENU_SUBTITLE "请选择开始菜单中的文件夹"

!define MUI_TEXT_INSTFILES_TITLE "正在安装"
!define MUI_TEXT_INSTFILES_SUBTITLE "请稍候，正在完成 $(^NameDA) 的安装"

!define MUI_TEXT_FINISH_INFO_TITLE "$(^Name) 安装程序结束"
!define MUI_TEXT_FINISH_INFO_TEXT \
    "$(^Name) 已经成功安装到本机。$\r$\n点击『完成(F)』关闭安装程序。"

; MUI reserve files
; MUI_RESERVEFILE_INSTALLOPTIONS is not supported in MUI2
; !insertmacro MUI_RESERVEFILE_INSTALLOPTIONS

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "QMT-Gateway-Setup-${PRODUCT_VERSION}-build${BUILD_NUMBER}.exe"
InstallDir "$PROGRAMFILES64\quantide-gateway"
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin

Function .onInit
    ; Chinese-only installer. The single registered language table above is
    ; used directly; NSIS will not pop a language picker because no picker
    ; macro is invoked here.
    ;
    ; 升级安装前先把已注册的开机自启计划任务停掉——避免它在我们解压
    ; embedded Python 时拉起 start-silent.bat → python.exe 持有
    ; python313.dll 等文件，导致 tar 报 "Can't unlink already-existing
    ; object" 整个安装失败。停掉后计划任务的定义还在，install 完成
    ; 后用户可以重新启用"开机自启"组件（它会 register-task.ps1 重新注册）。
    nsExec::ExecToLog 'schtasks /end /tn "QMT Gateway" >nul 2>&1 & exit 0'
FunctionEnd

Function .onVerifyInstDir
    ; Warn if the install path contains non-ASCII characters. The scheduled
    ; task launcher (wscript + bat) cannot resolve CJK paths through ANSI
    ; filesystem APIs, so an ASCII-only path is required.
    System::Call "kernel32::WideCharToMultiByte(i 0, i 0, w '$INSTDIR', i -1, i 0, i 0, i 0, *i .r2) i .r0"
    System::Alloc $0
    Pop $1
    System::Call "kernel32::WideCharToMultiByte(i 0, i 0, w '$INSTDIR', i -1, i r1, i r0, i 0, *i .r2) i .r3"
    System::Free $1
    ${If} $2 <> 0
        MessageBox MB_OK|MB_ICONEXCLAMATION \
            "安装路径包含非 ASCII 字符（如中文），可能导致开机自启功能异常。$\n$\n建议使用纯英文路径，如: C:\Program Files\quantide-gateway"
    ${EndIf}
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
    File "scrub-stale-installs.ps1"
    !insertmacro LogInit
    !insertmacro LogStep "Core: write uninstall registry"
    ; Publish InstallLocation immediately so PowerShell child processes can
    ; recover the install path from the registry without going through NSIS
    ; string expansion (which corrupts CJK under the system ANSI code page).
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_INSTALL_STATE_KEY}" "InstallLocation" "$INSTDIR"
    ; 清理旧版本安装残留——旧版 NSIS 安装器会写 DisplayName 到注册表，但不会
    ; 在用户重装时自动清掉。如果旧 entry 的 InstallLocation 跟当前 $INSTDIR 不同
    ; （例如用户从 'C:\Program Files\ѸͶ QMT 交易网关' 升级到
    ; 'C:\Program Files\quantide-gateway'），用户从控制面板点卸载会触发
    ; "Windows 正在查找 uninstall.bat" 因为旧路径下的 uninstall.exe 已经不存在了。
    ; scrub-stale-installs.ps1 扫描 HKLM Uninstall 子键，删掉 InstallLocation 与
    ; 当前 $INSTDIR 不一致的同名 entry，并清理它们指向的残留目录。
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scrub-stale-installs.ps1" -InstallDir "$INSTDIR"'
    Delete "$INSTDIR\scrub-stale-installs.ps1"
    !insertmacro LogStep "Core: wipe stale install dir"

    ; 上一次 install 中途崩溃后可能留下半套残留文件（python.exe / .pyd / .dll
    ; 仍被进程持有，或被 TrustedInstaller / AV 接管所有者），NSIS 自带的
    ; RMDir /r 拿不动这些文件——结果后续 tar -xf 报 "Can't unlink
    ; already-existing object" 整个安装中止。先用 takeown + icacls + cmd
    ; rmdir 强制清掉 $INSTDIR（保留可能的 data 子目录除外）。如果 cmd rmdir
    ; 也因为文件锁失败，我们继续往下走——新文件会被 SetOverwrite on 覆盖，
    ; 残留的旧文件不会阻塞后续 Stage。
    nsExec::ExecToLog 'cmd.exe /c takeown /f "$INSTDIR" /a /r /d y >nul 2>&1 & icacls "$INSTDIR" /grant Administrators:F /t /c /q >nul 2>&1 & cd /d "%TEMP%" & rmdir /s /q "$INSTDIR" >nul 2>&1 & exit 0'
    SetOutPath "$INSTDIR"
    !insertmacro LogStep "Core: create install dir"
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage InitLogs'
    !insertmacro AbortOnExecFailure "Initialize install logs"
    !insertmacro LogStep "Core: create directories"

    ; Create directories
    CreateDirectory "$INSTDIR\python"
    CreateDirectory "$INSTDIR\app"
    CreateDirectory "$INSTDIR\data"

    !insertmacro LogStep "Core: copy embedded Python"
    ; Copy embedded Python distribution. RMDir MUST run before File "python-embed.zip":
    ; previous installs may leave python.exe / python313.dll etc. locked, which makes
    ; the tar extract later report "Can't unlink already-existing object" and exit 1.
    ; If we File the zip first and then RMDir, the zip gets wiped along with the
    ; old python dir, and tar then fails with "Failed to open '...python-embed.zip'".
    DetailPrint "正在释放内嵌 Python 3.13..."
    RMDir /r "$INSTDIR\python"
    SetOutPath "$INSTDIR\python"
    File "python-embed.zip"

    !insertmacro LogStep "Core: extract embedded Python"
    ; Extract python-embed.zip via the built-in Windows tar.exe (ships with
    ; Windows 10 1803+ and Server 2019+, present on every supported system).
    ; tar -xf supports zip archives and handles Unicode paths reliably,
    ; unlike PowerShell 5.1's Expand-Archive which intermittently fails with
    ; 'Cannot access path' under CJK install paths.
    nsExec::ExecToLog 'cmd.exe /c tar -xf "$INSTDIR\python\python-embed.zip" -C "$INSTDIR\python"'
    !insertmacro AbortOnExecFailure "Extract embedded Python"
    Delete "$INSTDIR\python\python-embed.zip"
    !insertmacro LogStep "Core: post-process embedded Python"
    ; Hand control to the PowerShell helper only to patch python313._pth so
    ; the embedded interpreter can import pip and our application package.
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage Runtime'
    !insertmacro AbortOnExecFailure "Post-process embedded Python"

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
    ; start.bat is retained as a manual / debug entry point that runs the
    ; gateway in a visible console window. start-silent.bat is the hidden
    ; wrapper invoked by start-silent.vbs (which the scheduled task
    ; launches at logon) - it sets the same environment as start.bat but
    ; appends stdout/stderr to logs\task-launcher.log instead of showing
    ; a console.
    File "start.bat"
    File "start-silent.bat"
    File "start-silent.vbs"
    File "wait-and-open-browser.ps1"
    File "task-template.xml"
    File "register-task.ps1"
    File "create-shortcuts.ps1"
    File "qmt-gateway.ico"
    File "generate-icon.py"

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
    ; NSIS 自带的 CreateShortCut 即便在 Unicode 模式下，写出的 .lnk
    ; 文件名也只能落到系统 ANSI 代码页，中文系统下 Start Menu / Desktop
    ; 会显示成乱码。改走 PowerShell + WScript.Shell.CreateShortcut，
    ; 通过 IShellLinkW 写 UTF-16 LE 名称。
    !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    WriteIniStr "$INSTDIR\${PRODUCT_NAME}.url" "InternetShortcut" "URL" "${PRODUCT_WEB_SITE}"
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\create-shortcuts.ps1" -InstallDir "$INSTDIR" -StartMenuDir "$ICONS_GROUP"'
    !insertmacro AbortOnExecFailure "Create start menu shortcuts"
    !insertmacro MUI_STARTMENU_WRITE_END

    !insertmacro LogStep "Core: done"
SectionEnd

Section "Autostart" SEC_AUTOSTART
    !insertmacro LogStep "Autostart: register scheduled task"
    DetailPrint "正在注册开机自启任务..."

    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\register-task.ps1" -InstallDir "$INSTDIR"'
    !insertmacro AbortOnExecFailure "Register scheduled task"

    Delete "$INSTDIR\task-template.xml"
    Delete "$INSTDIR\register-task.ps1"
    ; create-shortcuts.ps1 只在安装期用一次，之后不再需要
    Delete "$INSTDIR\create-shortcuts.ps1"
SectionEnd

Section "Firewall" SEC_FIREWALL
    !insertmacro LogStep "Firewall: add inbound rule"
    DetailPrint "正在添加防火墙入站规则..."
    ; 端口 8130-8139：覆盖 qmt_gateway.services.port.find_available_port 的整个
    ; 探测范围，避免 8130 被占用自动跳到 8131 时防火墙规则变成"放行空端口"。
    nsExec::ExecToLog 'netsh advfirewall firewall add rule name="QMT Gateway" dir=in action=allow protocol=tcp localport=8130-8139 profile=private enable=yes'
SectionEnd

; Section descriptions are defined earlier, before MUI_PAGE_COMPONENTS,
; so MUI_DESCRIPTION_TEXT can resolve the localized strings at compile time
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE} $(DESC_SEC_CORE)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_AUTOSTART} $(DESC_SEC_AUTOSTART)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_FIREWALL} $(DESC_SEC_FIREWALL)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; 全部快捷方式（启动 / 停止 / 卸载 / Website / 桌面）都由
; Core 阶段的 create-shortcuts.ps1 写，避免 NSIS CreateShortCut 在
; 中文系统下产生乱码。

Section -Post
    WriteUninstaller "$INSTDIR\uninstall.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"

    DetailPrint "正在启动 QMT Gateway..."
    Exec 'wscript.exe "$INSTDIR\start-silent.vbs"'
    !insertmacro LogLine "Gateway launch initiated (non-blocking)"

    DetailPrint "等待服务就绪，即将打开浏览器..."
    ; 通过 install-python.ps1 的 WaitForBrowser stage 完成：它会读
    ; data\home\.port 拿到 gateway 实际监听的端口（8130 被占用时可能是
    ; 8131-8139），再探活并打开浏览器。
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${INSTALLER_SCRIPT_PATH}" -Stage WaitForBrowser'
    !insertmacro AbortOnExecFailure "Wait for gateway and open browser"
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

    ; Remove shortcuts (Unicode-named, created by create-shortcuts.ps1)
    !insertmacro MUI_STARTMENU_GETFOLDER Application $ICONS_GROUP
    Delete "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\${PRODUCT_NAME} - 停止.lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\Website.lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\卸载.lnk"
    Delete "$SMPROGRAMS\$ICONS_GROUP\Uninstall.lnk"
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
    Delete "$DESKTOP\${PRODUCT_NAME}.url"
    RMDir "$SMPROGRAMS\$ICONS_GROUP"

    ; Ask about data directory
    MessageBox MB_YESNO|MB_ICONQUESTION \
        "是否删除数据目录？$\n$\n选择「否」将保留数据以便将来恢复。" \
        /SD IDNO IDYES DeleteData IDNO KeepData

    DeleteData:
        RMDir /r "$INSTDIR\data"
        RMDir /r "$APPDATA\qmt-gateway"
        DetailPrint "数据目录已删除"
        ; 把 install 目录整个删掉——单个 Delete 一个文件太慢（pip 一堆 .dist-info、
        ; .whl、site-packages 上千个文件），cmd /c rmdir /s /q 一次性系统调用搞定。
        nsExec::ExecToLog 'cmd.exe /c rmdir /s /q "$INSTDIR"'
        Goto DoneUninstall

    KeepData:
        DetailPrint "数据目录已保留"
        ; 保留 $INSTDIR\data，把其余整个删掉。先把 data 临时改名，rmdir 完再改名回来
        ; ——避免 rmdir /s /q 把 data 也带走。
        nsExec::ExecToLog 'cmd.exe /c if exist "$INSTDIR\data" (rename "$INSTDIR\data" "$INSTDIR\.data_keep" & rmdir /s /q "$INSTDIR" & rename "$INSTDIR\.data_keep" "data") else (rmdir /s /q "$INSTDIR")'
        Goto DoneUninstall

    DoneUninstall:

    ; Remove registry keys
    DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY_WOW}"
    SetAutoClose true
SectionEnd