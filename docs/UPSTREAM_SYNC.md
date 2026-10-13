# Upstream synchronization manifest

This branch was reconciled on 2026-10-12 against these immutable company
revisions:

- WolfEye `master`: `989f9fffe4b58bce5b98213de945625780addcda`
- BeachEye `ver_50_remaster`: `110dd0c9d25e0a700c2662fe3442e117940ad2cf`

`beacheye-source.json` pins the full BeachEye SHAs. The authenticated resolver
verifies that the configured repository is private, downloads the selected
revision to `%LOCALAPPDATA%\DEVolf\BeachEye`, and builds from that external
cache. No BeachEye source mirror or generated BeachEye DLL is stored in the
public repository tree.

## WolfEye commit map

| Upstream commit | Company change | Location in this branch | Verification |
| --- | --- | --- | --- |
| `e9ffe71` | Revision-50 measurements | Existing revision-selected native decoder in `beacheye.py` and generated `wolfeye_beacheye*.dll` files | Native bridge profile tests |
| `0b336ae` | Raw ADC signal access | Existing Signal Viewer/native signal decoder | Native signal and UI tests |
| `9cf377d` | Additional undervoltage stages | `config_schema.py`, `native_config.py`, `config_pages.py` | Native round-trip and binding tests |
| `4864819` | Complete voltage protection and AR settings | Protection schema/mapping/editor | UV/OV native round-trip and UI binding tests |
| `eef8221` | Digital-output recognition time | General I/O schema, native mapping, six-column output editor | Payload and responsive-layout tests |
| `cfff784` | TCC “Show Elements” title | `tcc_chart.py` | Protection UI tests |
| `6c27d58` | Analog-value view correction | Existing native dereference/value decoding path | Revision measurement tests |
| `6968c28` | Robust event deserialization | Native event stream decoder plus invalid-timestamp filtering | Tail-tolerance and event tests |
| `989f9ff` | Min/max current curve plotting | TCC schema, settings bridge, editor, and chart | Fast-trip limit binding and round-trip tests |

## BeachEye commit map

The pinned private dependency includes every company source change through
`110dd0c`, including `7681773`/`ec30eba` (digital-output time and JSON fixes),
`e5aead6` (point updates), `fdddabf` (heater menu fix), `f36e6a7` (Windows
guard), `950d122` (BI/AI/CC stream events), and `110dd0c` (`C_MAX`).

The bridge uses source-capability checks so the pinned rev-50 API and the older
rev-51 measurement-profile source can still be built together. `C_MAX` remains
outside BeachEye's device `Settings` serialization lists exactly as upstream;
the bridge exposes it to the desktop TCC session without inventing incompatible
wire bytes.

## Numeric master alignment (2026-10-13)

The numeric editing behavior was audited against WolfEye `master` at the same
`989f9ff` commit. General/Protection editors and the TCC dialog now use shared
storage limits and precise units, with lossless numeric JSON export in the
external private dependency cache. See [the numeric audit](NUMERIC_SETTINGS_AUDIT.md) and
[field inventory](NUMERIC_SETTINGS_AUDIT.csv) for the complete field inventory and checks.

## Reproduction commands

```powershell
gh auth status
gh repo view majidnow/BeachEye
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\resolve-beacheye-source.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-native.ps1
$env:PYTHONPATH = (Resolve-Path .\code).Path
python -m unittest discover -s tests -v
```

These commands require read access to the private dependency. The resolver
refuses public repositories and has no bundled-source fallback.

## File-by-file mapping

This inventory covers **all 60 entries** returned by
`git ls-tree -r 989f9fffe4b58bce5b98213de945625780addcda` in company WolfEye `master`, inspected on
2026-10-13. Each tracked source/header, asset, build file and the BeachEye
gitlink has its own row. Source links use the immutable company commit;
destination links refer to this DEVolf checkout.

The mapping describes inspected implementation responsibilities. A Python
counterpart means that the responsibility was reimplemented or merged; it
does not establish line-by-line equality or complete hardware behavior.
Partial and unported workflows are identified in the notes.

The 20 retained DataProvider files were compared against the exact upstream
blobs: **17 are identical after CRLF/LF normalization and 3 are adapted**.
`tw.png` also matches its destination byte-for-byte. The current CMake target
compiles `DataProvider/src/crc.c` and `DataProvider/cJSON/cJSON.c`; the retained
provider/scenario/timer C++ files are not selected as translation units.

### Dependency boundary

Company master records BeachEye gitlink
`23283b73478b61b244aa344a159d2ad671689bf4`. DEVolf does **not** check out that
gitlink directly: [its dependency manifest](../beacheye-source.json) pins
`110dd0c9d25e0a700c2662fe3442e117940ad2cf` for revision 50 and
`718b40999d2cf80a1469e6a5a35b18353d8dcb34` for revision 51. The authenticated
resolver downloads them outside the repository. Files inside that separate
submodule repository are not entries of the WolfEye master tree counted here.

The original Visual Studio project also references ImGui, ImPlot, Asio,
ImGuiFileDialog, fonts and other files absent from the tracked master tree.
They are not silently counted as ported repository files. Qt replaces the
desktop rendering/dialog stack; the bridge supplies its compatibility headers.

### Complete inventory

| Company master entry | DEVolf destination | Treatment | Responsibility / limit |
| --- | --- | --- | --- |
| [`.gitmodules`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/.gitmodules) | [`beacheye-source.json`](../beacheye-source.json)<br>[`resolve-beacheye-source.ps1`](../resolve-beacheye-source.ps1) | Replaced | Submodule access is replaced by authenticated external dependency resolution. |
| [`DataProvider/BeachEye`](https://github.com/majidnow/wolfeye/tree/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/BeachEye) | [`beacheye-source.json`](../beacheye-source.json)<br>[`resolve-beacheye-source.ps1`](../resolve-beacheye-source.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | External dependency | Master gitlink: 23283b73478b61b244aa344a159d2ad671689bf4. DEVolf separately pins rev-50 and rev-51; no in-tree source copy. |
| [`DataProvider/DataProvider.vcxproj`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/DataProvider.vcxproj) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`DataProvider/DataProvider.vcxproj.filters`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/DataProvider.vcxproj.filters) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`DataProvider/DataProvider.vcxproj.user`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/DataProvider.vcxproj.user) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`DataProvider/cJSON/cJSON.c`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON.c) | [`code/native/DataProvider/cJSON/cJSON.c`](../code/native/DataProvider/cJSON/cJSON.c) | Retained / identical | Compiled directly into the native bridge for private Settings JSON conversion. |
| [`DataProvider/cJSON/cJSON.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON.h) | [`code/native/DataProvider/cJSON/cJSON.h`](../code/native/DataProvider/cJSON/cJSON.h) | Retained / identical | Native JSON declarations used by bridge.cpp and private dependency sources. |
| [`DataProvider/cJSON/cJSON_Helper.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Helper.cpp) | [`code/native/DataProvider/cJSON/cJSON_Helper.cpp`](../code/native/DataProvider/cJSON/cJSON_Helper.cpp) | Retained / identical | Retained upstream helper source; not a current bridge translation unit. |
| [`DataProvider/cJSON/cJSON_Helper.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Helper.h) | [`code/native/DataProvider/cJSON/cJSON_Helper.h`](../code/native/DataProvider/cJSON/cJSON_Helper.h) | Retained / identical | Retained upstream helper declaration file. |
| [`DataProvider/cJSON/cJSON_Utils.c`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Utils.c) | [`code/native/DataProvider/cJSON/cJSON_Utils.c`](../code/native/DataProvider/cJSON/cJSON_Utils.c) | Retained / identical | Retained JSON utility source; not a current bridge translation unit. |
| [`DataProvider/cJSON/cJSON_Utils.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Utils.h) | [`code/native/DataProvider/cJSON/cJSON_Utils.h`](../code/native/DataProvider/cJSON/cJSON_Utils.h) | Retained / identical | Retained JSON utility declarations. |
| [`DataProvider/include/ConfigureDef.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/ConfigureDef.h) | [`code/native/DataProvider/include/ConfigureDef.h`](../code/native/DataProvider/include/ConfigureDef.h) | Retained / identical | SCADA/configuration enums retained; definitions are available on the native include path. |
| [`DataProvider/include/DataProvider.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/DataProvider.h) | [`code/native/DataProvider/include/DataProvider.h`](../code/native/DataProvider/include/DataProvider.h) | Retained / adapted | Adapted provider declarations retained; the active ABI uses data_provider_adapter.cpp rather than compiling DataProvider.cpp. |
| [`DataProvider/include/DataProviderTypes.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/DataProviderTypes.h) | [`code/native/DataProvider/include/DataProviderTypes.h`](../code/native/DataProvider/include/DataProviderTypes.h) | Retained / adapted | Adapted provider/device/status types retained as compatibility/reference declarations. |
| [`DataProvider/include/EmWolfScenario.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/EmWolfScenario.h) | [`code/native/DataProvider/include/EmWolfScenario.h`](../code/native/DataProvider/include/EmWolfScenario.h) | Retained / identical | Scenario declarations retained; active scenario execution/serialization is in services/emwolf_protocol.py. |
| [`DataProvider/include/EmWolfSetup.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/EmWolfSetup.h) | [`code/native/DataProvider/include/EmWolfSetup.h`](../code/native/DataProvider/include/EmWolfSetup.h) | Retained / identical | Setup declarations retained; active Python Setup/Project model is in services/emwolf_protocol.py. |
| [`DataProvider/include/EmWolfUtils.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/EmWolfUtils.h) | [`code/native/DataProvider/include/EmWolfUtils.h`](../code/native/DataProvider/include/EmWolfUtils.h) | Retained / identical | EmWolf helper definitions retained; active Python protocol supplies validation and serialization. |
| [`DataProvider/include/TimeUnit.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/TimeUnit.h) | [`code/native/DataProvider/include/TimeUnit.h`](../code/native/DataProvider/include/TimeUnit.h) | Retained / identical | Timer unit definitions retained with upstream timer files. |
| [`DataProvider/include/Timer.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/Timer.h) | [`code/native/DataProvider/include/Timer.h`](../code/native/DataProvider/include/Timer.h) | Retained / identical | Timer declarations retained; Timer.cpp is not selected by the current bridge CMake target. |
| [`DataProvider/include/crc.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/crc.h) | [`code/native/DataProvider/include/crc.h`](../code/native/DataProvider/include/crc.h) | Retained / identical | CRC declarations used by the compiled native CRC implementation. |
| [`DataProvider/include/logger.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/logger.h) | [`code/native/DataProvider/include/logger.h`](../code/native/DataProvider/include/logger.h) | Retained / identical | Company logger header retained; desktop compatibility logger is also supplied in beacheye/compat/logger.h. |
| [`DataProvider/src/DataProvider.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/DataProvider.cpp) | [`code/native/DataProvider/src/DataProvider.cpp`](../code/native/DataProvider/src/DataProvider.cpp) | Retained / adapted | Adapted source retained but not compiled by current CMake; transport/update state machine lives in data_provider_adapter.cpp and DeviceService. |
| [`DataProvider/src/EmWolfScenario.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/EmWolfScenario.cpp) | [`code/native/DataProvider/src/EmWolfScenario.cpp`](../code/native/DataProvider/src/EmWolfScenario.cpp) | Retained / identical | Retained source, not a current bridge translation unit; Python emwolf_protocol.py executes the scenario workflow. |
| [`DataProvider/src/Timer.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/Timer.cpp) | [`code/native/DataProvider/src/Timer.cpp`](../code/native/DataProvider/src/Timer.cpp) | Retained / identical | Retained source, not a current bridge translation unit; active adapter uses chrono/thread timing. |
| [`DataProvider/src/crc.c`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/crc.c) | [`code/native/DataProvider/src/crc.c`](../code/native/DataProvider/src/crc.c) | Retained / identical | Compiled directly into the native bridge; Python emwolf_protocol.py has the EWS2 CRC implementation. |
| [`WolfEye.sln`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye.sln) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Visual Studio solution replaced by Python packaging and GCC/Ninja native build. |
| [`WolfEye/DeviceInfoType.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/DeviceInfoType.h) | [`code/wolfeye/models.py`](../code/wolfeye/models.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/DataProvider/include/DataProviderTypes.h`](../code/native/DataProvider/include/DataProviderTypes.h) | Reimplemented | DeviceInfo plus native device identity decoding; the old standalone declaration is not copied. |
| [`WolfEye/SCADA/include/dnp3/DNP3Test.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/SCADA/include/dnp3/DNP3Test.h) | — | Not ported | StartDNP3Master / opendnp3 sample has no DEVolf master implementation. The DNP3 settings editor configures the relay, not this sample. |
| [`WolfEye/SCADA/src/dnp3/DNP3Test.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/SCADA/src/dnp3/DNP3Test.cpp) | — | Not ported | StartDNP3Master / opendnp3 sample has no DEVolf master implementation. The DNP3 settings editor configures the relay, not this sample. |
| [`WolfEye/WolfEye.rc`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/WolfEye.rc) | [`code/assets/wolfeye.ico`](../code/assets/wolfeye.ico)<br>[`code/wolfeye/services/windows_shell.py`](../code/wolfeye/services/windows_shell.py)<br>[`build.ps1`](../build.ps1) | Replaced | Qt/Windows shell identity and PyInstaller icon replace the Win32 resource script. |
| [`WolfEye/WolfEye.vcxproj`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/WolfEye.vcxproj) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`WolfEye/WolfEye.vcxproj.filters`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/WolfEye.vcxproj.filters) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`WolfEye/imgs/fc.ico`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/imgs/fc.ico) | [`code/assets/company.png`](../code/assets/company.png) | Role replaced | Company branding is supplied as PNG; this ICO is not a byte-identical copy. |
| [`WolfEye/imgs/tw.ico`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/imgs/tw.ico) | [`code/assets/wolfeye.ico`](../code/assets/wolfeye.ico) | Role replaced | Application icon is supplied separately; this ICO is not a byte-identical copy. |
| [`WolfEye/imgs/tw.png`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/imgs/tw.png) | [`code/assets/wolfeye.png`](../code/assets/wolfeye.png) | Identical | SHA-256 byte comparison confirms the image is unchanged. |
| [`WolfEye/include/Base.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/Base.h) | [`code/wolfeye/qt.py`](../code/wolfeye/qt.py)<br>[`code/wolfeye/styles.py`](../code/wolfeye/styles.py)<br>[`code/wolfeye/widgets/config_pages.py`](../code/wolfeye/widgets/config_pages.py)<br>[`code/wolfeye/numeric_schema.py`](../code/wolfeye/numeric_schema.py) | Split / partial | ImGui field helpers become Qt bindings and shared numeric storage limits. Win32/ImGui macros are not copied. |
| [`WolfEye/include/EmWolf.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/EmWolf.h) | [`code/wolfeye/widgets/emwolf_page.py`](../code/wolfeye/widgets/emwolf_page.py)<br>[`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py)<br>[`code/wolfeye/services/emwolf_report.py`](../code/wolfeye/services/emwolf_report.py) | Split / reimplemented | EmWolf setup/scenario controls, project structures, EWS2 connection and DI transition reporting. PDF reporting is a DEVolf addition. |
| [`WolfEye/include/EventViewer.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/EventViewer.h) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/beacheye/bridge.cpp`](../code/native/beacheye/bridge.cpp) | Split / reimplemented | EventPage, request_events and decode_events handle event UI, retrieval and revision-aware native decoding. |
| [`WolfEye/include/FaultViewer.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/FaultViewer.h) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/beacheye/bridge.cpp`](../code/native/beacheye/bridge.cpp) | Split / partial | SignalPage, waveform/capture views, request_signal and decode_signal cover live captures. Legacy scatter-directory grouping and file assembly have no dedicated port; live captures and in-memory history are implemented. |
| [`WolfEye/include/IconsFontAwesome4.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/IconsFontAwesome4.h) | [`code/wolfeye/styles.py`](../code/wolfeye/styles.py)<br>[`code/assets/combo-arrow.svg`](../code/assets/combo-arrow.svg)<br>[`code/assets/spin-up.svg`](../code/assets/spin-up.svg)<br>[`code/assets/spin-down.svg`](../code/assets/spin-down.svg)<br>[`code/assets/checkbox-checked.svg`](../code/assets/checkbox-checked.svg)<br>[`code/assets/checkbox-unchecked.svg`](../code/assets/checkbox-unchecked.svg) | Replaced | Qt controls and SVG assets replace icon-font macros; Font Awesome glyph identities are not preserved. |
| [`WolfEye/include/LogViewer.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/LogViewer.h) | — | Not ported | Old offline .bin LogViewer with file loading/filtering has no dedicated counterpart. MainWindow messages are operational logs, not this file viewer. |
| [`WolfEye/include/MeasurementsView.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/MeasurementsView.h) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/models.py`](../code/wolfeye/models.py)<br>[`code/wolfeye/point_schema.py`](../code/wolfeye/point_schema.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py) | Split / reimplemented | MeasurementPage / StatusPage, MeasurementSnapshot, point catalogs and native measurement decoding. |
| [`WolfEye/include/MessageViewer.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/MessageViewer.h) | [`code/wolfeye/widgets/main_window.py`](../code/wolfeye/widgets/main_window.py)<br>[`code/wolfeye/widgets/emwolf_page.py`](../code/wolfeye/widgets/emwolf_page.py) | Merged / partial | Messages dock, MainWindow.log and EmWolf operation log replace message display. Original AddLog freeze behavior is not asserted equivalent. |
| [`WolfEye/include/Scatter.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/Scatter.h) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/beacheye/bridge.cpp`](../code/native/beacheye/bridge.cpp) | Split / partial | Capture-cycle timing and waveform metadata are handled in the Qt/native capture path. Not a literal port of old scatter-file constants or timezone offset. |
| [`WolfEye/include/SettingsView.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/SettingsView.h) | [`code/wolfeye/widgets/config_pages.py`](../code/wolfeye/widgets/config_pages.py)<br>[`code/wolfeye/config_schema.py`](../code/wolfeye/config_schema.py)<br>[`code/wolfeye/numeric_schema.py`](../code/wolfeye/numeric_schema.py)<br>[`code/wolfeye/widgets/numeric_editor.py`](../code/wolfeye/widgets/numeric_editor.py)<br>[`code/wolfeye/services/native_config.py`](../code/wolfeye/services/native_config.py)<br>[`code/wolfeye/widgets/native_settings.py`](../code/wolfeye/widgets/native_settings.py)<br>[`code/wolfeye/widgets/tcc_chart.py`](../code/wolfeye/widgets/tcc_chart.py)<br>[`code/wolfeye/widgets/main_window.py`](../code/wolfeye/widgets/main_window.py)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py) | Split / partial | GeneralPage / ProtectionPage, settings schema, numeric fields, native settings mapping, TCC and read/write/update actions. Company make_random_config has no production UI equivalent. |
| [`WolfEye/include/StreamReader.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/StreamReader.h) | [`code/native/beacheye/data_provider_adapter.cpp`](../code/native/beacheye/data_provider_adapter.cpp)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py)<br>[`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py) | Role replaced / partial | Native relay framing and EWS2 FrameDecoder replace old stream state helpers. Disabled ceSerial port enumeration is not exposed in DEVolf. |
| [`WolfEye/include/TCCCalculator.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/TCCCalculator.h) | [`code/wolfeye/widgets/tcc_chart.py`](../code/wolfeye/widgets/tcc_chart.py) | Reimplemented | calculate_trip_time_s implements IEC/ANSI/TD formulas; TccPlotWidget and TccChartDialog supply plotting/editing. |
| [`WolfEye/include/main.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/include/main.h) | [`code/main.py`](../code/main.py)<br>[`code/wolfeye/widgets/main_window.py`](../code/wolfeye/widgets/main_window.py)<br>[`code/wolfeye/qt.py`](../code/wolfeye/qt.py)<br>[`code/wolfeye/branding.py`](../code/wolfeye/branding.py)<br>[`code/wolfeye/services/windows_shell.py`](../code/wolfeye/services/windows_shell.py) | Split / replaced | QApplication / MainWindow, high-DPI setup and application identity replace ImGui/Direct3D initialization and Win32 rendering. |
| [`WolfEye/resource.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/resource.h) | [`code/wolfeye/services/windows_shell.py`](../code/wolfeye/services/windows_shell.py)<br>[`build.ps1`](../build.ps1) | Replaced | Win32 resource IDs are not carried into the Qt application. |
| [`WolfEye/src/Base.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/Base.cpp) | [`code/wolfeye/qt.py`](../code/wolfeye/qt.py)<br>[`code/wolfeye/widgets/config_pages.py`](../code/wolfeye/widgets/config_pages.py) | Replaced / partial | Qt owns widget identities; ImGui ID repository and random-number helper have no direct equivalent. |
| [`WolfEye/src/EmWolf.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/EmWolf.cpp) | [`code/wolfeye/widgets/emwolf_page.py`](../code/wolfeye/widgets/emwolf_page.py)<br>[`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py)<br>[`code/wolfeye/services/emwolf_report.py`](../code/wolfeye/services/emwolf_report.py) | Split / reimplemented | EmWolf setup/scenario controls, project structures, EWS2 connection and DI transition reporting. PDF reporting is a DEVolf addition. |
| [`WolfEye/src/EventViewer.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/EventViewer.cpp) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/beacheye/bridge.cpp`](../code/native/beacheye/bridge.cpp) | Split / reimplemented | EventPage, request_events and decode_events handle event UI, retrieval and revision-aware native decoding. |
| [`WolfEye/src/FaultViewer.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/FaultViewer.cpp) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/beacheye/bridge.cpp`](../code/native/beacheye/bridge.cpp) | Split / partial | SignalPage, waveform/capture views, request_signal and decode_signal cover live captures. Legacy scatter-directory grouping and file assembly have no dedicated port; live captures and in-memory history are implemented. |
| [`WolfEye/src/LogViewer.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/LogViewer.cpp) | — | Not ported | Old offline .bin LogViewer with file loading/filtering has no dedicated counterpart. MainWindow messages are operational logs, not this file viewer. |
| [`WolfEye/src/MeasurementsView.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/MeasurementsView.cpp) | [`code/wolfeye/widgets/pages.py`](../code/wolfeye/widgets/pages.py)<br>[`code/wolfeye/models.py`](../code/wolfeye/models.py)<br>[`code/wolfeye/point_schema.py`](../code/wolfeye/point_schema.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py) | Split / reimplemented | MeasurementPage / StatusPage, MeasurementSnapshot, point catalogs and native measurement decoding. |
| [`WolfEye/src/MessageViewer.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/MessageViewer.cpp) | [`code/wolfeye/widgets/main_window.py`](../code/wolfeye/widgets/main_window.py)<br>[`code/wolfeye/widgets/emwolf_page.py`](../code/wolfeye/widgets/emwolf_page.py) | Merged / partial | Messages dock, MainWindow.log and EmWolf operation log replace message display. Original AddLog freeze behavior is not asserted equivalent. |
| [`WolfEye/src/SettingsView.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/SettingsView.cpp) | [`code/wolfeye/widgets/config_pages.py`](../code/wolfeye/widgets/config_pages.py)<br>[`code/wolfeye/config_schema.py`](../code/wolfeye/config_schema.py)<br>[`code/wolfeye/numeric_schema.py`](../code/wolfeye/numeric_schema.py)<br>[`code/wolfeye/widgets/numeric_editor.py`](../code/wolfeye/widgets/numeric_editor.py)<br>[`code/wolfeye/services/native_config.py`](../code/wolfeye/services/native_config.py)<br>[`code/wolfeye/widgets/native_settings.py`](../code/wolfeye/widgets/native_settings.py)<br>[`code/wolfeye/widgets/tcc_chart.py`](../code/wolfeye/widgets/tcc_chart.py)<br>[`code/wolfeye/widgets/main_window.py`](../code/wolfeye/widgets/main_window.py)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py) | Split / partial | GeneralPage / ProtectionPage, settings schema, numeric fields, native settings mapping, TCC and read/write/update actions. Company make_random_config has no production UI equivalent. |
| [`WolfEye/src/StreamReader.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/StreamReader.cpp) | [`code/native/beacheye/data_provider_adapter.cpp`](../code/native/beacheye/data_provider_adapter.cpp)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py)<br>[`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py) | Role replaced / partial | Native relay framing and EWS2 FrameDecoder replace old stream state helpers. Disabled ceSerial port enumeration is not exposed in DEVolf. |
| [`WolfEye/src/TCCCalculator.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/TCCCalculator.cpp) | [`code/wolfeye/widgets/tcc_chart.py`](../code/wolfeye/widgets/tcc_chart.py) | Reimplemented | calculate_trip_time_s implements IEC/ANSI/TD formulas; TccPlotWidget and TccChartDialog supply plotting/editing. |
| [`WolfEye/src/main.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/src/main.cpp) | [`code/main.py`](../code/main.py)<br>[`code/wolfeye/widgets/main_window.py`](../code/wolfeye/widgets/main_window.py)<br>[`code/wolfeye/qt.py`](../code/wolfeye/qt.py)<br>[`code/wolfeye/branding.py`](../code/wolfeye/branding.py)<br>[`code/wolfeye/services/windows_shell.py`](../code/wolfeye/services/windows_shell.py) | Split / replaced | QApplication / MainWindow, high-DPI setup and application identity replace ImGui/Direct3D initialization and Win32 rendering. |

### DEVolf additions without a standalone master file

These files supply the new architecture or additional workflows; they are not
represented as unchanged company source files.

| DEVolf files | Purpose |
| --- | --- |
| [bridge.cpp](../code/native/beacheye/bridge.cpp), [bridge.h](../code/native/beacheye/bridge.h), [beacheye.py](../code/wolfeye/services/beacheye.py) | Stable C ABI and Python/native boundary for company data and settings. |
| [data_provider_adapter.cpp](../code/native/beacheye/data_provider_adapter.cpp), [data_provider_adapter.h](../code/native/beacheye/data_provider_adapter.h), [device_service.py](../code/wolfeye/services/device_service.py) | Active native transport/update adapter and Qt operation coordination. |
| [numeric_schema.py](../code/wolfeye/numeric_schema.py), [numeric_editor.py](../code/wolfeye/widgets/numeric_editor.py) | Shared storage bounds, scaling and preservation of unchanged numeric values. |
| [config_schema.py](../code/wolfeye/config_schema.py), [native_config.py](../code/wolfeye/services/native_config.py), [native_settings.py](../code/wolfeye/widgets/native_settings.py) | Normalized settings model, company JSON mapping and exact ABI tree editor. |
| [services/signal_analysis.py](../code/wolfeye/services/signal_analysis.py), [widgets/signal_analysis.py](../code/wolfeye/widgets/signal_analysis.py) | Signal analysis and its presentation; no standalone analysis module is tracked in master. |
| [fc22_tester_page.py](../code/wolfeye/widgets/fc22_tester_page.py), [fc22_session.py](../code/wolfeye/services/fc22_session.py), [fc22_form_pdf.py](../code/wolfeye/services/fc22_form_pdf.py), [windows_pdf_printer.py](../code/wolfeye/services/windows_pdf_printer.py) | FC22 inspection sessions, company form generation and printing. |
| [emwolf_report.py](../code/wolfeye/services/emwolf_report.py) | PDF reporting added to the EmWolf workflow. |
| [tests](../tests) | DEVolf regression coverage; not copied from a tracked master test suite. |

## DEVolf file responsibilities

Paths in the following index are relative to the repository root. This index
was moved from the main README so implementation details remain available
without overwhelming the setup/build guide.

### Application source files

#### Core package

| File | Responsibility |
| --- | --- |
| `code/main.py` | Configures Windows application identity, DPI behavior, Fusion style, assets, `QApplication`, and the main window. It also implements the packaged EXE smoke-test entry point. |
| `code/wolfeye/qt.py` | PySide6/Qt 6 import boundary and common UI helpers. |
| `code/wolfeye/styles.py` | Generates the shared application stylesheet and references the scalable SVG control assets. |
| `code/wolfeye/models.py` | Shared data records for device identity, measurement snapshots, and event records. |
| `code/wolfeye/config_schema.py` | Canonical UI configuration structure, defaults, choices, ranges, and protection-group defaults. |
| `code/wolfeye/numeric_schema.py` | Shared storage/wire ranges, units, precision and numeric validation for General/Protection fields. |
| `code/wolfeye/branding.py` | Product name, organization and Windows application identity constants. |
| `code/wolfeye/point_schema.py` | Canonical analog, binary, counter, and named device point catalogs used by decoding and the UI. |
| `code/wolfeye/__init__.py` | Marks `wolfeye` as the application package. |

#### UI widgets

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
| `code/wolfeye/widgets/numeric_editor.py` | Applies shared numeric limits to Qt controls and preserves the precision of unchanged loaded values. |
| `code/wolfeye/widgets/__init__.py` | Marks the widgets directory as a Python package. |

#### Services

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

### Native source files

| Path | Responsibility |
| --- | --- |
| `code/native/beacheye/CMakeLists.txt` | Defines the native DLL build, source selection, runtime linkage, and revision profile. |
| `code/native/beacheye/bridge.cpp`, `bridge.h` | Stable exported C ABI used by Python for decode, encode, settings, and provider operations. |
| `code/native/beacheye/data_provider_adapter.cpp`, `data_provider_adapter.h` | Adapts the company `DataProvider` callbacks and transport behavior to the exported bridge API. |
| `code/native/beacheye/compat/` | Minimal compatibility headers required by the native company sources. |
| `code/native/DataProvider/src/` | Retained provider, timer and scenario sources; only `crc.c` is compiled by the current bridge target. Active transport lives in `data_provider_adapter.cpp`. |
| `code/native/DataProvider/include/` | Public types and declarations for the provider, setup, scenario, logging, timing, and configuration. |
| `code/native/DataProvider/cJSON/` | Bundled C/C++ JSON parser and helper implementation used by native settings code. |

BeachEye source is present only in the authenticated external cache. Generated
`wolfeye_beacheye.dll` files are ignored build artifacts. When revision 50 is
selected, the build also produces `wolfeye_beacheye_51.dll` so measurement
decoding can switch to the exact revision-51 point profile after identification.

### Build and dependency files

| File | Responsibility |
| --- | --- |
| `build.ps1` | Builds the x64 release, checks Python and packaged EXE architecture, runs all tests, packages a one-file EXE, and smoke-tests the result. |
| `build-native.ps1` | Builds revision 50/51 DLLs with MSYS2 UCRT64 GCC/Ninja, not MSVC. |
| `resolve-beacheye-source.ps1` | Requires GitHub CLI authentication, verifies that BeachEye is private, resolves pinned commits, and maintains an external private cache. |
| `requirements.txt` | Pinned Python 3.11 x64 dependencies for the Windows release. |
| `beacheye-source.json` | Records only the private repository identifier, branch names, and immutable revision-50/51 commit IDs used by the resolver. |
| `.gitattributes` | Repository file and line-ending attributes. |
| `.gitignore` | Excludes generated environments, caches, build intermediates, and packaged outputs. |

### Tests

| File | Coverage |
| --- | --- |
| `tests/test_device_service.py` | Native/legacy connection selection, fallback, request routing, write status, and update operations. |
| `tests/test_native_bridge.py` | Native ABI, exact settings round trips, revision-specific measurement/event profiles, framing, and provider behavior. |
| `tests/test_emwolf_protocol.py` | CRC, frames, scenarios, projects, debouncing, connection shutdown, and command construction. |
| `tests/test_emwolf_report.py` | EmWolf run interpretation, digital-input transitions, reclose results, and generated PDFs. |
| `tests/test_fc22_tester.py` | Session persistence, form PDF values, tester workflow, and shared device identity. |
| `tests/test_protection_ui.py` | Protection menus, company limits/defaults, TCC behavior, settings preservation, and device-specific controls. |
| `tests/test_pages.py` | Status-page values and device-operation availability. |
| `tests/test_numeric_settings.py` | Numeric storage bounds, extended FC22AR/FC22S round trips, signed values, millisecond precision and TCC preservation. |
| `tests/test_responsive_ui.py` | Responsive I/O layout and focus-required mouse-wheel value changes. |

### Runtime and generated data

- `code/assets/` contains application branding, SVG control graphics, and the FC22 company form templates.
- `sessions/` contains persisted FC22 Tester sessions created by operators.
- `fc22ar_3shot_fault_scenarios_DI1_Open_DI2_Close/` and `fc22s_fault_scenarios_DI1_Close_DI2_Open/` contain the supplied device test scenarios.
- `build/` and `Dist/` are generated by the build scripts and are not application source directories.
