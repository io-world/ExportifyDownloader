param(
    [Parameter(Mandatory = $false)]
    [string]$ConfigPath = ".\\downloader.config.json",

    [Parameter(Mandatory = $false)]
    [string]$CsvPath = "",

    [Parameter(Mandatory = $false)]
    [string]$CsvFolder = ".\\exportify.app",

    [Parameter(Mandatory = $false)]
    [int]$DurationTolerance = 10,

    [Parameter(Mandatory = $false)]
    [int]$SearchResults = 6,

    [Parameter(Mandatory = $false)]
    [switch]$ForceRedownload,

    [Parameter(Mandatory = $false)]
    [int]$Limit = 0,

    [Parameter(Mandatory = $false)]
    [double]$SleepRequests = 1.0,

    [Parameter(Mandatory = $false)]
    [string]$LimitRate = "",

    [Parameter(Mandatory = $false)]
    [string]$ThrottledRate = "",

    [Parameter(Mandatory = $false)]
    [double]$SleepInterval = 0,

    [Parameter(Mandatory = $false)]
    [double]$MaxSleepInterval = 0,

    [Parameter(Mandatory = $false)]
    [ValidateSet("default", "ascending", "descending")]
    [string]$TrackOrder = "default",

    [Parameter(Mandatory = $false)]
    [string]$CookiesFromBrowser = "",

    [Parameter(Mandatory = $false)]
    [string]$CookiesFile = ""
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $scriptDir "spotify_csv_yt_dlp.py"
$pythonPath = Join-Path $scriptDir ".venv\Scripts\python.exe"
$defaultCookiesPath = Join-Path $scriptDir "music youtube cookies.txt"
$cliBoundParams = @{}
foreach ($entry in $PSBoundParameters.GetEnumerator()) {
    $cliBoundParams[$entry.Key] = $entry.Value
}

function Set-FromConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $false)]
        [object]$Value
    )

    if ($null -eq $Value) {
        return
    }

    if (-not $cliBoundParams.ContainsKey($Name)) {
        Set-Variable -Name $Name -Value $Value -Scope Script
    }
}

if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $scriptDir $ConfigPath
}

if (Test-Path $ConfigPath) {
    try {
        $config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    }
    catch {
        throw "Invalid config JSON at $ConfigPath. $_"
    }

    Set-FromConfig -Name "CsvPath" -Value $config.CsvPath
    Set-FromConfig -Name "CsvFolder" -Value $config.CsvFolder
    Set-FromConfig -Name "DurationTolerance" -Value $config.DurationTolerance
    Set-FromConfig -Name "SearchResults" -Value $config.SearchResults
    Set-FromConfig -Name "Limit" -Value $config.Limit
    Set-FromConfig -Name "SleepRequests" -Value $config.SleepRequests
    Set-FromConfig -Name "LimitRate" -Value $config.LimitRate
    Set-FromConfig -Name "ThrottledRate" -Value $config.ThrottledRate
    Set-FromConfig -Name "SleepInterval" -Value $config.SleepInterval
    Set-FromConfig -Name "MaxSleepInterval" -Value $config.MaxSleepInterval
    Set-FromConfig -Name "TrackOrder" -Value $config.TrackOrder
    Set-FromConfig -Name "CookiesFromBrowser" -Value $config.CookiesFromBrowser
    Set-FromConfig -Name "CookiesFile" -Value $config.CookiesFile

    if (-not $cliBoundParams.ContainsKey("ForceRedownload") -and $null -ne $config.ForceRedownload) {
        $ForceRedownload = [bool]$config.ForceRedownload
    }
}

if (-not (Test-Path $pythonPath)) {
    throw "Python virtual environment not found at $pythonPath"
}

function Invoke-CsvDownload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetCsvPath,
        [Parameter(Mandatory = $false)]
        [int]$CurrentIndex = 0,
        [Parameter(Mandatory = $false)]
        [int]$TotalCount = 0
    )

    $arguments = @(
        $scriptPath,
        $TargetCsvPath,
        "--duration-tolerance", $DurationTolerance,
        "--search-results", $SearchResults,
        "--limit", $Limit,
        "--sleep-requests", $SleepRequests,
        "--sleep-interval", $SleepInterval,
        "--max-sleep-interval", $MaxSleepInterval,
        "--track-order", $TrackOrder
    )

    if ($LimitRate -ne "") {
        $arguments += @("--limit-rate", $LimitRate)
    }

    if ($ThrottledRate -ne "") {
        $arguments += @("--throttled-rate", $ThrottledRate)
    }

    if ($ForceRedownload) {
        $arguments += "--force-redownload"
    }

    if ($CookiesFromBrowser -ne "") {
        $arguments += @("--cookies-from-browser", $CookiesFromBrowser)
    }

    if ($CookiesFile -ne "") {
        $cookiesCandidate = $CookiesFile
        if (-not [System.IO.Path]::IsPathRooted($cookiesCandidate)) {
            $cookiesCandidate = Join-Path $scriptDir $cookiesCandidate
        }
        $resolvedCookiesFile = Resolve-Path -Path $cookiesCandidate -ErrorAction Stop
        $arguments += @("--cookies-file", $resolvedCookiesFile)
    }
    elseif (Test-Path $defaultCookiesPath) {
        $arguments += @("--cookies-file", $defaultCookiesPath)
    }

    $csvName = Split-Path -Leaf $TargetCsvPath

    Write-Host ""
    if ($TotalCount -gt 0 -and $CurrentIndex -gt 0) {
        Write-Host "[$CurrentIndex/$TotalCount] Starting: $csvName"
    }
    else {
        Write-Host "Starting: $csvName"
    }
    Write-Host "  CSV path: $TargetCsvPath"
    Write-Host "  Settings: tolerance=$DurationTolerance searchResults=$SearchResults limit=$Limit sleepRequests=$SleepRequests sleepInterval=$SleepInterval maxSleepInterval=$MaxSleepInterval limitRate=$LimitRate throttledRate=$ThrottledRate trackOrder=$TrackOrder forceRedownload=$ForceRedownload"

    & $pythonPath -u @arguments | Out-Host
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "Completed: $csvName"
        return $exitCode
    }

    Write-Host "Failed: $csvName (exit code $exitCode)"
    return $exitCode
}

if ($CsvPath -ne "") {
    $resolvedCsvPath = Resolve-Path -Path $CsvPath -ErrorAction Stop
    $code = Invoke-CsvDownload -TargetCsvPath $resolvedCsvPath -CurrentIndex 1 -TotalCount 1
    exit $code
}

$resolvedFolder = Resolve-Path -Path $CsvFolder -ErrorAction Stop
$csvFiles = Get-ChildItem -Path $resolvedFolder -Filter "*.csv" -File | Sort-Object -Property Name

if ($csvFiles.Count -eq 0) {
    Write-Host "No CSV files found in folder: $resolvedFolder"
    exit 0
}

$succeeded = 0
$failed = 0

for ($index = 0; $index -lt $csvFiles.Count; $index++) {
    $csv = $csvFiles[$index]
    $code = Invoke-CsvDownload -TargetCsvPath $csv.FullName -CurrentIndex ($index + 1) -TotalCount $csvFiles.Count
    if ($code -eq 0) {
        $succeeded += 1
    }
    else {
        $failed += 1
    }
}

Write-Host ""
Write-Host "Batch scan complete"
Write-Host "  CSV processed: $($csvFiles.Count)"
Write-Host "  succeeded:     $succeeded"
Write-Host "  failed:        $failed"

if ($failed -gt 0) {
    exit 1
}

exit 0
