<#
.SYNOPSIS
  Root toggle for the S25+ (SM-S936B): install/remove the late-load root apps without a reboot.

.DESCRIPTION
  BRImo (id.co.bri.brimo) crashes with an ArithmeticException in its Dynatrace
  instrumentation as soon as it sees any of these packages installed:

      df.root                 DirtyFrag
      com.snothin.ghostsam    GhostSam
      me.weishu.kernelsu      KernelSU manager

  IMPORTANT — one hook per boot:
  DirtyFrag's exploit hook can only fire ONCE per boot. If it reports
      "/dev/df exists but no su appeared: the hook already fired this boot"
      "ERROR - hooked earlier this boot with no su - reboot and run once"
  then the boot is spent: nothing will work until a normal reboot. Reboot, then
  run DirtyFrag exactly once (SU Manager = KernelSU, then Run exploit). Do not
  tap Ready in GhostSam first - that consumes the hook without staging su.
  Removing the apps does NOT unload the already-loaded kernel module, so root
  keeps working for the rest of the boot. That is the whole trick:

      -On   install the three APKs   (BRImo will crash while they are present)
      -Off  uninstall them           (BRImo opens normally, root stays if loaded)
      -Status  show current state without changing anything

.EXAMPLE
  .\root-mode.ps1 -On
  # root, play, then:
  .\root-mode.ps1 -Off
#>
[CmdletBinding()]
param(
    [switch]$On,
    [switch]$Off,
    [switch]$Status,
    [string]$Serial = "",
    [string]$ApkDir = ""
)

$ErrorActionPreference = "Continue"
# $PSScriptRoot is not populated while parameter defaults are evaluated.
if (-not $ApkDir) { $ApkDir = Split-Path -Parent $PSScriptRoot }
$adb = if ($env:ADB_EXE) { $env:ADB_EXE } else { Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe" }
if (-not (Test-Path $adb)) { throw "adb not found at $adb (set ADB_EXE)" }

if (-not $Serial) {
    $line = & $adb devices -l 2>&1 | Where-Object { $_ -match 'model:SM_S9' } | Select-Object -First 1
    if ($line) { $Serial = ($line -split '\s+')[0] }
    if (-not $Serial) { throw "Samsung not on ADB. Plug the cable or reconnect wireless debugging." }
}

$pkgs = @('df.root', 'com.snothin.ghostsam', 'me.weishu.kernelsu')
$apks = @(
    (Join-Path $ApkDir 'dirtyfrag-app\dist\DirtyFrag-v1.18.apk'),
    (Join-Path $ApkDir 'ghostsam\GhostSam_0.2.4.apk'),
    (Join-Path $ApkDir 'dirtyfrag-app\dist\KernelSU_samsung-v2.2.apk')
)

function Installed {
    $list = & $adb -s $Serial shell "pm list packages" 2>&1
    $pkgs | Where-Object { $list -match [regex]::Escape($_) } | Sort-Object
}
function ModuleLoaded {
    $m = & $adb -s $Serial shell "cat /proc/modules" 2>&1
    if ($m -match 'kernelsu') { "loaded" } else { "not loaded" }
}
function BrimoState {
    $procId = (& $adb -s $Serial shell "pidof id.co.bri.brimo" 2>&1) -join ''
    if ("$procId".Trim()) { "running (pid $("$procId".Trim()))" } else { "not running" }
}

switch ($true) {
    $Status {
        "serial     : $Serial"
        "root module: $(ModuleLoaded)"
        "BRImo      : $(BrimoState)"
        $inst = Installed
        if ($inst) { "packages   : $($inst -join ', ')" } else { "packages   : none installed" }
        break
    }
    $On {
        "serial : $Serial"
        $i = 0
        foreach ($apk in $apks) {
            if (-not (Test-Path $apk)) { "MISSING apk: $apk"; continue }
            $r = & $adb -s $Serial install -r $apk 2>&1 | Select-Object -Last 1
            "install $(Split-Path -Leaf $apk) -> $r"
            $i++
        }
        "installed $i apk(s). Launch GhostSam and tap the Ready card to load the module."
        "After the run: .\root-mode.ps1 -Off   (keeps root, frees BRImo)"
        break
    }
    $Off {
        "serial : $Serial"
        foreach ($p in $pkgs) {
            $r = & $adb -s $Serial uninstall $p 2>&1
            "$p -> $r"
        }
        & $adb -s $Serial shell "am force-stop id.co.bri.brimo" 2>&1 | Out-Null
        "root module: $(ModuleLoaded)   (uninstalling apps does not unload a live module)"
        break
    }
    default { "Nothing to do. Use -On, -Off or -Status." }
}


