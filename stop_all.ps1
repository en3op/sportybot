# SportyBot Stop Script
# Stops all running bot processes

Write-Host "Stopping all SportyBot services..." -ForegroundColor Yellow

# Kill Python processes running the bots
$BotScripts = @("free_bot.py", "bot.py", "app.py", "run_local.py")

foreach ($Script in $BotScripts) {
    $Procs = Get-WmiObject Win32_Process -Filter "CommandLine LIKE '%$Script%'" -ErrorAction SilentlyContinue
    foreach ($Proc in $Procs) {
        Write-Host "Stopping $Script (PID: $($Proc.ProcessId))" -ForegroundColor Cyan
        Stop-Process -Id $Proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "All services stopped" -ForegroundColor Green
