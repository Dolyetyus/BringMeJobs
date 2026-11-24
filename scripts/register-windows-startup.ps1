$ErrorActionPreference = "Stop"

$TaskName = "BringMeJobs"
$StartupScript = (Resolve-Path (Join-Path $PSScriptRoot "windows-startup.ps1")).Path
$WindowsIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$QuotedScriptPath = '"' + $StartupScript + '"'
$ActionArguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $QuotedScriptPath"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $ActionArguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $WindowsIdentity
$Principal = New-ScheduledTaskPrincipal `
    -UserId $WindowsIdentity `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Start the BringMeJobs dashboard, then scan career sources after 60 seconds." `
    -Force | Out-Null

Write-Output "Registered task '$TaskName' for logon of $WindowsIdentity."
