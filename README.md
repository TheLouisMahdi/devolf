# DEVolf

## Build

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

Output: `Dist\DEVolf.exe`

The command requires an authenticated GitHub account with read access to the
private BeachEye repository. Complete the one-time access setup below before
the first build.

DEVolf is a Windows engineering console for Fartak Control FC22 recloser and sectionalizer devices. It connects to a device over LAN, reads live status and measurements, edits and writes protection/settings data, decodes events and captured signals, analyzes protection behavior, runs EmWolf test scenarios, and produces FC22 inspection reports. The internal `wolfeye` package, native DLL names, and settings schema identifiers are intentionally retained for compatibility with the company WolfEye/BeachEye ABI.

## Private BeachEye dependency

BeachEye is a private build-time dependency. This repository intentionally does
not contain a BeachEye source mirror, generated BeachEye DLL, or a source patch
containing private code. `beacheye-source.json` records only the private
repository name and the immutable revision-50 and revision-51 commit IDs.

### One-time access setup

1. Install [GitHub CLI](https://cli.github.com/) and Git.
2. Authenticate with a GitHub account that has read access to
   `majidnow/BeachEye`:

   ```powershell
   gh auth login
   gh auth status
   gh repo view majidnow/BeachEye
   ```

3. Install CMake, 64-bit Python 3.11, and a 64-bit C/C++ compiler supported by
   CMake (for example Visual Studio Build Tools with Desktop development with C++).
4. Run the build command at the top of this file from the repository root.

### How source resolution works

`build.ps1` calls `build-native.ps1`, which calls
`resolve-beacheye-source.ps1`. The resolver:

1. reads the repository, branches, and full commit SHAs from
   `beacheye-source.json`;
2. asks GitHub through `gh api` to confirm that the dependency repository is
   private and that the authenticated user can access it;
3. resolves and verifies the requested commit;
4. clones the private source outside this repository, by default under
   `%LOCALAPPDATA%\DEVolf\BeachEye`;
5. applies the narrowly scoped desktop-safety transformation only to that
   external cache; and
6. compiles the revision-specific bridge DLLs into ignored build directories
   before running tests and packaging `DEVolf.exe`.

The build fails closed if `gh` is missing, authentication fails, the repository
is public, a pinned commit cannot be found, or the expected private source layout
does not match. It never falls back to bundled BeachEye source.

To place the private cache somewhere else, set an absolute path before building:

```powershell
$env:DEVOLF_BEACHEYE_CACHE = "D:\PrivateBuildCache\DEVolf-BeachEye"
```

To build an explicitly selected private revision, pass all source selectors and
use a full 40-character commit SHA:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 `
  -BeachEyeRepository "owner/private-repository" `
  -BeachEyeBranch "ver_50_remaster" `
  -BeachEyeCommit "0123456789abcdef0123456789abcdef01234567" `
  -BeachEyeRevision 50 `
  -PythonExecutable "C:\Python311\python.exe"
```

Omitting `-BeachEyeBranch`, `-BeachEyeCommit`, and `-BeachEyeRepository` uses
the pinned defaults. Authentication is handled by GitHub CLI; never put a token,
password, private source archive, or generated native DLL in this repository.

## Publication status

DEVolf is intended to be published from the clean `TheLouisMahdi/devolf`
repository. All files tracked there are part of the public DEVolf source tree;
BeachEye is the only restricted dependency. Its source remains in the original
private repository and is downloaded directly by GitHub CLI during the
PowerShell build only for authenticated users who already have access.

Users without BeachEye access can clone and inspect DEVolf, but the native build
fails with an explicit access error and does not receive private source or DLLs.
See [PUBLIC_RELEASE_CHECKLIST.md](PUBLIC_RELEASE_CHECKLIST.md) for the final
visibility checks.

## Features

| Area | Included capabilities |
| --- | --- |
| Device connection | LAN/IP connection to FC22 devices, device-type selection, native protocol handshake, automatic one-time legacy fallback, connection state, and safe disconnect. |
| System status | Device identity, firmware revision, operating state, alarms, binary states, counters, and live status refresh. |
| Measurements | Live analog measurements, currents, voltages, frequency, power quantities, binary inputs, and counters using revision-specific point maps. |
| General configuration | Measurement, DNP3, IEC, port, I/O, system, function, security, and heater settings. |
| Digital I/O and indicators | Digital-input states and validation timing, independent digital-output recognition/pulse timing, conditional operation, and configurable front-panel LED behavior. |
| Protection | Separate FC22AR and FC22S protection pages, complete current UV/OV stages and voltage AR modes, protection groups, device-specific limits/defaults, synchronized shared settings, and preserved unsupported fields. |
| TCC tools | IEC/ANSI curve calculations, protection-element editing, min/max current-bounded plotting for fast-trip curves, interactive charting, zoom, pan, and curve comparison. |
| Settings transport | Read/write of current 3,439-byte settings and deployed 3,243-byte revision-50 settings, with byte preservation for unchanged data and status-based write completion. |
| Signal Viewer | Capture selection and history, current/voltage waveforms, channel visibility, zoom, pan, reset, inspection, and standalone viewing. |
| Signal analysis | RMS, fitted phasors, frequency, harmonics, symmetrical sequences, power-quality values, directional quantities, and protection indications. |
| Event Viewer | Device-event retrieval, revision-aware binary/analog/counter decoding, 32-bit counter values, timestamps, point values, and event-history presentation. |
| Firmware operations | Firmware and bootloader transfer, progress reporting, device reset, and operation-state protection. |
| EmWolf | EWS2 project/setup/scenario configuration, CRC-protected protocol frames, scenario execution, digital-input transition tracking, result interpretation, and branded PDF reports. |
| FC22 Tester | FC22AR/FC22S inspection sessions, form-data persistence, shared live device identity, recorded test values, company checklist PDF generation, and direct Windows printing. |
| Desktop behavior | Responsive scrollable pages, high-DPI handling, scalable SVG controls, Fusion styling, guarded mouse-wheel value changes, application identity, and taskbar/window icons. |

## Visual changes from the previous release

- The window title, top brand bar, standalone Signal Viewer/Analysis titles,
  report metadata/footer, and generated executable name now use `DEVolf`.
- **General → Digital Outputs** has a separate **Recogn. (s)** column between
  output state and action; pulse duration remains in **Pulse (s)**.
- **Protection → Voltage / Frequency / ABR** exposes UV12, UV13, UV22, and
  UV23 alongside the original undervoltage stages.
- **Protection → Master Extensions** exposes OV12, OV13, OV22, and OV23 plus
  their voltage auto-reclose modes.
- Fast-trip OC/EF/NPS rows and the TCC dialog now expose **Max Mode** and
  **Max. current multiplier**. Curves start at the configured minimum-current
  multiplier and, when enabled, stop at the configured maximum.
- The TCC selector caption is now **Show Elements**. The Event Viewer can also
  display **Counter** records and their full 32-bit values.

The analog-value correction, invalid-event filtering, BeachEye desktop guard,
and native serialization fixes are behavioral changes and do not add visible
controls.

One source tree produces one 64-bit Windows release. It does not target 32-bit Windows. The application uses Qt's Fusion style, Qt dialogs, scalable SVG assets, and explicit high-DPI handling so the client area remains as consistent as possible between Windows versions.

## Windows build

The supported build uses Python 3.11 x64, PySide6/Qt 6 and PyInstaller 6.
It targets 64-bit Windows 10/11. Windows 7/8 and 32-bit operating systems are
not supported; ARM64 execution through emulation has not been verified.

Requirements:

- Python 3.11 x64 (the Python launcher `py -3.11` can create `.venv`).
- CMake available on `PATH`.
- A 64-bit C/C++ toolchain available to CMake, such as Visual Studio Build Tools
  with the Desktop development with C++ workload.
- GitHub CLI, Git, and authorized read access to the private BeachEye dependency.

Run `build.ps1` without mode flags. The script builds both native decoder DLLs,
checks the Python and packaged EXE architecture, runs the tests, packages a
single-file executable, and performs the Qt startup smoke test. It no longer
accepts `-Legacy`, `-Modern`, or `-UniversalToolchainRoot`.

For offline Python package installation, supply `-Wheelhouse` with 64-bit wheels
for `requirements.txt`. Private BeachEye source access is still required.

Removing the old Windows build mode does not remove the device's native-first
protocol fallback or support for deployed settings layouts.

## Program map

```text
code/main.py
└── MainWindow
    ├── System Status / Measurements / Events / Signal Viewer
    ├── General / Protection configuration
    ├── EmWolf scenarios and reports
    └── FC22 Tester sessions and inspection forms
         │
         ├── DeviceService ── LAN transport and operation coordination
         │    ├── beacheye.py ── Python/native ABI boundary
         │    │    └── wolfeye_beacheye*.dll ── C/C++ protocol and settings bridge
         │    └── native_config.py ── UI configuration ↔ native settings mapping
         │
         ├── signal_analysis.py ── phasors, harmonics, sequences, protection checks
         ├── emwolf_protocol.py ── EWS2 frames, scenarios, and EmWolf connection
         └── PDF/session services ── persistent sessions and generated reports
```

The relay/configuration widgets never open their own device sockets. They emit actions through `DeviceService`, which owns the FC22 connection and selects the native or legacy protocol. `EmWolfPage` separately owns the verified EWS2 connection to the EmWolf test set, while `Fc22TesterPage` only consumes the existing device state. Native settings are decoded and encoded through the C ABI so untouched device bytes remain unchanged.

## Repository layout

```text
.
├── code/
│   ├── main.py                 Application entry point
│   ├── assets/                 Icons, SVG controls, logos, and PDF templates
│   ├── wolfeye/                Python application package
│   │   ├── widgets/            Qt pages, dialogs, tables, and charts
│   │   └── services/           Protocol, device, analysis, persistence, and reports
│   └── native/                 C/C++ device ABI and protocol implementation
├── tests/                      Automated unit and integration tests
├── build.ps1                   Complete test/package/smoke-test pipeline
├── build-native.ps1            Native bridge build and compatibility checks
├── resolve-beacheye-source.ps1 Authenticated private dependency resolver
├── requirements.txt            Optional modern-development dependencies
├── RELEASE_NOTES.md            Release branch features and behavioral changes
├── UPSTREAM_SYNC.md             Commit-by-commit company-source traceability
├── build/                      Generated intermediate build files (not source)
└── Dist/                       Generated Windows executables
```

## Application source files

### Core package

| File | Responsibility |
| --- | --- |
| `code/main.py` | Configures Windows application identity, DPI behavior, Fusion style, assets, `QApplication`, and the main window. It also implements the packaged EXE smoke-test entry point. |
| `code/wolfeye/qt.py` | PySide6/Qt 6 import boundary and common UI helpers. |
| `code/wolfeye/styles.py` | Generates the shared application stylesheet and references the scalable SVG control assets. |
| `code/wolfeye/models.py` | Shared data records for device identity, measurement snapshots, and event records. |
| `code/wolfeye/config_schema.py` | Canonical UI configuration structure, defaults, choices, ranges, and protection-group defaults. |
| `code/wolfeye/point_schema.py` | Canonical analog, binary, counter, and named device point catalogs used by decoding and the UI. |
| `code/wolfeye/__init__.py` | Marks `wolfeye` as the application package. |

### UI widgets

| File | Responsibility |
| --- | --- |
| `code/wolfeye/widgets/main_window.py` | Builds the top-level tabs, menus, device-operation footer, responsive scroll containers, signal wiring, configuration loading/saving, and guarded mouse-wheel behavior. |
| `code/wolfeye/widgets/pages.py` | Implements System Status, Measurements, Signal Viewer, waveform plotting, capture history, standalone viewer, and Event Viewer pages. |
| `code/wolfeye/widgets/config_pages.py` | Implements General and Protection editors, including communication, I/O, indicators, functions, FC22AR/FC22S groups, and responsive configuration tables. |
| `code/wolfeye/widgets/tcc_chart.py` | Implements IEC/ANSI trip-time calculations, interactive TCC plotting, element editing, zoom, pan, and chart dialogs. |
| `code/wolfeye/widgets/signal_analysis.py` | Displays signal-analysis summaries and detailed channel, phasor, sequence, harmonic, directional, and protection results. |
| `code/wolfeye/widgets/emwolf_page.py` | Implements the EmWolf setup/scenario UI, device connection, test execution, digital-input tracking, project files, and report workflow. |
| `code/wolfeye/widgets/fc22_tester_page.py` | Implements the Setup → Form Data → Run Test → Report inspection workflow without creating a second device connection. |
| `code/wolfeye/widgets/native_settings.py` | Lossless tree editor for the exact JSON settings exposed by the native company ABI. |
| `code/wolfeye/widgets/__init__.py` | Marks the widgets directory as a Python package. |

### Services

| File | Responsibility |
| --- | --- |
| `code/wolfeye/services/device_service.py` | Owns relay communication, native-first/legacy fallback, frame sequencing, live reads, settings operations, reset, and firmware/bootloader transfers. |
| `code/wolfeye/services/beacheye.py` | Loads the native DLL through `ctypes` and exposes device-info, measurement, event, signal, frame, and settings encode/decode operations to Python. |
| `code/wolfeye/services/native_config.py` | Converts between the normalized UI configuration and the company native settings JSON while preserving unsupported or untouched fields. |
| `code/wolfeye/services/signal_analysis.py` | Calculates fitted phasors, RMS values, frequency, harmonics, symmetrical sequences, power quality, directional quantities, and protection indications. |
| `code/wolfeye/services/emwolf_protocol.py` | Defines EmWolf projects, setups, scenarios, analog outputs, EWS2 frame encoding/decoding, CRC, debouncing, SSH startup, and TCP connection handling. |
| `code/wolfeye/services/emwolf_report.py` | Collects EmWolf execution results and generates branded PDF test reports. |
| `code/wolfeye/services/fc22_session.py` | Persists each FC22 inspection session atomically and restores its form/test values. |
| `code/wolfeye/services/fc22_form_pdf.py` | Fills the FC22AR or FC22S company PDF template using recorded inspection data. |
| `code/wolfeye/services/windows_pdf_printer.py` | Rasterizes generated PDFs and sends them to the Windows default printer through GDI/Winspool. |
| `code/wolfeye/services/windows_shell.py` | Applies the Windows AppUserModelID and native window/taskbar icons and releases their handles safely. |
| `code/wolfeye/services/__init__.py` | Marks the services directory as a Python package. |

## Native source files

| Path | Responsibility |
| --- | --- |
| `code/native/beacheye/CMakeLists.txt` | Defines the native DLL build, source selection, runtime linkage, and revision profile. |
| `code/native/beacheye/bridge.cpp`, `bridge.h` | Stable exported C ABI used by Python for decode, encode, settings, and provider operations. |
| `code/native/beacheye/data_provider_adapter.cpp`, `data_provider_adapter.h` | Adapts the company `DataProvider` callbacks and transport behavior to the exported bridge API. |
| `code/native/beacheye/compat/` | Minimal compatibility headers required by the native company sources. |
| `code/native/DataProvider/src/` | TCP provider, timers, CRC, and EmWolf scenario implementation used by the native bridge. |
| `code/native/DataProvider/include/` | Public types and declarations for the provider, setup, scenario, logging, timing, and configuration. |
| `code/native/DataProvider/cJSON/` | Bundled C/C++ JSON parser and helper implementation used by native settings code. |

BeachEye source is present only in the authenticated external cache. Generated
`wolfeye_beacheye.dll` files are ignored build artifacts. When revision 50 is
selected, the build also produces `wolfeye_beacheye_51.dll` so measurement
decoding can switch to the exact revision-51 point profile after identification.

## Build and dependency files

| File | Responsibility |
| --- | --- |
| `build.ps1` | Builds the x64 release, checks Python and packaged EXE architecture, runs all tests, packages a one-file EXE, and smoke-tests the result. |
| `build-native.ps1` | Builds revision 50/51 native DLLs using the available CMake toolchain. |
| `resolve-beacheye-source.ps1` | Requires GitHub CLI authentication, verifies that BeachEye is private, resolves pinned commits, and maintains an external private cache. |
| `requirements.txt` | Pinned Python 3.11 x64 dependencies for the Windows release. |
| `beacheye-source.json` | Records only the private repository identifier, branch names, and immutable revision-50/51 commit IDs used by the resolver. |
| `.gitattributes` | Repository file and line-ending attributes. |
| `.gitignore` | Excludes generated environments, caches, build intermediates, and packaged outputs. |

## Tests

| File | Coverage |
| --- | --- |
| `tests/test_device_service.py` | Native/legacy connection selection, fallback, request routing, write status, and update operations. |
| `tests/test_native_bridge.py` | Native ABI, exact settings round trips, revision-specific measurement/event profiles, framing, and provider behavior. |
| `tests/test_emwolf_protocol.py` | CRC, frames, scenarios, projects, debouncing, connection shutdown, and command construction. |
| `tests/test_emwolf_report.py` | EmWolf run interpretation, digital-input transitions, reclose results, and generated PDFs. |
| `tests/test_fc22_tester.py` | Session persistence, form PDF values, tester workflow, and shared device identity. |
| `tests/test_protection_ui.py` | Protection menus, company limits/defaults, TCC behavior, settings preservation, and device-specific controls. |
| `tests/test_pages.py` | Status-page values and device-operation availability. |
| `tests/test_responsive_ui.py` | Responsive I/O layout and focus-required mouse-wheel value changes. |

## Runtime and generated data

- `code/assets/` contains application branding, SVG control graphics, and the FC22 company form templates.
- `sessions/` contains persisted FC22 Tester sessions created by operators.
- `fc22ar_3shot_fault_scenarios_DI1_Open_DI2_Close/` and `fc22s_fault_scenarios_DI1_Close_DI2_Open/` contain the supplied device test scenarios.
- `build/` and `Dist/` are generated by the build scripts and are not application source directories.
