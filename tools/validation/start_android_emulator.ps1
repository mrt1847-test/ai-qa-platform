param(
    [string]$SdkRoot = (Join-Path $env:LOCALAPPDATA 'Android/Sdk'),
    [switch]$ShowWindow
)
$ErrorActionPreference = 'Stop'
$aiqaRepo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$aiqaRoot = Join-Path $aiqaRepo '.review-work/android'
$aiqaAvdHome = Join-Path $aiqaRoot 'avd'
$aiqaAvdDir = Join-Path $aiqaAvdHome 'AIQA_API36.avd'
$aiqaAdb = Join-Path $SdkRoot 'platform-tools/adb.exe'
$aiqaEmulator = Join-Path $SdkRoot 'emulator/emulator.exe'
$aiqaImage = Join-Path $SdkRoot 'system-images/android-36/google_apis_playstore/x86_64/system.img'
foreach ($aiqaRequired in @($aiqaAdb,$aiqaEmulator,$aiqaImage)) {
    if (-not (Test-Path -LiteralPath $aiqaRequired)) { throw "Required SDK component missing: $aiqaRequired. This script does not install packages." }
}
$aiqaDevices = & $aiqaAdb devices -l
if ($LASTEXITCODE -ne 0) { throw 'ADB is unavailable.' }
if ($aiqaDevices -match '^emulator-5580\s') {
    $aiqaName = & $aiqaAdb -s emulator-5580 emu avd name
    if (($aiqaName | Select-Object -First 1).Trim() -ne 'AIQA_API36') { throw 'Port 5580 belongs to another AVD or is still booting.' }
    Write-Output 'AIQA_API36 is already running as emulator-5580.'
    return
}
New-Item -ItemType Directory -Path $aiqaAvdDir -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $aiqaAvdDir 'config.ini'))) {
    $aiqaConfig = @"
AvdId=AIQA_API36
avd.ini.displayname=AIQA Android API 36
avd.ini.encoding=UTF-8
abi.type=x86_64
hw.cpu.arch=x86_64
hw.cpu.ncore=2
hw.ramSize=1536
hw.lcd.width=720
hw.lcd.height=1600
hw.lcd.density=280
hw.keyboard=yes
hw.gpu.enabled=yes
hw.gpu.mode=host
disk.dataPartition.size=6G
image.sysdir.1=system-images\android-36\google_apis_playstore\x86_64\
tag.id=google_apis_playstore
target=android-36
fastboot.forceColdBoot=yes
fastboot.forceFastBoot=no
"@
    [IO.File]::WriteAllText((Join-Path $aiqaAvdDir 'config.ini'),$aiqaConfig,[Text.UTF8Encoding]::new($false))
}
[IO.File]::WriteAllText((Join-Path $aiqaAvdHome 'AIQA_API36.ini'),"avd.ini.encoding=UTF-8`npath=$aiqaAvdDir`ntarget=android-36`n",[Text.UTF8Encoding]::new($false))
$aiqaArguments = @('-avd','AIQA_API36','-port','5580','-no-snapshot','-no-audio','-no-boot-anim','-gpu','host','-skin','720x1600','-cores','2','-memory','1536','-camera-back','none','-camera-front','none')
if (-not $ShowWindow) { $aiqaArguments += '-no-window' }
$aiqaPreviousHome = $env:ANDROID_AVD_HOME
try {
    $env:ANDROID_AVD_HOME = $aiqaAvdHome
    $aiqaWindowStyle = if ($ShowWindow) { 'Normal' } else { 'Hidden' }
    $aiqaProcess = Start-Process -FilePath $aiqaEmulator -ArgumentList $aiqaArguments -WindowStyle $aiqaWindowStyle -RedirectStandardOutput (Join-Path $aiqaRoot 'emulator.stdout.log') -RedirectStandardError (Join-Path $aiqaRoot 'emulator.stderr.log') -PassThru
    [pscustomobject]@{EmulatorPid=$aiqaProcess.Id;Avd='AIQA_API36';Serial='emulator-5580';AvdHome=$aiqaAvdHome} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $aiqaRoot 'session.json') -Encoding utf8
    Write-Output "Started AIQA_API36 (PID $($aiqaProcess.Id)), serial emulator-5580. Wait for sys.boot_completed=1 before probing."
} finally { $env:ANDROID_AVD_HOME = $aiqaPreviousHome }
