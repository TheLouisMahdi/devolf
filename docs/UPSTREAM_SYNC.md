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
| `e9ffe71` | Revision-50 measurements | One native decoder in `beacheye.py` and `wolfeye_beacheye.dll`; INFO selects the company point map | Native bridge profile tests |
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

The bridge directly uses the pinned `ver_50_remaster` API. `C_MAX` remains
outside BeachEye's device `Settings` serialization lists exactly as upstream;
the bridge exposes it to the desktop TCC session without inventing incompatible
wire bytes.

## BeachEye read/write alignment (2026-10-13)

The dependency selected at this synchronization was company `ver_50_remaster` at
`222c24eb813b9798a5eab42a3fed501892f61f26`, verified against the branch head.
The earlier `110dd0c` pin above records the previous synchronization state.
The newest commit adds `GeneralElement.cmax`; it does not change the settings
serialization lists compared with that previous pin.

All device builds, including **FC22AR build 51**, use this same company's
Database, Settings and event implementation. The prior `ver_51_compatible`
DLL selection was removed: its 394-BI/121-AI response was 296 bytes, whereas
the selected branch's FC22AR build-51 mapping is 410 BI / 122 AI, 300 bytes.
Packed BI/AI values follow the enabled declaration list used by the company
Serializer, rather than sorting values by DNP presentation index. The distinct
old byte-per-binary format retains its existing legacy DNP-order mapping.

The native provider adds/removes the company sequence byte and validates frame
CRC. Settings reads preserve the received payload; writes serialize/patch
through the same Settings ABI and send that payload without the file trailer.
Write completion accepts company status `0x00` or `0x09`. Tests exercise this
INFO/read/measurement/write flow over a localhost relay simulator, including
the 300-byte response. Physical-device verification remains a separate step.

Prior validation on 2026-10-13: the selected native library compiled successfully;
all **99 tests** passed in 161.484 seconds, including the stale-DLL selection
regression, point ordering, AR51 native read/write simulation and unchanged
settings round trips. Build-script syntax and local documentation links were
also checked. The final application EXE was left for the user to build.

## Single-source compatibility and cleanup

FC22AR (auto recloser) and FC22S (sectionalizer), including build 50, build 51
and later builds, share the same pinned company Database, Settings, Event and
transport implementation. The build scripts no longer accept another
repository, branch or compile-time revision. Old one-argument `DisablePoints`
and event-deserialization API alternatives were removed from the bridge.

The company `DisablePoints(model, revision)` API accepts an 8-bit revision,
but device INFO reports a 16-bit build. The bridge now saturates the API
argument at 255 instead of wrapping. INFO still preserves the original build.
The pinned source distinguishes build 50 from builds greater than 50, so 256,
257, 306 and 65535 retain the same post-50 map as 51. This follows the current
company source; it does not predict unknown future firmware format changes.
Unexpected measurement layouts remain an explicit decode error.

Tests cover both models at builds **50, 51, 52, 100, 255, 256, 257, 306 and
65535**: INFO decoding, exact settings reads, packed BI/AI decoding in company
list order, edited settings writes, sequence bytes, CRC and completion statuses
`0x00`/`0x09`. Point-map checks additionally cover build 512. The transport is
tested with a localhost simulator; no physical relay was available for this run.

Fourteen unused DataProvider source/header copies were removed after checking
compiler dependencies. Only six required CRC, JSON and configuration files
remain; the native library rebuilt successfully after cleanup. Every removed
company file remains accounted for in the 60-entry mapping below. Historical
generated build folders/DLLs are ignored, never selected by the loader, and
not included in the release package.

Final validation for this cleanup on 2026-10-13: native compilation succeeded
and **101 tests passed in 137.742 seconds**. The six retained DataProvider
files match company master; all 60 mapping entries occur exactly once and all
198 local documentation links/anchors resolve. PowerShell build/resolver
scripts passed syntax checks. No final EXE was built.

## Event reception correction

Reported device failure: `decode fail invalid 5512 bytes` (2026-10-13).
The actual failed device bytes were not available, so their format cannot be
established from the reported length alone. The length matches an 8-byte
legacy ring header plus 344 16-byte slots; it also exceeds the old 5,120-byte
receive rejection threshold. Both cases now have regression coverage.

The receive parser accepts the full unsigned 16-bit wire length (up to 65,535
payload bytes), keeps CRC/sequence checks and handles fragmented TCP delivery.
Outgoing frames and update chunks keep the pinned company's 5 KiB limit.
This changes the desktop receive buffer policy, not the company's serializers.

Legacy rings now support binary, analog and 32-bit counter records, the exact
unwrapped full-buffer boundary, wrapped heads and empty buffers. Serialized
events continue to use company Event::Deserialize and source-index names for
both models and all tested builds. Zero-time slots are omitted exactly as in
company EventToString. Incomplete AI/CC records raise an error rather than
quietly dropping an event; the established short device-tail tolerance remains.
The decoder also accepts an explicit serialized/ring format hint for inspection
of ambiguous captures. Bridge ABI 7 prevents an old DLL from being called with
the changed event function signature.

Event downloads have one active transaction, two bounded retries for timeouts
or invalid responses/chunks, sequence validation, empty-chunk rejection and
the company 1 MiB file-size limit. Repeated chunks do not append duplicate
bytes. Success, failure and disconnect release busy state; a canceled response
does not populate the viewer. A completed invalid file is preserved and the
transaction ends, allowing the operator to request a new snapshot. The viewer
reapplies its filter after loading and displays milliseconds.

On decode failure the latest raw response and device/transfer metadata are
saved outside the repository as
`%LOCALAPPDATA%\DEVolf\diagnostics\events-response.bin` and
`events-response.json`. Save failures are reported without replacing the
original error. Unknown/corrupt layouts remain explicit failures; no record
format is fabricated to force a successful display.

Regression tests cover 5,512-byte rings with all event types and wrap states
for FC22AR/FC22S builds 50, 51, 52, 256 and 65535; serialized mixed events;
empty and truncated responses; TCP fragmentation; bad CRC; wrong native
sequence; native and legacy receive framing; timeout recovery; duplicate and
empty file chunks; retry exhaustion; exact diagnostic captures; cancellation;
and viewer filtering. A localhost simulator verifies transport. Physical-device
verification of the user's original response remains necessary.

Validation: the pinned native dependency compiled with bridge ABI 7; **112
tests passed in 131.920 seconds**. The final diagnostic-metadata changes also
passed the 17 DeviceService tests. All 60 company mapping rows and 200 local
documentation links/anchors were checked. No final application EXE was built.

### Captured firmware serialization correction

The subsequent real capture identifies **FC22AR build 51, firmware 100,
hardware/bootloader 2** with a **5,112-byte serialized response**, not the
earlier reported 5,512-byte ring hypothesis. It contains 634 binary records
and four Counter records whose transmitted values occupy two bytes; their
values are 8, 7, 3 and 2. Eleven zero-time binary records are unused, leaving
**627 visible events**. The original bytes remain outside tracked source.

Company history confirms the cause. At BeachEye commit
[`b83f083`](https://github.com/majidnow/BeachEye/blob/b83f083650fa373709b22ac4920fcab7f2814c83/include/Event.h),
Event::SerializeSize reports 10 bytes for every nonbinary event, while
Event::Serialize writes a 32-bit CC value (12 bytes). Advancing the output
pointer by 10 lets the next event overwrite the upper CC word. The current
[`950d122` implementation](https://github.com/majidnow/BeachEye/blob/950d122e65347bf4361da041d2cb0e5f543bb1a9/include/Event.h)
uses 12 bytes for CC. The captured device still exhibits the earlier wire
layout even though it reports build 51.

The bridge derives record sizes from the pinned Event::SerializeSize API and
validates the complete stream, including company header/type bits, before
decoding any records. It considers the current CC32 layout and the proven
deployed CC16 layout. Complete record boundaries take precedence over a partial
tail; consuming current zero padding as extra empty records does not override
a valid CC32 stream. Equal consumption prefers the current layout. No packet-size constant, model or build
selects this wire layout. Short CC values are zero-extended for the pinned
Event::Deserialize implementation; current 32-bit values are never truncated.
Explicit `serialized16`/`serialized32` hints are available when inspecting
ambiguous captures, alongside serialized auto-detection and ring inspection.
Source-index names still come from the same pinned company Database.

Event records now retain the actual transmitted value width. A short Counter
has a viewer tooltip identifying its 16-bit device value. Upper bits that old
firmware overwrote cannot be recovered; the application preserves the bits
actually received. Unknown/invalid streams remain explicit errors with saved
raw diagnostics. Binary protocol schema and CRC checks are still required;
fixed total-size assumptions have been removed from this event decoder.

Native bridge ABI **8** requires rebuilding old DLLs. The real capture was
replayed through both FC22AR/FC22S models, builds 0, 50, 51, 52, 256 and 65535,
and direct/native plus chunked/legacy DeviceService paths: every run produced
the same 627 timestamps/types/values, no decode errors and released busy state.
Public regression tests use synthetic equivalent records rather than the
private device capture, and additionally verify current 32-bit Counter values,
mixed BI/AI/CC records, invalid headers and strict format inspection.

Final validation: ABI 8 native compilation succeeded and **114 tests passed
in 125.087 seconds**, including the ambiguous-zero-padding regression. The
final DLL also decoded the real capture correctly in all 12 model/build
combinations. All 60 mapping entries and 200 local documentation links were
verified. The final EXE remains for the user to build.

## Connection verification (2026-10-14)

Native connection now starts TCP directly and obtains its model/firmware/build
from the company INFO response, without requiring an HTTP probe beforehand.
Legacy fallback retains its optional HTTP discovery and normalizes text-valued
firmware/hardware fields. Cancellation is checked after discovery and after
TCP start, preventing a stopped attempt from becoming a live connection.

The Windows adapter monitors both writable and exception fd sets during
nonblocking connect, checks SO_ERROR and returns IP, port, error category and
Winsock code. Python preserves the native message. No networking settings or
device configuration are changed by this correction.

A localhost relay simulator verifies actual DeviceService startup, AR51 INFO,
sequenced settings request and byte-exact settings delivery without HTTP.
Tests also cover cancellation and endpoint/error reporting. The device's
current IP/error was not supplied during this investigation, so actual network
reachability and the cause of the reported physical connection failure remain
unverified. No final EXE was built.

Validation: native compilation succeeded and **120 tests passed in 127.032
seconds**, including the full TCP INFO/settings service handshake and accurate
failed-connect error reporting. All 200 local documentation links resolved.

## Latest company source and update builds (2026-10-14)

The current pin is **18d5e1696730c1167cae854f83d77eb0c20d9ac5**, checked against
the company ver_50_remaster head. It includes d3b49da (SEF trip-time defaults
corrected to 10,000 ms) and 18d5e16 (ROCOF structure/menu attributes). UI SEF
defaults now match 10 seconds for both models. This update does not add ROCOF
to company Settings serialization or JSON lists, so no new device bytes or
ROCOF wire controls are invented by DEVolf.

`-UpdateBeachEye` is supported by build.ps1, build-native.ps1 and
resolve-beacheye-source.ps1. The resolver selects the branch head once, resolves
an exact private checkout and updates the manifest after compatibility checks.
Lookup/download/compatibility failures retain the previous pin. A later native
compile or test failure stops the build but leaves the selected SHA recorded
for investigation. Without the switch, the recorded SHA is reused. Repository
and branch stay restricted to majidnow/BeachEye ver_50_remaster.

See [the English build guide](../guidebuild.txt) for complete commands. Resolver
transaction tests use isolated synthetic caches and fake GitHub/Git commands,
without accessing real account credentials or private source.

Validation: the update-capable native build compiled the selected 18d5e16
checkout and **125 tests passed in 146.270 seconds**. All three PowerShell
scripts and all 12 build examples passed syntax checks; all 204 local
documentation links and the 60-entry company mapping were verified. The final
application EXE was not built.

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

The **six retained DataProvider files** match the exact upstream blobs after
CRLF/LF normalization. Fourteen unused source/header copies were removed.
`tw.png` also matches its destination byte-for-byte. The current CMake target
compiles `DataProvider/src/crc.c` and `DataProvider/cJSON/cJSON.c` and uses four
required headers. Active relay transport is implemented in the native adapter.

### Dependency boundary

Company master records BeachEye gitlink
`23283b73478b61b244aa344a159d2ad671689bf4`. DEVolf does **not** check out that
gitlink directly: [its dependency manifest](../beacheye-source.json) pins
`18d5e1696730c1167cae854f83d77eb0c20d9ac5` from `ver_50_remaster` for all
reported device builds. The authenticated
resolver downloads that revision outside the repository. Files inside that separate
submodule repository are not entries of the WolfEye master tree counted here.

The original Visual Studio project also references ImGui, ImPlot, Asio,
ImGuiFileDialog, fonts and other files absent from the tracked master tree.
They are not silently counted as ported repository files. Qt replaces the
desktop rendering/dialog stack; the bridge supplies its compatibility headers.

### Complete inventory

| Company master entry | DEVolf destination | Treatment | Responsibility / limit |
| --- | --- | --- | --- |
| [`.gitmodules`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/.gitmodules) | [`beacheye-source.json`](../beacheye-source.json)<br>[`resolve-beacheye-source.ps1`](../resolve-beacheye-source.ps1) | Replaced | Submodule access is replaced by authenticated external dependency resolution. |
| [`DataProvider/BeachEye`](https://github.com/majidnow/wolfeye/tree/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/BeachEye) | [`beacheye-source.json`](../beacheye-source.json)<br>[`resolve-beacheye-source.ps1`](../resolve-beacheye-source.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | External dependency | Master gitlink: 23283b73478b61b244aa344a159d2ad671689bf4. DEVolf pins the current ver_50_remaster source for all device builds; no in-tree source copy. |
| [`DataProvider/DataProvider.vcxproj`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/DataProvider.vcxproj) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`DataProvider/DataProvider.vcxproj.filters`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/DataProvider.vcxproj.filters) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`DataProvider/DataProvider.vcxproj.user`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/DataProvider.vcxproj.user) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Project/filter/local IDE settings have no runtime equivalent; CMake selects native translation units. |
| [`DataProvider/cJSON/cJSON.c`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON.c) | [`code/native/DataProvider/cJSON/cJSON.c`](../code/native/DataProvider/cJSON/cJSON.c) | Retained / identical | Compiled directly into the native bridge for private Settings JSON conversion. |
| [`DataProvider/cJSON/cJSON.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON.h) | [`code/native/DataProvider/cJSON/cJSON.h`](../code/native/DataProvider/cJSON/cJSON.h) | Retained / identical | Native JSON declarations used by bridge.cpp and private dependency sources. |
| [`DataProvider/cJSON/cJSON_Helper.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Helper.cpp) | — | Removed / unused | Uncompiled helper implementation removed; current Settings JSON uses the required helper header and cJSON parser. |
| [`DataProvider/cJSON/cJSON_Helper.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Helper.h) | [`code/native/DataProvider/cJSON/cJSON_Helper.h`](../code/native/DataProvider/cJSON/cJSON_Helper.h) | Retained / identical | Required helper declarations used by private Settings/cJSON implementation. |
| [`DataProvider/cJSON/cJSON_Utils.c`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Utils.c) | — | Removed / unused | Unused JSON utility implementation removed; no active application responsibility. |
| [`DataProvider/cJSON/cJSON_Utils.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/cJSON/cJSON_Utils.h) | — | Removed / unused | Unused JSON utility declarations removed; no active application responsibility. |
| [`DataProvider/include/ConfigureDef.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/ConfigureDef.h) | [`code/native/DataProvider/include/ConfigureDef.h`](../code/native/DataProvider/include/ConfigureDef.h) | Retained / identical | SCADA/configuration enums retained; definitions are available on the native include path. |
| [`DataProvider/include/DataProvider.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/DataProvider.h) | [`code/native/beacheye/data_provider_adapter.h`](../code/native/beacheye/data_provider_adapter.h)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py) | Removed / replaced | Unused provider declarations removed; active provider ABI and operation coordination live in the adapter and DeviceService. |
| [`DataProvider/include/DataProviderTypes.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/DataProviderTypes.h) | [`code/native/beacheye/bridge.h`](../code/native/beacheye/bridge.h)<br>[`code/wolfeye/models.py`](../code/wolfeye/models.py) | Removed / replaced | Unused reference types removed; exported ABI and Python records supply device/status data. |
| [`DataProvider/include/EmWolfScenario.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/EmWolfScenario.h) | [`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py) | Removed / replaced | Unused C++ scenario declarations removed; Python Scenario supplies active serialization and execution. |
| [`DataProvider/include/EmWolfSetup.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/EmWolfSetup.h) | [`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py) | Removed / replaced | Unused C++ setup declarations removed; Python Setup/Project supplies active models. |
| [`DataProvider/include/EmWolfUtils.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/EmWolfUtils.h) | [`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py) | Removed / replaced | Unused C++ helper definitions removed; Python protocol supplies validation and serialization. |
| [`DataProvider/include/TimeUnit.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/TimeUnit.h) | [`code/native/beacheye/data_provider_adapter.cpp`](../code/native/beacheye/data_provider_adapter.cpp) | Removed / replaced | Unused timer units removed; active adapter uses chrono/thread timing. |
| [`DataProvider/include/Timer.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/Timer.h) | [`code/native/beacheye/data_provider_adapter.cpp`](../code/native/beacheye/data_provider_adapter.cpp) | Removed / replaced | Unused timer declarations removed; active adapter uses chrono/thread timing. |
| [`DataProvider/include/crc.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/crc.h) | [`code/native/DataProvider/include/crc.h`](../code/native/DataProvider/include/crc.h) | Retained / identical | CRC declarations used by the compiled native CRC implementation. |
| [`DataProvider/include/logger.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/include/logger.h) | [`code/native/beacheye/compat/logger.h`](../code/native/beacheye/compat/logger.h) | Removed / replaced | Unused company logger copy removed; desktop compatibility header supplies the required logging API. |
| [`DataProvider/src/DataProvider.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/DataProvider.cpp) | [`code/native/beacheye/data_provider_adapter.cpp`](../code/native/beacheye/data_provider_adapter.cpp)<br>[`code/wolfeye/services/device_service.py`](../code/wolfeye/services/device_service.py) | Removed / replaced | Uncompiled provider copy removed; active transport/update state machine lives in the adapter and DeviceService. |
| [`DataProvider/src/EmWolfScenario.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/EmWolfScenario.cpp) | [`code/wolfeye/services/emwolf_protocol.py`](../code/wolfeye/services/emwolf_protocol.py) | Removed / replaced | Uncompiled scenario implementation removed; Python protocol supplies the active scenario workflow. |
| [`DataProvider/src/Timer.cpp`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/Timer.cpp) | [`code/native/beacheye/data_provider_adapter.cpp`](../code/native/beacheye/data_provider_adapter.cpp) | Removed / replaced | Uncompiled timer implementation removed; active adapter uses chrono/thread timing. |
| [`DataProvider/src/crc.c`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/DataProvider/src/crc.c) | [`code/native/DataProvider/src/crc.c`](../code/native/DataProvider/src/crc.c) | Retained / identical | Compiled directly into the native bridge; Python emwolf_protocol.py has the EWS2 CRC implementation. |
| [`WolfEye.sln`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye.sln) | [`build.ps1`](../build.ps1)<br>[`build-native.ps1`](../build-native.ps1)<br>[`code/native/beacheye/CMakeLists.txt`](../code/native/beacheye/CMakeLists.txt) | Replaced | Visual Studio solution replaced by Python packaging and GCC/Ninja native build. |
| [`WolfEye/DeviceInfoType.h`](https://github.com/majidnow/wolfeye/blob/989f9fffe4b58bce5b98213de945625780addcda/WolfEye/DeviceInfoType.h) | [`code/wolfeye/models.py`](../code/wolfeye/models.py)<br>[`code/wolfeye/services/beacheye.py`](../code/wolfeye/services/beacheye.py)<br>[`code/native/beacheye/bridge.h`](../code/native/beacheye/bridge.h) | Reimplemented | DeviceInfo plus native device identity decoding; the old standalone declaration is not copied. |
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
| `code/wolfeye/widgets/fc22_lot_editor.py` | Edits versioned acceptance lots using the same native company point names as Measurements, with model/build-specific source choices. |
| `code/wolfeye/widgets/fc22_instruction_dialog.py` | Displays a WI03 mode's setup and exact acceptance expressions; records native/manual measurements and individual results without issuing test-board commands. |
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
| `code/wolfeye/services/fc22_autofill.py` | Maps actual DeviceService snapshots to 22 numeric and 3 boolean checklist fields using the company point names. Records observed values independently from acceptance verdicts. |
| `code/wolfeye/services/fc22_instruction.py` | Validates WI03 JSON and evaluates units, model/setup conditions, inclusive tolerances and strict ranges. Ambiguous or unspecified limits remain NOT_TESTED. |
| `code/wolfeye/services/fc22_test_lot.py` | Validates acceptance rules against BeachEye's point catalog and evaluates ranges, tolerances, stability, conditions, transitions and deadlines. Local inspection logic; no separate relay protocol. |
| `code/wolfeye/services/fc22_input_adapters.py` | Receives explicit bench measurements with session/listener context and converts confirmed EmWolf trip results to checklist inputs. Does not command the relay. |
| `code/wolfeye/services/fc22_form_pdf.py` | Fills the FC22AR or FC22S company PDF template using recorded inspection data. |
| `code/wolfeye/services/windows_pdf_printer.py` | Rasterizes generated PDFs and sends them to the Windows default printer through GDI/Winspool. |
| `code/wolfeye/services/windows_shell.py` | Applies the Windows AppUserModelID and native window/taskbar icons and releases their handles safely. |
| `code/wolfeye/services/__init__.py` | Marks the services directory as a Python package. |

### Native source files

| Path | Responsibility |
| --- | --- |
| `code/native/beacheye/CMakeLists.txt` | Defines the single company native DLL build, required sources and runtime linkage. |
| `code/native/beacheye/bridge.cpp`, `bridge.h` | Stable exported C ABI used by Python for decode, encode, settings, and provider operations. |
| `code/native/beacheye/data_provider_adapter.cpp`, `data_provider_adapter.h` | Adapts the company `DataProvider` callbacks and transport behavior to the exported bridge API. |
| `code/native/beacheye/compat/` | Minimal compatibility headers required by the native company sources. |
| `code/native/DataProvider/src/crc.c` | Required company CRC implementation compiled into the bridge. |
| `code/native/DataProvider/include/` | Required `ConfigureDef.h` configuration enums and `crc.h` declarations. |
| `code/native/DataProvider/cJSON/` | Required `cJSON.c`, `cJSON.h` and `cJSON_Helper.h` for native settings JSON. |

BeachEye source is present only in the authenticated external cache. The
generated `wolfeye_beacheye.dll` is an ignored build artifact. Device INFO
builds select a point map inside the same company source, not another DLL.

### Build and dependency files

| File | Responsibility |
| --- | --- |
| `build.ps1` | Builds the x64 release, checks Python and packaged EXE architecture, runs all tests, packages a one-file EXE, and smoke-tests the result. |
| `build-native.ps1` | Builds the ver_50_remaster DLL with MSYS2 UCRT64 GCC/Ninja; optionally updates its pin with -UpdateBeachEye. |
| `resolve-beacheye-source.ps1` | Requires GitHub CLI authentication, verifies privacy, resolves a recorded or latest branch commit, and maintains an external private cache. |
| `guidebuild.txt` | English reference for full/native-only builds, company updates, runtimes, wheelhouses and private cache options. |
| `requirements.txt` | Pinned Python 3.11 x64 dependencies for the Windows release. |
| `beacheye-source.json` | Records the private repository identifier, selected branch and immutable commit ID used by the resolver. |
| `.gitattributes` | Repository file and line-ending attributes. |
| `.gitignore` | Excludes generated environments, caches, build intermediates, and packaged outputs. |

### Tests

| File | Coverage |
| --- | --- |
| `tests/test_device_service.py` | Native/legacy connection selection, fallback, request routing, write status, and update operations. |
| `tests/test_build_source.py` | Source-pin/update selection, single branch lookup and manifest preservation on failed resolution/compatibility checks. |
| `tests/test_native_bridge.py` | Native ABI, exact settings round trips, revision-specific measurement/event profiles, framing, and provider behavior. |
| `tests/test_emwolf_protocol.py` | CRC, frames, scenarios, projects, debouncing, connection shutdown, and command construction. |
| `tests/test_emwolf_report.py` | EmWolf run interpretation, digital-input transitions, reclose results, and generated PDFs. |
| `tests/test_fc22_tester.py` | Session persistence, form PDF values, tester workflow, and shared device identity. |
| `tests/test_fc22_autofill.py` | Lot-independent form filling, provenance, manual edits, unavailable values, identity/session resets, confirmed board feedback and shared EWS2 controls. |
| `tests/test_fc22_instruction.py` | WI03 source identity, board/model coverage, exact input/output values, strict boundaries, unit conversions, review gates, worksheet/session behavior and PDF warnings. |
| `tests/test_fc22_test_lot.py` | Rule validation, unavailable/invalid values, distinct stability samples, transitions and late replies. |
| `tests/test_fc22_input_adapters.py` | Authenticated bench framing, sequence/unit validation and confirmed EmWolf result mapping. |
| `tests/test_fc22_lot_integration.py` | Company snapshots for both models/build generations, Qt callback isolation, manual edits/PDF warnings, disconnects, freshness and timer-driven timeouts. |
| `tests/test_protection_ui.py` | Protection menus, company limits/defaults, TCC behavior, settings preservation, and device-specific controls. |
| `tests/test_pages.py` | Status-page values and device-operation availability. |
| `tests/test_numeric_settings.py` | Numeric storage bounds, extended FC22AR/FC22S round trips, signed values, millisecond precision and TCC preservation. |
| `tests/test_responsive_ui.py` | Responsive I/O layout and focus-required mouse-wheel value changes. |

### Runtime and generated data

- `code/assets/` contains application branding, SVG control graphics, and the FC22 company form templates.
- `code/test_lots/wi03.json` contains WI03 revision 00 procedure data, source SHA-256 and page references. It is bundled into the EXE as `test_lots/wi03.json`; the company Word source stays external.
- `sessions/` contains persisted FC22 Tester sessions created by operators.
- `fc22ar_3shot_fault_scenarios_DI1_Open_DI2_Close/` and `fc22s_fault_scenarios_DI1_Close_DI2_Open/` contain the supplied device test scenarios.
- `build/` and `Dist/` are generated by the build scripts and are not application source directories.
