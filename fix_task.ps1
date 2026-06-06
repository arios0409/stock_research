$task = Get-ScheduledTask -TaskName 'Hermes_DapanScan'
$task.Settings.WakeToRun = $true
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries = $false
$task.Settings.AllowHardTerminate = $true
$task.Settings.StartWhenAvailable = $true
$task.Settings.ExecutionTimeLimit = 'PT10M'
Set-ScheduledTask -InputObject $task

Write-Host "=== Updated Task Settings ==="
Get-ScheduledTask -TaskName 'Hermes_DapanScan' | Select-Object TaskName, State, @{N='WakeToRun';E={$_.Settings.WakeToRun}}, @{N='DisallowStartIfOnBatteries';E={$_.Settings.DisallowStartIfOnBatteries}}, @{N='StopIfGoingOnBatteries';E={$_.Settings.StopIfGoingOnBatteries}}, @{N='StartWhenAvailable';E={$_.Settings.StartWhenAvailable}}
