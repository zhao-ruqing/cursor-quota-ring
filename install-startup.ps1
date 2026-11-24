param([switch]$Remove)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "CursorQuotaRing.lnk"

if ($Remove) {
    if (Test-Path $ShortcutPath) {
        Remove-Item $ShortcutPath -Force
        Write-Host "已移除开机启动: $ShortcutPath"
    } else {
        Write-Host "未找到开机启动项"
    }
    exit 0
}

$Wsh = New-Object -ComObject WScript.Shell
$Sc = $Wsh.CreateShortcut($ShortcutPath)
$Sc.TargetPath = "powershell.exe"
$Sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Root\run.ps1`" -Hidden"
$Sc.WorkingDirectory = $Root
$Sc.WindowStyle = 7
$Sc.Description = "cursor-quota-ring — Activity Bar overlay"
$Sc.Save()
Write-Host "已写入开机启动: $ShortcutPath"
