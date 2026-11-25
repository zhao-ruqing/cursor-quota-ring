param([switch]$Remove)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "CursorQuotaRing.lnk"
$Boot = Join-Path $Root "_boot.py"

$pythonwCmd = Get-Command pythonw -ErrorAction SilentlyContinue
if ($pythonwCmd) {
    $pythonw = $pythonwCmd.Source
} else {
    $python = Get-Command python -ErrorAction Stop
    $pythonw = Join-Path (Split-Path $python.Source) "pythonw.exe"
}
if (-not (Test-Path -LiteralPath $pythonw)) { Write-Error "pythonw.exe not found" }
if (-not (Test-Path -LiteralPath $Boot)) { Write-Error "_boot.py not found: $Boot" }

foreach ($name in @("CursorQuotaRing.lnk", "CursorUsageRing.lnk")) {
    $old = Join-Path $Startup $name
    if (Test-Path -LiteralPath $old) {
        if ($Remove -or ($name -eq "CursorUsageRing.lnk")) {
            Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($Remove) {
    if (Test-Path -LiteralPath $ShortcutPath) {
        Remove-Item -LiteralPath $ShortcutPath -Force
        Write-Host "Removed autostart: $ShortcutPath"
    } else {
        Write-Host "Autostart shortcut not found"
    }
    exit 0
}

$Wsh = New-Object -ComObject WScript.Shell
$Sc = $Wsh.CreateShortcut($ShortcutPath)
$Sc.TargetPath = $pythonw
$Sc.Arguments = "`"$Boot`""
$Sc.WorkingDirectory = $Root
$Sc.WindowStyle = 7
$Sc.Description = "cursor-quota-ring Activity Bar overlay"
$Sc.Save()
Write-Host "Installed autostart: $ShortcutPath"
Write-Host "Target: $pythonw `"$Boot`""
