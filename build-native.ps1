[CmdletBinding()]
param(
    [ValidateSet("x64", "x86")]
    [string]$Architecture = "x64",
    [switch]$UpdateBeachEye,
    [switch]$UpdateWolfEye,
    [string]$WolfEyeSourceDirectory,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
if ($UpdateWolfEye -and $WolfEyeSourceDirectory) {
    throw "Use either -UpdateWolfEye for company master or -WolfEyeSourceDirectory for local development sources."
}
$projectRoot = $PSScriptRoot
$source = Join-Path $projectRoot "code\native\beacheye"

# Pin GCC: the private BeachEye source is not compatible with MSVC.
$toolchainBin = if ($env:DEVOLF_GCC_BIN) {
    [System.IO.Path]::GetFullPath($env:DEVOLF_GCC_BIN)
}
elseif ($Architecture -eq "x64" -and (Test-Path -LiteralPath "C:\msys64\ucrt64\bin\g++.exe" -PathType Leaf)) {
    "C:\msys64\ucrt64\bin"
}
elseif ($Architecture -eq "x86" -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "DEVolf/Toolchains/mingw32/bin/g++.exe") -PathType Leaf)) {
    Join-Path $env:LOCALAPPDATA "DEVolf/Toolchains/mingw32/bin"
}
elseif ($Architecture -eq "x86" -and (Test-Path -LiteralPath "C:\mingw32\bin\g++.exe" -PathType Leaf)) {
    "C:\mingw32\bin"
}
else {
    $pathCompiler = Get-Command g++.exe -ErrorAction SilentlyContinue
    if ($null -eq $pathCompiler) {
        throw "Missing x86 MinGW GCC. Install an i686 POSIX/DWARF MSVCRT toolchain and set DEVOLF_GCC_BIN to its bin directory."
    }
    Split-Path $pathCompiler.Source -Parent
}
$gcc = Join-Path $toolchainBin "gcc.exe"
$gxx = Join-Path $toolchainBin "g++.exe"
$ninjaCommand = Get-Command ninja.exe -ErrorAction SilentlyContinue
$ninja = if (Test-Path -LiteralPath (Join-Path $toolchainBin 'ninja.exe')) {
    Join-Path $toolchainBin 'ninja.exe'
} elseif ($ninjaCommand) {
    $ninjaCommand.Source
} elseif (Test-Path -LiteralPath 'C:\msys64\ucrt64\bin\ninja.exe') {
    'C:\msys64\ucrt64\bin\ninja.exe'
} else {
    throw "Missing Ninja. Install Ninja and add ninja.exe to PATH."
}
foreach ($tool in @($gcc, $gxx, $ninja)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Missing GCC build tool: $tool. Set DEVOLF_GCC_BIN to the i686 POSIX/DWARF MSVCRT toolchain bin directory."
    }
}
$target = (& $gxx -dumpmachine | Out-String).Trim()
$expectedTarget = if ($Architecture -eq "x86") { "i686-w64-mingw32" } else { "x86_64-w64-mingw32" }
if ($LASTEXITCODE -ne 0 -or $target -ne $expectedTarget) {
    throw "Expected $Architecture MinGW GCC ($expectedTarget); found '$target'."
}
$buildName = if ($WolfEyeSourceDirectory) { "native-beacheye-development-$Architecture" } else { "native-beacheye-$Architecture" }
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
        "-DDEVOLF_ARCHITECTURE=$Architecture",
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
    & cmake --build $BuildDirectory --config Release --parallel
    if ($LASTEXITCODE -ne 0) {
        throw "Native DataProvider build failed with exit code $LASTEXITCODE."
    }
}

$sourceInfo = & $resolver -UpdateSource:$UpdateBeachEye
if ($null -eq $sourceInfo -or -not (Test-Path -LiteralPath $sourceInfo.Path -PathType Container)) {
    throw "BeachEye source resolution did not return a valid directory."
}

if ($WolfEyeSourceDirectory) {
    $wolfPath = (Resolve-Path -LiteralPath $WolfEyeSourceDirectory).Path
    if (-not (Test-Path -LiteralPath (Join-Path $wolfPath 'WolfEye/src/FaultViewer.cpp'))) {
        throw "WolfEyeSourceDirectory must contain the company WolfEye source tree: $wolfPath"
    }
    $wolfSourceInfo = [PSCustomObject]@{ Path = $wolfPath }
    Write-Warning "Development WolfEye source selected: $wolfPath. Native support headers use this checkout; WolfEye algorithms are Python ports and are not compiled."
}
else {
    $wolfSourceInfo = & $resolver -Dependency WolfEye -UpdateSource:$UpdateWolfEye
}
Write-Host "WolfEye source: $($wolfSourceInfo.Path)"
if ($wolfSourceInfo.Commit) { Write-Host "WolfEye commit: $($wolfSourceInfo.Commit)" }

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
    Write-Host "Built native DataProvider: $destination"

    # All reported device builds use the selected company source. Its Database
    # DisablePoints(model, device_build) owns revision-specific measurement maps.
}
finally {
    $env:PATH = $previousPath
}
