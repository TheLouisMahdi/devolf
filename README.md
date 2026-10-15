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

To fetch the latest company `ver_50_remaster` revision on each build:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -UpdateBeachEye
```

The update records the selected SHA in `beacheye-source.json`. Omitting the
switch repeats that recorded SHA. See [guidebuild.txt](guidebuild.txt) for the
English command reference, native-only builds and custom build options.

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

Normal builds use [the pinned manifest](beacheye-source.json); `-UpdateBeachEye`
resolves the latest company branch commit and refreshes that pin.
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
`ver_50_remaster`**, currently pinned to `18d5e1696730c1167cae854f83d77eb0c20d9ac5`
(branch head checked on 2026-10-14). A device reporting build 51 still uses
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

Frame transmission and reception use the protocol's two-byte length field,
without a general 5 KiB payload rejection. Native requests reserve one byte
for the company sequence; legacy requests use the full frame body. Firmware
file chunks retain the company's `MAX_DATA_SIZE - 4` partitioning.
Complete measurements with a different point count are displayed by wire index
(`BI N`, `AI N`, `Counter N`); matching profiles retain company names. Empty
channels and repeated channel blocks are supported without dropping values.
Event reception includes 5,112-byte and larger responses. Serialized BI/AI/Counter
streams and legacy rings share the company point map. Event record sizes come
from the pinned BeachEye schema; complete-stream validation also recognizes
deployed short Counter records caused by the older company serializer. Layout
selection does not depend on a fixed response size, device model or build.
Both 16-bit and 32-bit transmitted Counter values retain their width.
Event file downloads follow the device's reported length without a desktop
1 MiB rejection; chunk sequences wrap within their two-byte field. Interrupted downloads
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

### FC22 Test Lots

FC22 Tester uses four fixed workflow steps: Setup, Form data, Run test and
Report. The test table keeps each observation beside its source and verdict;
hover over the parameter or result for the exact acceptance rule. Use **All
measurements & test results** for the complete diagnostic list. Setup exposes
WI03 worksheets and shared EmWolf controls; enable **Custom acceptance rules /
Test Lot JSON** to load or edit additional rules, including percent tolerances.
Blank manual fields can be completed on paper. Form groups adapt to the window
width, and test navigation stays visible while measurements scroll.

The company procedure is [code/test_lots/wi03.json](code/test_lots/wi03.json),
transcribed from **WI03 revision 00, 1403/01/25, 8 pages**. It contains 38 test
modes, 104 checks and 14 numeric input specifications for HMI, Keypad, Analog,
Digital, Power, Base, Relay & key, Modem, AR DRV Power and LLDL. Every mode keeps
its model, setup, units, source expressions and Word page references.

In **FC22 Tester → Setup → WI03**, select a mode and open its worksheet. Establish
the displayed input/setup conditions, confirm them, and record the measurements.
Applicable DUT voltage/current readings use the conversions already present in
System Status (raw volts to kV, raw current divided by ten to A). Oscilloscope,
multimeter and qualitative observations are recorded explicitly as manual.
Frequency is entered in verified Hz; WI03 does not establish raw F ABC/F RST
scaling. No stimulus amplitude calibration or automatic board commands are
inferred from the procedure.

Tolerance endpoints are inclusive. Explicit `X>13.0 V` and `11.4<X<11.6` remain
strict. The IN differential entry **2.7±3.3 V** and the three Charger/Battery
ranges with tolerances on their boundaries remain verbatim and **require review**.
Where WI03 supplies no numerical acceptance limit, the program leaves the check
NOT_TESTED rather than inventing a threshold. Those cases cannot automatically
approve a report. The previous illustrative frequency/trip/charging limits were
removed; acceptance defaults now come from this procedure.

Saving a worksheet preserves the exact rules, source identity, setup confirmation,
model, units, timestamps and individual results in `session.json`. Applicable
checklist fields use these recorded engineering-unit values and are protected
from subsequent raw autofill. Manual edits invalidate the corresponding WI03
verdicts; failed, missing, changed or review-required criteria trigger the PDF
warning. The original Word file is read-only source material and is not bundled
or published with DEVolf. Edit/load the JSON to maintain procedure data; protocol
and device connections retain their existing responsibilities.

FC22 Tester shares the **existing EmWolfConnection and EWS2 protocol** with the
EmWolf tab. Its Setup page can connect/disconnect the board, run the current
EmWolf project and open the scenario editor. Both tabs show the same connection
state and endpoint. Connecting the test board and reading the FC22 DUT remain
the existing separate EmWolf and DeviceService responsibilities.

Without loading a lot, incoming DUT snapshots automatically fill **22 numeric
fields** (phase/line voltages, currents, total powers, both frequencies and PF)
and **3 status fields** (AC supply, door and lockout), plus the existing device
identity/software fields. While Tester is visible, its automatic-update option
requests DUT measurements every two seconds through DeviceService and waits
while device operations are busy. Manual reads are also available. Values use
the same raw units as Measurements, with no inferred scaling or synthetic values.

Confirmed EmWolf scenario times and feedback are recorded even without a lot.
The results view distinguishes **MEASURED** values from acceptance verdicts.
Use a Test Lot to define the acceptance conditions for protection and digital
tests; receiving feedback or a status bit alone does not declare those tests
PASS. Serial numbers, visual inspections and measurements unavailable from
the existing protocols remain manual. Session JSON records measurement sources,
timestamps and confirmed EmWolf feedback. The optional external-equipment
adapter is separate from the shared EmWolf board controls.

For additional custom acceptance rules, create a Test Lot or load a version-1
JSON lot. Select the DUT model and assign each test
to a checklist field. The source editor uses BeachEye's point catalog, including
the connected DUT's exact build when available. Offline lots accept company
points from revision 50 and newer; an unavailable reading remains NOT_TESTED.

- `analog`, `binary` and `counters` consume the existing DeviceService snapshots.
  Analog and counter values are the **same raw values shown in Measurements**;
  the unit label does not convert them. Set acceptance limits in those units.
  The frequency source is `analog.F ABC` (load side: `analog.F RST`).
- `emwolf.scenario_N.trip_time_ms` consumes a confirmed trip from the Nth scenario
  of an EmWolf run started after selecting the lot. Time is converted to milliseconds.
- `external.FIELD` accepts equipment measurements through the optional Test Bench
  listener, or the existing external-value adapter. Start the listener explicitly
  and use the displayed session ID and temporary token. Its protocol is a 4-byte
  network-order length followed by a JSON measurement object.
  Each device's sequence number must increase.

Example bench object (prefix its UTF-8 JSON with the 4-byte byte length):

```json
{"version":1,"source":"testbench","type":"measurement","device":"meter_1","sequence":1,"session_id":"CURRENT_SESSION_ID","token":"CURRENT_LISTENER_TOKEN","field":"charging_voltage","value":27.2,"unit":"V"}
```

Changing the lot, DUT identity or session stops the bench listener and resets
its input context. Queued measurements from an earlier listener cannot verify
the new context. Live readings expire after `max_age_seconds` (default 30);
timeouts advance even when no new response arrives. EmWolf deadlines start when
its run begins. Stability counts distinct received samples, not timer ticks.

Every configured test must have a verified PASS before the lot is complete.
Editing an automatic field manually marks it NOT_TESTED until a fresh source
measurement arrives. Generating a PDF with an incomplete lot requires acknowledging
the warning; the exact rules and individual verdicts remain in `session.json`.
All Test Lot regression tests are in the root `tests/` directory and run during
the normal build.

## Documentation

- [Complete company file mapping and DEVolf module responsibilities](docs/UPSTREAM_SYNC.md)
- [Numeric settings audit](docs/NUMERIC_SETTINGS_AUDIT.md) and [field inventory](docs/NUMERIC_SETTINGS_AUDIT.csv)
- [Release notes](docs/RELEASE_NOTES.md)
- [Public release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md)
- [English build command reference](guidebuild.txt)
