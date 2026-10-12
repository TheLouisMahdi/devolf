[CmdletBinding()]
param(
    [string]$BeachEyeBranch,
    [string]$BeachEyeRepository,
    [string]$BeachEyeCommit,
    [int]$BeachEyeRevision = 0,
    [switch]$Legacy,
    [Alias("UniversalToolchainRoot")]
    [string]$LegacyToolchainRoot,
    [ValidateSet("x86", "x64")]
    [string]$Architecture = "x64",
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$source = Join-Path $projectRoot "code\native\beacheye"
$buildName = if ($Legacy) { "native-beacheye-dataprovider-legacy-$Architecture" } else { "native-beacheye-dataprovider" }
$build = Join-Path $projectRoot "build\$buildName"
$output = Join-Path $build "wolfeye_beacheye.dll"
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = $source
}
$destination = Join-Path $OutputDirectory "wolfeye_beacheye.dll"
$resolver = Join-Path $projectRoot "resolve-beacheye-source.ps1"
$sourceConfigPath = Join-Path $projectRoot "beacheye-source.json"

$cmakeToolchainArguments = @()
if ($Legacy) {
    if ([string]::IsNullOrWhiteSpace($LegacyToolchainRoot)) {
        $LegacyToolchainRoot = $env:WOLFEYE_LEGACY_MINGW
    }
    if ([string]::IsNullOrWhiteSpace($LegacyToolchainRoot)) {
        throw "Legacy builds require -LegacyToolchainRoot (MinGW-w64 POSIX/MSVCRT)."
    }
    $LegacyToolchainRoot = [System.IO.Path]::GetFullPath($LegacyToolchainRoot)
    if ($LegacyToolchainRoot -match '\s') {
        throw "LegacyToolchainRoot must not contain spaces: $LegacyToolchainRoot"
    }
    $gcc = Join-Path $LegacyToolchainRoot "bin\gcc.exe"
    $gxx = Join-Path $LegacyToolchainRoot "bin\g++.exe"
    $make = Join-Path $LegacyToolchainRoot "bin\mingw32-make.exe"
    $objdump = Join-Path $LegacyToolchainRoot "bin\objdump.exe"
    foreach ($tool in @($gcc, $gxx, $make, $objdump)) {
        if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
            throw "Legacy compiler tool is missing: $tool"
        }
    }
    $compilerDescription = (& cmd.exe /d /c "`"$gxx`" -v 2>&1" | Out-String)
    if ($compilerDescription -notmatch "Thread model:\s*posix" -or $compilerDescription -notmatch "msvcrt") {
        throw "Legacy builds require a MinGW-w64 POSIX/MSVCRT compiler."
    }
    $compilerTarget = (& $gxx -dumpmachine | Out-String).Trim()
    $expectedTarget = if ($Architecture -eq "x86") { "i686-w64-mingw32" } else { "x86_64-w64-mingw32" }
    if ($compilerTarget -ne $expectedTarget) {
        throw "The $Architecture build requires compiler target $expectedTarget (found $compilerTarget)."
    }
    $cmakeToolchainArguments = @(
        "-DCMAKE_MAKE_PROGRAM=$make",
        "-DCMAKE_C_COMPILER=$gcc",
        "-DCMAKE_CXX_COMPILER=$gxx",
        "-DWOLFEYE_LEGACY_WINDOWS=ON"
    )
}

function Invoke-NativeBuild(
    [string]$BuildDirectory,
    [string]$BeachEyeDirectory,
    [int]$Revision
) {
    $configureArguments = @(
        "-S", $source,
        "-B", $BuildDirectory,
        "-G", "MinGW Makefiles",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBEACHEYE_DIR=$BeachEyeDirectory",
        "-DBEACHEYE_REVISION=$Revision"
    ) + $cmakeToolchainArguments
    & cmake @configureArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native DataProvider configure failed with exit code $LASTEXITCODE."
    }
    & cmake --build $BuildDirectory --config Release --clean-first --parallel
    if ($LASTEXITCODE -ne 0) {
        throw "Native DataProvider build failed with exit code $LASTEXITCODE."
    }
}

function Assert-LegacyImports([string]$Path) {
    if (-not $Legacy) {
        return
    }
    $imports = (& $objdump -p $Path | Out-String)
    $expectedFormat = if ($Architecture -eq "x86") { "pei-i386" } else { "pei-x86-64" }
    if ($imports -notmatch "file format\s+$expectedFormat") {
        throw "Legacy DLL architecture mismatch: expected $Architecture ($expectedFormat)."
    }
    $unsupported = @(
        "BaseGetNamedObjectDirectory",
        "GetDpiForSystem",
        "GetDpiForWindow",
        "GetSystemTimePreciseAsFileTime",
        "SetThreadDescription",
        "WaitOnAddress",
        "WakeByAddressAll",
        "WakeByAddressSingle"
    ) | Where-Object { $imports.Contains($_) }
    if ($unsupported) {
        throw "Legacy DLL imports unsupported Windows APIs: $($unsupported -join ', ')"
    }
    if ($imports -notmatch "DLL Name:\s+msvcrt\.dll") {
        throw "Legacy DLL was not linked against MSVCRT."
    }
}

$resolveArguments = @{}
if (-not [string]::IsNullOrWhiteSpace($BeachEyeBranch)) {
    $resolveArguments.Branch = $BeachEyeBranch
}
if (-not [string]::IsNullOrWhiteSpace($BeachEyeRepository)) {
    $resolveArguments.Repository = $BeachEyeRepository
}
if (-not [string]::IsNullOrWhiteSpace($BeachEyeCommit)) {
    $resolveArguments.Commit = $BeachEyeCommit
}
$sourceInfo = & $resolver @resolveArguments
if ($null -eq $sourceInfo -or -not (Test-Path -LiteralPath $sourceInfo.Path -PathType Container)) {
    throw "BeachEye source resolution did not return a valid directory."
}

if ($BeachEyeRevision -le 0) {
    if ($sourceInfo.Branch -match '(?i)ver[_-]?(\d+)') {
        $BeachEyeRevision = [int]$Matches[1]
    }
    else {
        $BeachEyeRevision = 50
    }
}
if ($BeachEyeRevision -lt 1 -or $BeachEyeRevision -gt 255) {
    throw "BeachEye revision must be between 1 and 255 (found $BeachEyeRevision)."
}

Write-Host "Building BeachEye branch '$($sourceInfo.Branch)' from $($sourceInfo.SourceKind)."
Write-Host "BeachEye source: $($sourceInfo.Path)"
Write-Host "BeachEye revision: $BeachEyeRevision"

Invoke-NativeBuild $build $sourceInfo.Path $BeachEyeRevision
Assert-LegacyImports $output
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
Copy-Item -LiteralPath $output -Destination $destination -Force
Write-Host "Built native DataProvider: $destination"

# Revision 51 has a different measurement point profile. Keep revision 50 as
# the transport/settings source selected by the project, and build the exact
# revision-51 branch as a decoder selected only after device INFO reports 51.
if ($BeachEyeRevision -eq 50) {
    $profileRevision = 51
    $sourceConfig = Get-Content -LiteralPath $sourceConfigPath -Raw | ConvertFrom-Json
    $profileBranch = [string]$sourceConfig.revision51Branch
    $profileCommit = [string]$sourceConfig.revision51Commit
    if ([string]::IsNullOrWhiteSpace($profileBranch) -or
        $profileCommit -notmatch '^[0-9a-fA-F]{40}$') {
        throw "beacheye-source.json must pin revision51Branch and a full revision51Commit SHA."
    }
    $profileSourceInfo = & $resolver `
        -Branch $profileBranch `
        -Repository $sourceInfo.Repository `
        -Commit $profileCommit
    if ($null -eq $profileSourceInfo -or -not (Test-Path -LiteralPath $profileSourceInfo.Path -PathType Container)) {
        throw "BeachEye revision-51 profile resolution did not return a valid directory."
    }
    $profileBuildName = if ($Legacy) { "native-beacheye-profile-51-legacy-$Architecture" } else { "native-beacheye-profile-51" }
    $profileBuild = Join-Path $projectRoot "build\$profileBuildName"
    $profileOutput = Join-Path $profileBuild "wolfeye_beacheye.dll"
    $profileDestination = Join-Path $OutputDirectory "wolfeye_beacheye_51.dll"
    Invoke-NativeBuild $profileBuild $profileSourceInfo.Path $profileRevision
    Assert-LegacyImports $profileOutput
    Copy-Item -LiteralPath $profileOutput -Destination $profileDestination -Force
    Write-Host "Built revision-51 measurement decoder: $profileDestination"
}
