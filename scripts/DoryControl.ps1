# DoryControl.ps1 -- Windows launcher for dorycontrol.py
#
# Talk to a Chasing Dory underwater drone without the vendor app.
# Join the drone's Wi-Fi (Dory_xxxxx / 12345678) and run it.
#
#   .\scripts\DoryControl.bat --retrievemedia
#   .\scripts\DoryControl.bat --video
#   .\scripts\DoryControl.bat --telemetry
#
# THIS FILE IS A LAUNCHER, NOT AN IMPLEMENTATION. It used to be a 1376-line
# hand-written port of the macOS script, and within a week it was three days
# behind: no netcode handshake, no control, no daemon, and it still accepted
# --force/--yes/--no-scan long after those were removed. Two hand-maintained
# implementations drift, and the drift only shows up at the water where
# neither can be debugged.
#
# So the logic lives once, in scripts/dorycontrol.py, and both platforms run
# it. This file does only the genuinely platform-specific part: gather the
# network facts, put them in DORY_* environment variables, hand over.
#
# Keep it that way. If something needs fixing, fix dorycontrol.py.

$ErrorActionPreference = 'Stop'

function Show-Usage {
    # One source of truth for the option list too: ask the program itself.
    $py = Find-Python
    if ($py) {
        $env:DORY_USAGE_ONLY = '1'
        & $py (Join-Path $PSScriptRoot 'dorycontrol.py')
        Remove-Item Env:\DORY_USAGE_ONLY -ErrorAction SilentlyContinue
    } else {
        Write-Host 'DoryControl -- Chasing Dory over its private REST API'
        Write-Host 'Python 3 is required and was not found; see the message below.'
    }
}

function Find-Python {
    foreach ($c in @('python3', 'python', 'py')) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            # The Windows Store stub named python.exe exits 9009 and opens the
            # Store instead of running anything. Make it prove it works.
            try {
                $v = & $cmd.Source '-c' 'import sys; print(sys.version_info[0])' 2>$null
                if ($LASTEXITCODE -eq 0 -and $v -ge 3) { return $cmd.Source }
            } catch { }
        }
    }
    return $null
}

# --- arguments ---------------------------------------------------------------
# Parsed here only far enough to know where the log goes and what to export.
# dorycontrol.py is the authority on what each option means.
$Retrieve = ''; $Remove = 0; $Live = 0; $LiveFile = ''; $DoList = 0
$Telem = 0; $Control = 0; $Power = 40; $SelfTest = 0
$Netcode = 1; $NetcodeOnly = 0; $ControlKey = ''; $Timeout = ''
$FindLink = 0; $Probe = 0; $Diagnose = 0; $Daemon = 0; $SendCmd = ''
$DoryHost = $env:DORY_HOST; if (-not $DoryHost) { $DoryHost = '192.168.1.1' }
$Scan = 0; $Force = 1; $Yes = 1; $DebugOn = ''

$DefaultMedia = Join-Path (Get-Location).Path 'media'

$argv = @($args)
function Next-IsValue([int]$i) {
    return ($i + 1 -lt $argv.Count -and $argv[$i + 1] -notlike '-*')
}

for ($i = 0; $i -lt $argv.Count; $i++) {
    switch ($argv[$i]) {
        '--retrievemedia' {
            if (Next-IsValue $i) { $Retrieve = $argv[++$i] } else { $Retrieve = $DefaultMedia }
        }
        '--removemedia' { $Remove = 1 }
        '--video' {
            $Live = 1
            if (Next-IsValue $i) { $LiveFile = $argv[++$i] }
        }
        '--telemetry' { $Telem = 1 }
        '--control' {
            $Control = 1
            if (Next-IsValue $i) { $ControlKey = $argv[++$i] }
        }
        '--selftest'  { $SelfTest = 1 }
        '--power'     { $Power = $argv[++$i] }
        '--timeout'   { $Timeout = $argv[++$i] }
        '--list'      { $DoList = 1 }
        '--netcode'   { $NetcodeOnly = 1 }
        '--no-netcode'{ $Netcode = 0 }
        '--findlink'  { $FindLink = 1 }
        '--probe'     { $Probe = 1 }
        '--diagnose'  { $Diagnose = 1 }
        '--daemon'    { $Daemon = 1 }
        '--send'      { $SendCmd = $argv[++$i] }
        '--sock'      { $env:DORY_SOCK = $argv[++$i] }
        '--host'      { $DoryHost = $argv[++$i] }
        '--scan'      { $Scan = 1 }
        '--checkwifi' { $Force = '' }
        '--confirm'   { $Yes = '' }
        '--debug'     { $DebugOn = '1' }
        { $_ -in '-h', '--help', '--usage' } { Show-Usage; exit 0 }
        default {
            Write-Error "unknown option: $($argv[$i])" -ErrorAction Continue
            Show-Usage
            exit 2
        }
    }
}

if (-not $Retrieve -and -not $Remove -and -not $Live -and -not $DoList -and
    -not $Telem -and -not $Control -and -not $NetcodeOnly -and -not $FindLink -and
    -not $Probe -and -not $Diagnose -and -not $Daemon -and -not $SendCmd) {
    Show-Usage
    exit 2
}

# --- python ------------------------------------------------------------------
$Py = Find-Python
if (-not $Py) {
    Write-Host ''
    Write-Host 'Python 3 is required and was not found.'
    Write-Host 'Windows does not ship it. Install it from https://python.org'
    Write-Host 'or run:  winget install Python.Python.3.12'
    Write-Host 'Tick "Add python.exe to PATH" in the installer.'
    exit 2
}

$PyFile = Join-Path $PSScriptRoot 'dorycontrol.py'
if (-not (Test-Path $PyFile)) {
    Write-Host "Cannot find dorycontrol.py next to this script (expected $PyFile)"
    exit 2
}

# --- where the log goes ------------------------------------------------------
if ($Retrieve) { $LogDir = $Retrieve } else { $LogDir = $DefaultMedia }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir '_run.txt'
Add-Content -Path $Log -Value ''
Add-Content -Path $Log -Value ("== run {0} == retrieve='{1}' remove={2} live={3} list={4} telem={5}" -f `
    (Get-Date), $Retrieve, $Remove, $Live, $DoList, $Telem)

function Write-Dbg([string]$m) {
    if ($DebugOn) { [Console]::Error.WriteLine("  " + [char]0x00B7 + " $m") }
}

# --- network facts -----------------------------------------------------------
# The macOS equivalents, one for one:
#   ifconfig -l + ipconfig getifaddr  ->  Get-NetIPAddress
#   ipconfig getsummary en0           ->  netsh wlan show interfaces
#   netstat -rn -f inet               ->  Get-NetRoute 0.0.0.0/0
#   arp -an                           ->  Get-NetNeighbor / arp -a
#   ping -c 2 -t 2                    ->  ping -n 2 -w 2000
$MyIp = ''; $Iface = ''
try {
    $addrs = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
             Where-Object { $_.IPAddress -ne '127.0.0.1' -and
                            $_.PrefixOrigin -ne 'WellKnown' } |
             Sort-Object -Property SkipAsSource
    foreach ($a in $addrs) {
        Add-Content -Path $Log -Value "   iface    $($a.InterfaceAlias) $($a.IPAddress)"
        Write-Dbg "iface    $($a.InterfaceAlias) $($a.IPAddress)"
        if (-not $MyIp) { $MyIp = $a.IPAddress; $Iface = $a.InterfaceAlias }
    }
} catch {
    # Get-NetIPAddress is missing on very old builds; ipconfig always works.
    $line = (ipconfig | Select-String -Pattern 'IPv4.*: (\d+\.\d+\.\d+\.\d+)' |
             Select-Object -First 1)
    if ($line -match '(\d+\.\d+\.\d+\.\d+)') { $MyIp = $Matches[1] }
}

# Windows actually gives the SSID, unlike macOS, so the wrong-Wi-Fi check is
# better here than on the Mac.
$Ssid = ''
try {
    $w = netsh wlan show interfaces 2>$null | Select-String -Pattern '^\s*SSID\s*:\s*(.+)$'
    if ($w) { $Ssid = $w.Matches[0].Groups[1].Value.Trim() }
} catch { }

$Gw = ''
try {
    $r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
         Sort-Object RouteMetric | Select-Object -First 1
    if ($r) { $Gw = $r.NextHop }
} catch {
    $g = (ipconfig | Select-String -Pattern 'Default Gateway.*: (\d+\.\d+\.\d+\.\d+)' |
          Select-Object -First 1)
    if ($g -match '(\d+\.\d+\.\d+\.\d+)') { $Gw = $Matches[1] }
}
Add-Content -Path $Log -Value "   ssid     $(if ($Ssid) { $Ssid } else { '(unknown)' })"
Add-Content -Path $Log -Value "   gateway  $(if ($Gw) { $Gw } else { '(none)' })"

# Populate the neighbour table the same way the Mac does: broadcast ping first,
# then read what answered.
$Neighbours = ''
if ($MyIp) {
    $prefix = $MyIp.Substring(0, $MyIp.LastIndexOf('.') + 1)
    try { ping -n 2 -w 2000 "$($prefix)255" | Out-Null } catch { }
    $found = @()
    try {
        $found = Get-NetNeighbor -AddressFamily IPv4 -ErrorAction Stop |
                 Where-Object { $_.IPAddress -like "$prefix*" -and
                                $_.State -ne 'Unreachable' -and
                                $_.IPAddress -notmatch '\.(0|255)$' } |
                 Select-Object -ExpandProperty IPAddress
    } catch {
        $found = (arp -a | Select-String -Pattern "($([regex]::Escape($prefix))\d+)" -AllMatches |
                  ForEach-Object { $_.Matches } | ForEach-Object { $_.Value })
    }
    $Neighbours = ($found | Sort-Object -Unique) -join "`n"
}
Add-Content -Path $Log -Value "   arp      $($Neighbours -replace "`n", ' ')"
Write-Dbg "ssid     $(if ($Ssid) { $Ssid } else { '(unknown)' })"
Write-Dbg "gateway  $(if ($Gw) { $Gw } else { '(none)' })"
Write-Dbg "arp      $($Neighbours -replace "`n", ' ')"

# --- the firewall ------------------------------------------------------------
# The macOS application firewall silently drops inbound UDP, which cost a full
# day of debugging on 2026-08-24 -- 6843 video packets on the wire while the
# socket bound to that port reported silence. Windows Defender Firewall does
# the same thing, but it prompts on first use instead of failing silently, and
# it is per-application rather than global.
#
# So this does NOT disable anything: no equivalent of the Mac's global toggle
# is appropriate here, and turning a Windows firewall profile off is a much
# bigger hammer. It warns instead, because a blocked inbound port looks exactly
# like a drone that is not sending.
if ($Live -or $Telem -or $Control -or $Probe -or $Diagnose -or $FindLink -or $Daemon) {
    Write-Dbg 'This mode listens on a UDP port.'
    Write-Dbg 'If Windows prompts to allow Python on this network, say YES --'
    Write-Dbg 'and tick Private networks. Blocked inbound UDP looks exactly'
    Write-Dbg 'like a silent drone.'
}

# --- hand over ---------------------------------------------------------------
$env:DORY_LOG = $Log
$env:DORY_MYIP = $MyIp
$env:DORY_GW = $Gw
$env:DORY_SSID = $Ssid
$env:DORY_NEIGHBOURS = $Neighbours
$env:DORY_HOST = $DoryHost
$env:DORY_SCAN = "$Scan"
$env:DORY_FORCE = "$Force"
$env:DORY_YES = "$Yes"
$env:DORY_RETRIEVE = $Retrieve
$env:DORY_REMOVE = "$Remove"
$env:DORY_LIVE = "$Live"
$env:DORY_LIVEFILE = $LiveFile
$env:DORY_LIST = "$DoList"
$env:DORY_TELEM = "$Telem"
$env:DORY_DEBUG = $DebugOn
$env:DORY_CONTROL = "$Control"
$env:DORY_POWER = "$Power"
$env:DORY_SELFTEST = "$SelfTest"
$env:DORY_NETCODE = "$Netcode"
$env:DORY_NETCODE_ONLY = "$NetcodeOnly"
$env:DORY_CONTROL_KEY = $ControlKey
$env:DORY_TIMEOUT = $Timeout
$env:DORY_FINDLINK = "$FindLink"
$env:DORY_PROBE = "$Probe"
$env:DORY_DIAGNOSE = "$Diagnose"
$env:DORY_DAEMON = "$Daemon"
$env:DORY_SENDCMD = $SendCmd

& $Py $PyFile
exit $LASTEXITCODE
