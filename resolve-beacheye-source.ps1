[CmdletBinding()]
param(
    [string]$Branch,
    [string]$Repository,
    [string]$Commit
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$configPath = Join-Path $projectRoot "beacheye-source.json"
$requiredFiles = @(
    "include\Configure.h",
    "include\Database.h",
    "include\Settings.h",
    "src\Database.cpp",
    "src\Settings.cpp",
    "src\cJSON_Imp.cpp"
)

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
    if (-not $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
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

function Enable-DesktopCompatibility([string]$Path) {
    # Private revisions must carry their own desktop guard. The public tree
    # deliberately contains neither the private header nor a source patch.
    $measureTypePath = Join-Path $Path "include\MeasureType.h"
    $measureType = Get-Content -LiteralPath $measureTypePath -Raw
    $usesFirmwareScatter = $measureType.Contains("GetTick()") -and
        $measureType.Contains("global.scatter_buffer")
    $hasDesktopGuard = $measureType.Contains("#ifndef _WIN32") -or
        $measureType.Contains("#if !defined(_WIN32)")
    if ($usesFirmwareScatter -and -not $hasDesktopGuard) {
        throw "The selected private BeachEye revision lacks its required Windows desktop guard in include\MeasureType.h."
    }

    # Revision 50 declares seven physical output timers but serializes eight
    # output records. Apply a narrow cache-only safety transform without
    # storing private source or a source diff in this public repository.
    $configurePath = Join-Path $Path "include\Configure.h"
    $configure = Get-Content -LiteralPath $configurePath -Raw
    $jsonPath = Join-Path $Path "src\cJSON_Imp.cpp"
    $json = Get-Content -LiteralPath $jsonPath -Raw
    $changed = $false

    $unsafeReadPattern = '(?m)^(?<indent>[ \t]*)GET_O_GPIO\(item,\s*\(\*output\),\s*c->do_time\[doutput_c\+\+\]\);\s*\\\s*$'
    if ($configure.Contains('do_time[7]') -and [regex]::IsMatch($json, $unsafeReadPattern)) {
        $macroTimerPattern = '(?m)^[ \t]*GET_NUM\(obj,\s*"t",\s*do_time\);\s*\\\r?\n'
        $writerPattern = '(?m)^(?<indent>[ \t]*)JSON_NUM_ADD_DEF\(output,\s*"t",\s*c->do_time\[i\],\s*i32_time_0p01_120,\s*1000\);\s*$'
        if ([regex]::Matches($json, $macroTimerPattern).Count -ne 1 -or
            [regex]::Matches($json, $unsafeReadPattern).Count -ne 1 -or
            [regex]::Matches($json, $writerPattern).Count -ne 1) {
            throw "The selected private BeachEye revision has an unknown digital-output JSON layout."
        }

        $json = [regex]::Replace($json, $macroTimerPattern, "", 1)

        $readMatch = [regex]::Match($json, $unsafeReadPattern)
        $indent = $readMatch.Groups["indent"].Value
        $safeRead = @(
            "${indent}GET_O_GPIO(item, (*output), c->do_time[0]); \",
            "${indent}if(doutput_c < 7) \",
            "${indent}{ \",
            "${indent}    cJSON* operation_time = cJSON_GetObjectItem(item, `"t`"); \",
            "${indent}    if(cJSON_IsNumber(operation_time)) \",
            "${indent}        c->do_time[doutput_c] = operation_time->valuedouble; \",
            "${indent}} \",
            "${indent}doutput_c++; \"
        ) -join [Environment]::NewLine
        $json = $json.Substring(0, $readMatch.Index) + $safeRead +
            $json.Substring($readMatch.Index + $readMatch.Length)

        $writerMatch = [regex]::Match($json, $writerPattern)
        $indent = $writerMatch.Groups["indent"].Value
        $safeWriter = @(
            "${indent}if(i < 7)",
            "${indent}{",
            "${indent}    JSON_NUM_ADD_DEF(output, `"t`", c->do_time[i], i32_time_0p01_120, 1000);",
            "${indent}}"
        ) -join [Environment]::NewLine
        $json = $json.Substring(0, $writerMatch.Index) + $safeWriter +
            $json.Substring($writerMatch.Index + $writerMatch.Length)
        $changed = $true
    }

    if ($configure.Contains('do_time[7]')) {
        $safeWriterPattern = '(?s)if\s*\(i\s*<\s*7\).*?JSON_NUM_ADD_DEF\(output,\s*"t",\s*c->do_time\[i\],\s*i32_time_0p01_120,\s*1000\);'
        if ($json -match 'c->do_time\[doutput_c\+\+\]' -or
            -not [regex]::IsMatch($json, $safeWriterPattern)) {
            throw "The private BeachEye digital-output JSON safety transform was not applied completely."
        }
    }

    # WolfEye master edits Configure directly with numeric validation disabled.
    # The JSON export helper otherwise resets out-of-menu numeric values in
    # Configure while merely reading them. Keep numeric export lossless in the
    # desktop cache; enum validation and the firmware source remain unchanged.
    $numericMacroPattern = '(?ms)^#define JSON_NUM_ASSERT_DEF\(.*?(?=^#define JSON_NUM_ADD\()'
    if ([regex]::Matches($json, $numericMacroPattern).Count -ne 1) {
        throw "The private BeachEye numeric JSON export layout is not recognized."
    }
    $numericMacro = "#define JSON_NUM_ASSERT_DEF(obj, value, attr, def) JSON_NUM_ASSERT(obj, value)" +
        [Environment]::NewLine + [Environment]::NewLine
    $losslessJson = [regex]::Replace($json, $numericMacroPattern, $numericMacro, 1)
    if ($losslessJson -ne $json) {
        $json = $losslessJson
        $changed = $true
    }

    if ($changed) {
        [IO.File]::WriteAllText($jsonPath, $json, [Text.UTF8Encoding]::new($false))
    }
    Set-Content -LiteralPath (Join-Path $Path ".devolf-desktop-ready") `
        -Value "DEVolf desktop compatibility applied outside the public repository." `
        -Encoding ascii
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

$branchWasSpecified = -not [string]::IsNullOrWhiteSpace($Branch)
if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = [string]$config.repository
}
if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = [string]$config.branch
}
if ([string]::IsNullOrWhiteSpace($Commit) -and -not $branchWasSpecified) {
    $Commit = [string]$config.commit
}
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "BeachEye repository must use owner/name format: $Repository"
}
if ([string]::IsNullOrWhiteSpace($Branch)) {
    throw "BeachEye branch is empty. Set it in $configPath or pass -Branch."
}
if (-not [string]::IsNullOrWhiteSpace($Commit) -and $Commit -notmatch '^[0-9a-fA-F]{40}$') {
    throw "BeachEye commit must be a full 40-character SHA: $Commit"
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw "GitHub CLI (gh) is required to authenticate to the private BeachEye repository."
}

$privacy = Invoke-NativeCommand $gh.Source @("api", "repos/$Repository", "--jq", ".private")
if ($privacy.ExitCode -ne 0) {
    throw "Cannot access '$Repository'. Run 'gh auth login' with an account that has read access to the private repository."
}
if (([string]($privacy.Output | Select-Object -Last 1)).Trim().ToLowerInvariant() -ne "true") {
    throw "Refusing to use '$Repository': the BeachEye dependency must remain private."
}

$requestedRevision = if ([string]::IsNullOrWhiteSpace($Commit)) { $Branch } else { $Commit }
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
$repositoryCache = Join-Path $cacheRoot $safeRepository
$branchCache = Join-Path $repositoryCache $safeBranch
$snapshotPath = Join-Path $branchCache $remoteCommit

if (Test-CachedRevision $snapshotPath $remoteCommit) {
    Enable-DesktopCompatibility $snapshotPath
    Write-Host "Using authenticated private BeachEye cache: $Repository@$Branch ($($remoteCommit.Substring(0, 12)))"
    $sourceKind = "private-cache"
}
else {
    if (Test-Path -LiteralPath $snapshotPath) {
        Remove-CacheDirectory $snapshotPath
    }
    New-Item -ItemType Directory -Path $branchCache -Force | Out-Null
    $stagingPath = Join-Path $branchCache (".staging-" + [Guid]::NewGuid().ToString("N"))
    try {
        Write-Host "Downloading private BeachEye dependency: $Repository@$Branch ($($remoteCommit.Substring(0, 12)))"
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
        Enable-DesktopCompatibility $stagingPath
        Move-Item -LiteralPath $stagingPath -Destination $snapshotPath
        $sourceKind = "private-download"
    }
    catch {
        Remove-CacheDirectory $stagingPath
        throw
    }
}

[PSCustomObject]@{
    Path = (Resolve-Path -LiteralPath $snapshotPath).Path
    Repository = $Repository
    Branch = $Branch
    Commit = $remoteCommit
    SourceKind = $sourceKind
    CacheRoot = $cacheRoot
}
