<#
.SYNOPSIS
  Attach to the phones over Wi-Fi, preferring mDNS over a hardcoded IP.

.DESCRIPTION
  Two ways a phone can be reachable over wireless:

    - Wireless debugging (Android 11+): advertised as _adb-tls-connect._tcp with a
      random port. Survives reboots while the toggle stays on. adb can find it by
      mDNS, so no IP is needed.
    - Legacy `tcpip` mode on 5555: works until reboot, then needs USB again.

  This scans mDNS first, then falls back to the last known address, and reports a
  per-device summary. Safe to run any time; it only issues `adb connect`.

.EXAMPLE
  .\tools\phone-connect.ps1
  .\tools\phone-connect.ps1 -Fallback 192.168.1.17:5555
#>
[CmdletBinding()]
param(
    [string]$Fallback = "",
    [string[]]$Match = @("SM_S9", "Infinix"),
    [switch]$KillServer
)

$ErrorActionPreference = "Continue"
$adb = if ($env:ADB_EXE) { $env:ADB_EXE } else { Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe" }
if (-not (Test-Path $adb)) { throw "adb not found at $adb (set ADB_EXE)" }

if ($KillServer) {
    & $adb kill-server | Out-Null
    Start-Sleep -Seconds 1
}

# 1. mDNS discovery: the only method that survives reboots without USB.
$mdns = & $adb mdns services 2>&1
$found = @()
foreach ($line in $mdns) {
    if ($line -match '(_adb-tls-connect\._tcp|_adb\._tcp)\s+(\S+):(\d+)') {
        $hostPort = "$($Matches[2]):$($Matches[3])"
        if ($found -notcontains $hostPort) { $found += $hostPort }
    }
}

if ($found.Count -eq 0 -and $Fallback) { $found = @($Fallback) }

if ($found.Count -eq 0) {
    "no wireless endpoint advertised."
    "on the phone: Developer options -> Wireless debugging -> ON (keep the screen awake)"
    "then plug USB once and run: adb tcpip 5555"
    exit 1
}

foreach ($hp in $found) {
    $r = & $adb connect $hp 2>&1
    "connect $hp -> $r"
}

# 2. Report what is actually usable now.
""
"=== devices ==="
& $adb devices -l | ForEach-Object {
    if ($_ -match '([A-Za-z0-9_.:-]+)\s+device\s+(.*)') {
        $serial = $Matches[1]; $rest = $Matches[2]
        $model = if ($rest -match 'model:(\S+)') { $Matches[1] } else { "?" }
        $how = if ($serial -match ':\d+$') { "wifi/tcp" } else { "usb/emu" }
        "  {0,-26} {1,-16} {2}" -f $serial, $model, $how
    }
}
