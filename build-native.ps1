[CmdletBinding()]
param(
    [string]$BeachEyeBranch,
    [string]$BeachEyeRepository,
    [string]$BeachEyeCommit,
    [int]$BeachEyeRevision = 0,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$source = Join-Path $projectRoot "code\native\beacheye"
$build = Join-Path $projectRoot "build\native-beacheye-dataprovider"
$output = Join-Path $build "wolfeye_beacheye.dll"
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = $source
}
$destination = Join-Path $OutputDirectory "wolfeye_beacheye.dll"
$resolver = Join-Path $projectRoot "resolve-beacheye-source.ps1"
$sourceConfigPath = Join-Path $projectRoot "beacheye-source.json"

function Invoke-NativeBuild(
    [string]$BuildDirectory,
    [string]$BeachEyeDirectory,
    [int]$Revision
) {
    $configureArguments = @(
        "-S", $source,
        "-B", $BuildDirectory,
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=$BuildDirectory",
        "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=$BuildDirectory",
        "-DBEACHEYE_DIR=$BeachEyeDirectory",
        "-DBEACHEYE_REVISION=$Revision"
    )
    & cmake @configureArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native DataProvider configure failed with exit code $LASTEXITCODE."
    }
    & cmake --build $BuildDirectory --config Release --clean-first --parallel
    if ($LASTEXITCODE -ne 0) {
        throw "Native DataProvider build failed with exit code $LASTEXITCODE."
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
    $profileBuild = Join-Path $projectRoot "build\native-beacheye-profile-51"
    $profileOutput = Join-Path $profileBuild "wolfeye_beacheye.dll"
    $profileDestination = Join-Path $OutputDirectory "wolfeye_beacheye_51.dll"
    Invoke-NativeBuild $profileBuild $profileSourceInfo.Path $profileRevision
    Copy-Item -LiteralPath $profileOutput -Destination $profileDestination -Force
    Write-Host "Built revision-51 measurement decoder: $profileDestination"
}
