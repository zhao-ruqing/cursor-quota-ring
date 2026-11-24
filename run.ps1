param(
    [switch]$Probe,
    [switch]$Hidden
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Prefer pythonw for background (no console). Never spawn nested powershell loops.
$pythonw = Get-Command pythonw -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python -and -not $pythonw) {
    Write-Error "python not found. Install Python 3.10+"
    exit 1
}

$exe = if ($Hidden -and $pythonw) { $pythonw.Source } elseif ($python) { $python.Source } else { $pythonw.Source }
$argList = @("$Root\main.py")
if ($Probe) { $argList += "--probe" }

if ($Hidden -and -not $Probe) {
    # Kill previous instance from this folder
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$Root*main.py*" -or $_.CommandLine -like "*$Root*_boot.py*") } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $Root -WindowStyle Hidden
    Write-Host "cursor-quota-ring started in background (no console)"
} else {
    & $exe @argList
}
