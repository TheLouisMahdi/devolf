[CmdletBinding()]
param(
    [switch]$UpdateBeachEye,
    [string]$WolfEyeSourceDirectory,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$source = Join-Path $projectRoot "code\native\beacheye"

# Pin GCC: the private BeachEye source is not compatible with MSVC.
$toolchainBin = if ($env:DEVOLF_GCC_BIN) {
    [System.IO.Path]::GetFullPath($env:DEVOLF_GCC_BIN)
}
elseif (Test-Path -LiteralPath "C:\msys64\ucrt64\bin\g++.exe" -PathType Leaf) {
    "C:\msys64\ucrt64\bin"
}
else {
    $pathCompiler = Get-Command g++.exe -ErrorAction SilentlyContinue
    if ($null -eq $pathCompiler) {
        throw "Missing x64 MinGW GCC. Install MSYS2 UCRT64 GCC/Ninja, set DEVOLF_GCC_BIN, or add its bin directory to PATH."
    }
    Split-Path $pathCompiler.Source -Parent
}
$gcc = Join-Path $toolchainBin "gcc.exe"
$gxx = Join-Path $toolchainBin "g++.exe"
$ninja = Join-Path $toolchainBin "ninja.exe"
foreach ($tool in @($gcc, $gxx, $ninja)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Missing GCC build tool: $tool. Install MSYS2 UCRT64 GCC/Ninja, set DEVOLF_GCC_BIN, or add its bin directory to PATH."
    }
}
$target = (& $gxx -dumpmachine | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $target -ne "x86_64-w64-mingw32") {
    throw "Expected x64 MinGW GCC (x86_64-w64-mingw32); found '$target'."
}
$buildName = if ($WolfEyeSourceDirectory) { "native-wolfeye-development-gcc-x64" } else { "native-beacheye-dataprovider-gcc-x64" }
$build = Join-Path $projectRoot "build\$buildName"
$output = Join-Path $build "wolfeye_beacheye.dll"
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = $source
}
$destination = Join-Path $OutputDirectory "wolfeye_beacheye.dll"
$resolver = Join-Path $projectRoot "resolve-beacheye-source.ps1"

function Invoke-NativeBuild(
    [string]$BuildDirectory,
    [string]$BeachEyeDirectory,
    [string]$WolfEyeDirectory
) {
    $configureArguments = @(
        "-S", $source,
        "-B", $BuildDirectory,
        "-G", "Ninja",
        "-DCMAKE_C_COMPILER=$gcc",
        "-DCMAKE_CXX_COMPILER=$gxx",
        "-DCMAKE_MAKE_PROGRAM=$ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=$BuildDirectory",
        "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE=$BuildDirectory",
        "-DBEACHEYE_DIR=$BeachEyeDirectory",
        "-DWOLFEYE_DIR=$WolfEyeDirectory"
        "-DWOLFEYE_REQUIRE_PRISTINE=$(if ($WolfEyeSourceDirectory) { 'OFF' } else { 'ON' })"
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

$sourceInfo = & $resolver -UpdateBeachEye:$UpdateBeachEye
if ($null -eq $sourceInfo -or -not (Test-Path -LiteralPath $sourceInfo.Path -PathType Container)) {
    throw "BeachEye source resolution did not return a valid directory."
}

if ($WolfEyeSourceDirectory) {
    $wolfPath = (Resolve-Path -LiteralPath $WolfEyeSourceDirectory).Path
    if (-not (Test-Path -LiteralPath (Join-Path $wolfPath 'WolfEye/src/FaultViewer.cpp'))) {
        throw "WolfEyeSourceDirectory must contain the company WolfEye source tree: $wolfPath"
    }
    $wolfSourceInfo = [PSCustomObject]@{ Path = $wolfPath }
    Write-Warning "Development WolfEye source selected: $wolfPath. Local changes are compiled; this is not a pristine company release."
}
else {
    $wolfSourceInfo = & $resolver -Dependency WolfEye
}
Write-Host "WolfEye source: $($wolfSourceInfo.Path)"

Write-Host "Building BeachEye branch '$($sourceInfo.Branch)' from $($sourceInfo.SourceKind)."
Write-Host "BeachEye source: $($sourceInfo.Path)"
Write-Host "BeachEye commit: $($sourceInfo.Commit)"

$previousPath = $env:PATH
$env:PATH = "$toolchainBin;$previousPath"
try {
    Invoke-NativeBuild $build $sourceInfo.Path $wolfSourceInfo.Path
    $sourceStatus = & git -C $sourceInfo.Path status --porcelain --untracked-files=all
    if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace(($sourceStatus -join ""))) {
        throw "BeachEye checkout changed during compilation; refusing to install the DLL."
    }
    $wolfStatus = & git -C $wolfSourceInfo.Path status --porcelain --untracked-files=all
    if (-not $WolfEyeSourceDirectory -and ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace(($wolfStatus -join "")))) {
        throw "WolfEye company checkout changed during compilation."
    }
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    Copy-Item -LiteralPath $output -Destination $destination -Force
    Copy-Item -LiteralPath (Join-Path $build 'wolfeye_core.dll') -Destination (Join-Path $OutputDirectory 'wolfeye_core.dll') -Force
    Write-Host "Built native DataProvider: $destination"

    # All reported device builds use the selected company source. Its Database
    # DisablePoints(model, device_build) owns revision-specific measurement maps.
}
finally {
    $env:PATH = $previousPath
}
