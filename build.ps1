[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Name = "DEVolf",
    [switch]$UpdateBeachEye,
    [string]$WolfEyeSourceDirectory,
    [string]$PythonExecutable,
    [string]$Wheelhouse
)

$ErrorActionPreference = "Stop"

$architecture = "x64"

if ([System.IO.Path]::GetFileName($Name) -ne $Name) {
    throw "Name must be a file name, not a path: $Name"
}

$projectRoot = $PSScriptRoot
$pythonVersionRequired = "3.11"
$pythonBitsRequired = 64
$venvName = ".venv"
$python = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $projectRoot "$venvName\Scripts\python.exe"
}
else {
    [System.IO.Path]::GetFullPath($PythonExecutable)
}
$entryPoint = Join-Path $projectRoot "code\main.py"
$assets = Join-Path $projectRoot "code\assets"
$testLots = Join-Path $projectRoot "code\test_lots"
$icon = Join-Path $assets "wolfeye.ico"
$nativeDirectory = Join-Path $projectRoot "code\native\beacheye"
$nativeDll = Join-Path $nativeDirectory "wolfeye_beacheye.dll"
$wolfEyeDll = Join-Path $nativeDirectory "wolfeye_core.dll"
$requirements = Join-Path $projectRoot "requirements.txt"
$dist = Join-Path $projectRoot "Dist"
$work = Join-Path $projectRoot "build"
$output = Join-Path $dist "$Name.exe"
$nativeBuildScript = Join-Path $projectRoot "build-native.ps1"

function Test-OutputLocked([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        $probe = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $probe.Dispose()
        return $false
    }
    catch {
        return $true
    }
}

function Get-PeMachine([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $reader = [System.IO.BinaryReader]::new($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5A4D) {
            throw "Not a PE executable: $Path"
        }
        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            throw "Invalid PE signature: $Path"
        }
        return $reader.ReadUInt16()
    }
    finally {
        $reader.Dispose()
    }
}

foreach ($requiredFile in @($entryPoint, $icon, $requirements, $nativeBuildScript)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required build input is missing: $requiredFile"
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf) -and [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $launcherVersion = "-$pythonVersionRequired"
    py $launcherVersion -m venv (Join-Path $projectRoot $venvName)
    if ($LASTEXITCODE -ne 0) {
        throw "Python $pythonVersionRequired could not create the virtual environment."
    }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python executable is missing: $python"
}

$pythonInfo = & $python -c "import struct, sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{struct.calcsize(chr(80)) * 8}')"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the selected Python runtime."
}
$pythonVersion, $pythonBits = $pythonInfo.Trim().Split("|")
if ($pythonVersion -ne $pythonVersionRequired -or [int]$pythonBits -ne $pythonBitsRequired) {
    throw "This build requires Python $pythonVersionRequired $pythonBitsRequired-bit (found $pythonVersion $pythonBits-bit)."
}

$nativeBuildArguments = @{}
$nativeBuildArguments.OutputDirectory = $nativeDirectory
$nativeBuildArguments.UpdateBeachEye = $UpdateBeachEye
$nativeBuildArguments.WolfEyeSourceDirectory = $WolfEyeSourceDirectory
& $nativeBuildScript @nativeBuildArguments
if (-not (Test-Path -LiteralPath $nativeDll -PathType Leaf)) {
    throw "Native BeachEye build did not produce: $nativeDll"
}
if (-not (Test-Path -LiteralPath $wolfEyeDll -PathType Leaf)) {
    throw "Native WolfEye build did not produce: $wolfEyeDll"
}

if (Test-OutputLocked $output) {
    $requestedOutput = $output
    $fallbackName = "$Name-new"
    $fallbackOutput = Join-Path $dist "$fallbackName.exe"
    if (Test-OutputLocked $fallbackOutput) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $fallbackName = "$Name-$stamp"
        $fallbackOutput = Join-Path $dist "$fallbackName.exe"
    }
    Write-Warning "Output is in use: $requestedOutput"
    Write-Warning "Building the new version as: $fallbackOutput"
    $Name = $fallbackName
    $output = $fallbackOutput
}

$pipArguments = @("-m", "pip", "install", "--disable-pip-version-check")
if (-not [string]::IsNullOrWhiteSpace($Wheelhouse)) {
    $Wheelhouse = [System.IO.Path]::GetFullPath($Wheelhouse)
    if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
        throw "Wheelhouse directory is missing: $Wheelhouse"
    }
    $pipArguments += @("--no-index", "--find-links", $Wheelhouse)
}
$pipArguments += @("-r", $requirements)
& $python @pipArguments
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE."
}

$previousPythonPath = $env:PYTHONPATH
$previousNativeDirectory = $env:WOLFEYE_NATIVE_DIR
$env:PYTHONPATH = Join-Path $projectRoot "code"
$env:WOLFEYE_NATIVE_DIR = $nativeDirectory
try {
    $testRoot = Join-Path $projectRoot "tests"
    $codeRoot = Join-Path $projectRoot "code"
    $testRunner = @"
import sys, unittest
sys.path.insert(0, r'$codeRoot')
suite = unittest.defaultTestLoader.discover(r'$testRoot')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"@
    & $python -c $testRunner
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed with exit code $LASTEXITCODE."
    }

    $arguments = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", $Name,
        "--distpath", $dist,
        "--workpath", $work,
        "--specpath", $work,
        "--icon", $icon,
        "--add-data", "$assets;assets",
        "--add-data", "$testLots;test_lots",
        "--add-binary", "$nativeDll;native/beacheye",
        "--add-binary", "$wolfEyeDll;native/beacheye"
    )
    $arguments += $entryPoint
    New-Item -ItemType Directory -Path $work -Force | Out-Null

    # PyInstaller searches PATH while resolving native dependencies. Limit it
    # to Windows and this Python installation so unrelated tools cannot inject
    # incompatible DLLs (for example a third-party ICU ahead of System32).
    $previousPath = $env:PATH
    $pythonHome = & $python -c "import sys; print(sys.base_prefix)"
    if ($LASTEXITCODE -ne 0 -or -not $pythonHome.Trim()) {
        throw "Could not determine the Python installation directory."
    }
    $safePath = @(
        (Split-Path $python -Parent),
        $pythonHome.Trim(),
        (Join-Path $pythonHome.Trim() "DLLs"),
        (Join-Path $env:SystemRoot "System32"),
        $env:SystemRoot,
        (Join-Path $env:SystemRoot "System32\Wbem")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }

    try {
        $env:PATH = $safePath -join ";"
        & $python @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        $env:PATH = $previousPath
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:WOLFEYE_NATIVE_DIR = $previousNativeDirectory
}

if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw "Build finished without producing $output"
}
$expectedMachine = 0x8664
$actualMachine = Get-PeMachine $output
if ($actualMachine -ne $expectedMachine) {
    throw "Packaged EXE architecture mismatch: expected $architecture, PE machine 0x$($actualMachine.ToString('X4'))."
}

$previousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
try {
    $smoke = Start-Process `
        -FilePath $output `
        -ArgumentList "--smoke-test" `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    if ($smoke.ExitCode -ne 0) {
        throw "Built EXE failed its Qt startup smoke test with exit code $($smoke.ExitCode)."
    }
}
finally {
    $env:QT_QPA_PLATFORM = $previousQtPlatform
}

Write-Host "Built and smoke-tested: $output"
