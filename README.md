# DEVolf

Windows engineering console for Fartak Control **FC22AR / FC22S** devices.
DEVolf connects over LAN, displays device status and measurements, edits
settings and protection groups, retrieves events and signals, runs EmWolf
scenarios, and creates FC22 inspection reports.

[Build](#build) · [Features](#features) · [Company file mapping](#company-file-mapping) · [Project layout](#project-layout) · [Documentation](#documentation)

## Build

Supported target: **Windows 10/11, x64**, with **Python 3.11 x64**.

### Requirements

- Python 3.11 x64 and the `py` launcher.
- Git, [GitHub CLI](https://cli.github.com/) and CMake on `PATH`.
- MSYS2 UCRT64 GCC and Ninja. In the MSYS2 UCRT64 terminal:

  ```sh
  pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-ninja
  ```

- A GitHub account with read access to the private `majidnow/BeachEye` repository:

  ```powershell
  gh auth login
  gh auth status
  gh repo view majidnow/BeachEye
  ```

### Build command

Run from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

**Output:** `Dist\DEVolf.exe`.

The script creates `.venv` when needed, installs `requirements.txt`, builds
the pinned company native library, runs the tests, packages one EXE and checks its startup.
GCC/Ninja are selected explicitly. The default toolchain is
`C:\msys64\ucrt64\bin`; use `DEVOLF_GCC_BIN` for a different installation.

<details>
<summary>Advanced build options</summary>

Use `-PythonExecutable` to select an existing Python 3.11 x64 runtime and
`-Wheelhouse` for offline Python dependency installation. Private BeachEye
access is still required.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 `
  -PythonExecutable 'C:\Python311\python.exe' `
  -Wheelhouse 'D:\Wheelhouse'
```

Private source defaults to `%LOCALAPPDATA%\DEVolf\BeachEye`. To choose another
cache:

```powershell
$env:DEVOLF_BEACHEYE_CACHE = 'D:\PrivateBuildCache\DEVolf-BeachEye'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

Source selection comes only from [the pinned manifest](beacheye-source.json).
The resolver requires `majidnow/BeachEye` and `ver_50_remaster`; alternate
repository, branch and revision build options have been removed.

</details>

### Private native dependency

BeachEye source is resolved through authenticated GitHub CLI into an external
cache. The build verifies repository access, privacy and pinned revisions;
it stops if these checks fail. Private source and generated DLLs are not
tracked in this repository. The resolver applies desktop compatibility and
lossless numeric-export transformations only to that external cache.

All relay read/write, measurements and events use **BeachEye
`ver_50_remaster`**, pinned to `222c24eb813b9798a5eab42a3fed501892f61f26`
(branch head checked on 2026-10-13). A device reporting build 51 still uses
this branch's `DisablePoints(model, build)` mapping; no separate revision-51
DLL is selected. FC22AR build 51 uses 410 binary and 122 analog points in a
300-byte packed BI/AI response.

Both **FC22AR (auto recloser)** and **FC22S (sectionalizer)** use the company
maps for build 50 and builds greater than 50. INFO retains its full 16-bit
build number; the bridge prevents overflow in the company's 8-bit revision
API. Simulated read/write and measurement tests cover builds 50, 51, 52, 100,
255, 256, 257, 306 and 65535 for both models. Later builds work with the current
company wire format; a future firmware format change requires a new source
audit. See [compatibility and cleanup details](docs/UPSTREAM_SYNC.md#single-source-compatibility-and-cleanup).

Event reception handles the 16-bit wire length independently of the company's
5 KiB outgoing limit, including 5,512-byte responses. Serialized BI/AI/Counter
streams and legacy rings share the company point map. Event record sizes come
from the pinned BeachEye schema; complete-stream validation also recognizes
deployed short Counter records caused by the older company serializer. Layout
selection does not depend on a fixed response size, device model or build.
Both 16-bit and 32-bit transmitted Counter values retain their width.
Interrupted downloads
retry twice; invalid responses are saved with device metadata under
`%LOCALAPPDATA%\DEVolf\diagnostics\events-response.bin` and `.json`.
See [event verification and remaining limits](docs/UPSTREAM_SYNC.md#event-reception-correction).

## Features

| Area | Capabilities |
| --- | --- |
| Connection and status | LAN connection, native handshake with legacy fallback, device identity, alarms and operating state. |
| Measurements and events | Revision-aware analog/binary/counter values, timestamps and 32-bit counters. |
| General settings | Measurement, DNP3/IEC configuration, ports, digital I/O, functions, synchronization, security and heater settings. |
| Protection and TCC | FC22AR/FC22S menus, four groups, UV/OV stages, IEC/ANSI curves and current bounds. |
| Signals and analysis | Capture history, waveform viewing, zoom/pan, RMS, phasors, harmonics and sequence quantities. |
| Device operations | Settings read/write, firmware/bootloader transfer and device reset. |
| EmWolf | EWS2 setup/projects/scenarios, digital-input transitions, result interpretation and PDF reports. |
| FC22 Tester | Inspection sessions, persistent form/test values, company checklist PDFs and Windows printing. |

Current 3,439-byte and deployed 3,243-byte revision-50 settings layouts retain
unchanged device bytes. Company `master` disables engineering-range numeric
validation; DEVolf keeps actual storage/wire bounds and precise units. See
[the numeric audit](docs/NUMERIC_SETTINGS_AUDIT.md) and
[all 1,252 numeric paths](docs/NUMERIC_SETTINGS_AUDIT.csv).

The internal `wolfeye` package, native DLL names and schema identifiers are
retained for ABI compatibility. The product name and EXE are **DEVolf**.

## Company file mapping

Reference: [company WolfEye master](https://github.com/majidnow/wolfeye/tree/989f9fffe4b58bce5b98213de945625780addcda),
commit `989f9fffe4b58bce5b98213de945625780addcda`.

[The complete file-by-file inventory](docs/UPSTREAM_SYNC.md#file-by-file-mapping)
accounts for **all 60 tracked master entries**, with source links, destination
files and an explicit treatment for each file: retained, adapted, split,
replaced, removed, external or unported.

| Company source | Main DEVolf counterpart |
| --- | --- |
| `WolfEye/src/main.cpp`, `include/main.h` | [Application entry](code/main.py) and [MainWindow](code/wolfeye/widgets/main_window.py). |
| `SettingsView.cpp`, `SettingsView.h` | [General/Protection editors](code/wolfeye/widgets/config_pages.py), [schema](code/wolfeye/config_schema.py), [native mapping](code/wolfeye/services/native_config.py) and [numeric limits](code/wolfeye/numeric_schema.py). |
| `TCCCalculator.cpp`, `TCCCalculator.h` | [TCC calculations, editor and chart](code/wolfeye/widgets/tcc_chart.py). |
| `MeasurementsView`, `EventViewer`, `FaultViewer` | [Qt pages](code/wolfeye/widgets/pages.py), [device service](code/wolfeye/services/device_service.py), [native decoding](code/wolfeye/services/beacheye.py). |
| `EmWolf.cpp`, `EmWolf.h` | [EmWolf page](code/wolfeye/widgets/emwolf_page.py), [EWS2 protocol](code/wolfeye/services/emwolf_protocol.py) and [reports](code/wolfeye/services/emwolf_report.py). |
| `DataProvider/include`, `src`, `cJSON` | [Six required CRC/JSON/configuration files](code/native/DataProvider); unused provider/scenario/timer copies were removed. Active transport is the [native adapter](code/native/beacheye/data_provider_adapter.cpp). |
| `DataProvider/BeachEye` submodule | [Pinned dependency manifest](beacheye-source.json) and [authenticated resolver](resolve-beacheye-source.ps1). |
| Visual Studio projects, resources and ImGui helpers | [PowerShell build](build.ps1), [CMake](code/native/beacheye/CMakeLists.txt), Qt and [assets](code/assets). |

A counterpart identifies implementation responsibility, not a byte-identical
port. The complete inventory marks partial workflows, unported `LogViewer`
and the DNP3 Master sample, and the difference between master's BeachEye
gitlink and DEVolf's revision pins.

## Project layout

```text
code/main.py              Application entry point
code/wolfeye/widgets/     Qt pages, dialogs and charts
code/wolfeye/services/    Device, protocol, analysis and report services
code/native/beacheye/     C ABI, active transport adapter and CMake build
code/native/DataProvider/ Six required CRC/JSON/configuration files
code/assets/             Branding, SVG controls and form templates
tests/                   Regression tests
docs/                    Mapping, audits, release and publication details
build.ps1                Complete release build
build-native.ps1         Pinned ver_50_remaster native build
requirements.txt         Pinned Python dependencies
build/                   Generated intermediates and logs
Dist/                    Generated Windows EXE
```

Relay pages share `DeviceService`; the EmWolf page owns its EWS2 connection.
FC22 Tester consumes the existing device state. Inspection sessions are
generated under `sessions/`; supplied FC22AR/FC22S scenarios remain in their
named scenario folders.

## Documentation

- [Complete company file mapping and DEVolf module responsibilities](docs/UPSTREAM_SYNC.md)
- [Numeric settings audit](docs/NUMERIC_SETTINGS_AUDIT.md) and [field inventory](docs/NUMERIC_SETTINGS_AUDIT.csv)
- [Release notes](docs/RELEASE_NOTES.md)
- [Public release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md)
