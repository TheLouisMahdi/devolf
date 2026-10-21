[CmdletBinding()]
param(
    [Alias("UpdateBeachEye")][switch]$UpdateSource,
    [ValidateSet("BeachEye", "WolfEye")][string]$Dependency = "BeachEye"
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$configPath = Join-Path $projectRoot $(if ($Dependency -eq "WolfEye") { "wolfeye-source.json" } else { "beacheye-source.json" })
$requiredFiles = @(
    "include\Configure.h",
    "include\Database.h",
    "include\Settings.h",
    "src\Database.cpp",
    "src\Settings.cpp",
    "src\cJSON_Imp.cpp"
)

if ($Dependency -eq "WolfEye") {
    $requiredFiles = @("WolfEye\include\TCCCalculator.h", "WolfEye\src\TCCCalculator.cpp",
        "WolfEye\src\SettingsView.cpp", "WolfEye\src\FaultViewer.cpp", "DataProvider\src\DataProvider.cpp")
}

function Get-PrivateCacheRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:DEVOLF_BEACHEYE_CACHE)) {
        return [IO.Path]::GetFullPath($env:DEVOLF_BEACHEYE_CACHE)
    }

    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if ([string]::IsNullOrWhiteSpace($localAppData)) {
        throw "LOCALAPPDATA is unavailable. Set DEVOLF_BEACHEYE_CACHE to a directory outside the public repository."
    }
    return Join-Path $localAppData "DEVolf\BeachEye"
}

$cacheRoot = Get-PrivateCacheRoot
$projectPrefix = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
$cachePrefix = [IO.Path]::GetFullPath($cacheRoot).TrimEnd('\') + '\'
if ($cachePrefix.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BeachEye source cache must be outside the project: $cacheRoot"
}

function Test-BeachEyeSource([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    foreach ($relativePath in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $relativePath) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

function Invoke-NativeCommand([string]$FilePath, [string[]]$Arguments = @()) {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $FilePath @Arguments 2>$null)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return [PSCustomObject]@{
        Output = $output
        ExitCode = $exitCode
    }
}

function Get-SafeDirectoryName([string]$Value) {
    $safe = $Value -replace '[^A-Za-z0-9._-]', '_'
    if ([string]::IsNullOrWhiteSpace($safe)) {
        throw "The BeachEye branch does not contain a usable directory name."
    }
    return $safe
}

function Assert-CacheChild([string]$Path) {
    $fullRoot = [IO.Path]::GetFullPath($cacheRoot).TrimEnd('\') + '\'
    $fullPath = [IO.Path]::GetFullPath($Path)
    $projectPath = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($projectPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a directory outside the private dependency cache: $fullPath"
    }
}

function Remove-CacheDirectory([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or
        -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return
    }
    Assert-CacheChild $Path
    Remove-Item -LiteralPath $Path -Recurse -Force
}

function Test-CachedRevision([string]$Path, [string]$ExpectedCommit) {
    if (-not (Test-BeachEyeSource $Path) -or
        -not (Test-Path -LiteralPath (Join-Path $Path ".git") -PathType Container)) {
        return $false
    }
    $revision = Invoke-NativeCommand git @("-C", $Path, "rev-parse", "HEAD")
    if ($revision.ExitCode -ne 0) {
        return $false
    }
    return ([string]($revision.Output | Select-Object -Last 1)).Trim() -eq $ExpectedCommit
}

function Assert-PristineSource([string]$Path) {
    $status = Invoke-NativeCommand git @("-C", $Path, "status", "--porcelain", "--untracked-files=all")
    if ($status.ExitCode -ne 0 -or -not [string]::IsNullOrWhiteSpace(($status.Output -join ""))) {
        throw "BeachEye source must be an unmodified company checkout: $Path"
    }
}

if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Missing BeachEye source configuration: $configPath"
}
try {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
}
catch {
    throw "Invalid JSON in ${configPath}: $($_.Exception.Message)"
}

$Repository = [string]$config.repository
$Branch = [string]$config.branch
$Commit = [string]$config.commit
$expectedRepository = if ($Dependency -eq "WolfEye") { "majidnow/wolfeye" } else { "majidnow/BeachEye" }
$expectedBranch = if ($Dependency -eq "WolfEye") { "master" } else { "ver_50_remaster" }
if ($Repository -cne $expectedRepository -or $Branch -cne $expectedBranch) {
    throw "DEVolf requires $expectedRepository branch $expectedBranch in $configPath."
}
if ($Commit -notmatch '^[0-9a-fA-F]{40}$') {
    throw "BeachEye commit must be a full 40-character SHA: $Commit"
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw "GitHub CLI (gh) is required to authenticate to the private company repositories."
}

$privacy = Invoke-NativeCommand $gh.Source @("api", "repos/$Repository", "--jq", ".private")
if ($privacy.ExitCode -ne 0) {
    throw "Cannot access '$Repository'. Run 'gh auth login' with an account that has read access to the private repository."
}
if (([string]($privacy.Output | Select-Object -Last 1)).Trim().ToLowerInvariant() -ne "true") {
    throw "Refusing to use '$Repository': the BeachEye dependency must remain private."
}

$requestedRevision = if ($UpdateSource) { $Branch } else { $Commit }
$encodedRevision = [Uri]::EscapeDataString($requestedRevision)
$remote = Invoke-NativeCommand $gh.Source @("api", "repos/$Repository/commits/$encodedRevision", "--jq", ".sha")
if ($remote.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace(($remote.Output -join ""))) {
    throw "Private BeachEye revision '$requestedRevision' could not be resolved in '$Repository'."
}
$remoteCommit = ([string]($remote.Output | Select-Object -Last 1)).Trim().ToLowerInvariant()
if ($remoteCommit -notmatch '^[0-9a-f]{40}$') {
    throw "GitHub returned an invalid BeachEye commit SHA."
}

$safeBranch = Get-SafeDirectoryName $Branch
$safeRepository = Get-SafeDirectoryName ($Repository -replace '/', '__')
$repositoryCache = Join-Path (Join-Path $cacheRoot "upstream") $safeRepository
$branchCache = Join-Path $repositoryCache $safeBranch
$snapshotPath = Join-Path $branchCache $remoteCommit

if (Test-CachedRevision $snapshotPath $remoteCommit) {
    Assert-PristineSource $snapshotPath
    Write-Host "Using authenticated private $Dependency cache: $Repository@$Branch ($($remoteCommit.Substring(0, 12)))"
    $sourceKind = "private-cache"
}
else {
    if (Test-Path -LiteralPath $snapshotPath) {
        throw "The existing BeachEye cache is not the expected company checkout: $snapshotPath"
    }
    New-Item -ItemType Directory -Path $branchCache -Force | Out-Null
    $stagingPath = Join-Path $branchCache (".staging-" + [Guid]::NewGuid().ToString("N"))
    try {
        Write-Host "Downloading private $Dependency dependency: $Repository@$Branch ($($remoteCommit.Substring(0, 12)))"
        $clone = Invoke-NativeCommand $gh.Source @(
            "repo", "clone", $Repository, $stagingPath, "--",
            "--filter=blob:none", "--no-checkout"
        )
        if ($clone.ExitCode -ne 0) {
            throw "Cloning the private BeachEye repository failed."
        }
        $fetch = Invoke-NativeCommand git @("-C", $stagingPath, "fetch", "origin", $remoteCommit, "--depth", "1")
        if ($fetch.ExitCode -ne 0) {
            throw "Fetching private BeachEye commit '$remoteCommit' failed."
        }
        $checkout = Invoke-NativeCommand git @("-C", $stagingPath, "checkout", "--detach", $remoteCommit)
        if ($checkout.ExitCode -ne 0 -or -not (Test-BeachEyeSource $stagingPath)) {
            throw "The private BeachEye checkout is incomplete."
        }
        Assert-PristineSource $stagingPath
        Assert-CacheChild $stagingPath
        Assert-CacheChild $snapshotPath
        Move-Item -LiteralPath $stagingPath -Destination $snapshotPath
        $sourceKind = "private-download"
    }
    catch {
        Remove-CacheDirectory $stagingPath
        throw
    }
}

if ($UpdateSource -and $Commit -cne $remoteCommit) {
    # Persist only after the exact checkout is ready. A failed lookup/download
    # leaves the prior pin intact; one build never follows a moving branch twice.
    $config.commit = $remoteCommit
    $manifest = ($config | ConvertTo-Json -Depth 10) + [Environment]::NewLine
    [IO.File]::WriteAllText($configPath, $manifest, [Text.UTF8Encoding]::new($false))
    Write-Host "Updated $([IO.Path]::GetFileName($configPath)): $Commit -> $remoteCommit"
}

[PSCustomObject]@{
    Path = (Resolve-Path -LiteralPath $snapshotPath).Path
    Repository = $Repository
    Branch = $Branch
    Commit = $remoteCommit
    SourceKind = $sourceKind
    CacheRoot = $cacheRoot
}
