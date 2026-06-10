# Windows Installer (NSIS)

This folder contains the NSIS-driven Windows installer for QMT Gateway.

## Build requirements

- NSIS 3.x (tested with 3.10+)
- Python 3.11+ on PATH (used to generate `requirements.txt` at compile time)
- A working tree with the `app/`, `get-pip.py` and `python-embed.zip` files staged in
  `installer/` (downloaded automatically by the GitHub Actions workflow)

## Local build

```powershell
# Install NSIS
choco install nsis -y
# Make sure makensis is on PATH for the current shell
$env:Path = "C:\Program Files (x86)\NSIS;$env:Path"

# Build the installer
cd <repo-root>
makensis /INPUTCHARSET UTF8 installer\installer.nsi
```

If `makensis` is not on PATH, the build fails with
`'makensis' is not recognized as an internal or external command` (#50).
Fix that by either installing NSIS (Chocolatey / official installer) or
appending the NSIS install dir to the current `PATH`.

## Output

The compiled installer is written to
`installer/QMT-Gateway-Setup-<version>-build<build>.exe` and uploaded by the
GitHub Actions workflow as artifact `QMT-Gateway-Installer-build<n>`.

## Helper script

`install-python.ps1` is shipped inside the installer and is invoked by NSIS
at each step (`InitLogs`, `Runtime`, `BootstrapPip`, `InstallDependencies`).
Logs are written to the user-selected install directory (`$INSTDIR\install.log`
plus `$INSTDIR\python\_*.log`); no diagnostic files are written outside of
`$INSTDIR`.
