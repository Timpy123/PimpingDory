@echo off
setlocal EnableExtensions
rem ---------------------------------------------------------------------------
rem DoryControl.bat -- Windows launcher for DoryControl.ps1
rem
rem   DoryControl.bat -> DoryControl.ps1 -> dorycontrol.py
rem
rem The .ps1 gathers the Windows network facts; dorycontrol.py holds ALL the
rem logic and is shared with the macOS script. This file exists so the tool can
rem be double-clicked or run from cmd.exe without anyone having to know about
rem execution policies.
rem
rem   DoryControl.bat --retrievemedia
rem   DoryControl.bat --retrievemedia .\media --removemedia
rem   DoryControl.bat --video
rem   DoryControl.bat --telemetry
rem   DoryControl.bat --usage
rem ---------------------------------------------------------------------------

set "PS1=%~dp0DoryControl.ps1"

if not exist "%PS1%" (
    echo Cannot find DoryControl.ps1 next to this file.
    echo Expected it at: "%PS1%"
    exit /b 2
)

if not exist "%~dp0dorycontrol.py" (
    echo Cannot find dorycontrol.py next to this file.
    echo That file holds all the logic and is shared with the macOS script.
    exit /b 2
)

rem Windows PowerShell 5.1 is present on every Windows 10/11 box and is what
rem the script targets. pwsh.exe is only a fallback for a stripped system.
rem -ExecutionPolicy Bypass applies to this process alone; it changes nothing
rem system-wide, and without it the default policy refuses to run the script.
set "PSEXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PSEXE%" set "PSEXE=powershell.exe"

"%PSEXE%" -NoProfile -NoLogo -ExecutionPolicy Bypass -File "%PS1%" %*
exit /b %ERRORLEVEL%
