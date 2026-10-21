# Company process audit — 2026-10-17

## Current architecture — 2026-10-21

WolfEye master was checked again through authenticated GitHub CLI:
`7e58f4af439c6fa9c9db51e4558936264401732a`. The Qt appearance is retained.
Two native libraries now have separate responsibilities:

| Layer | Implementation |
| --- | --- |
| `wolfeye_beacheye.dll`, ABI 12 | Original BeachEye settings serializers, point maps, events, plus local framing, transport and settings-editor integration. |
| `wolfeye_core.dll`, ABI 1 | Original WolfEye `TCCCalculator.cpp`; exact pure AR functions from `SettingsView.cpp`; exact `SignalsBuf`/`load_signal()` from `FaultViewer.cpp`. |
| `services/wolfeye.py` | Single ctypes boundary for TCC, AR and SIGNAL/ADC; no copy of the company algorithms in Python. |
| Existing Qt widgets and analysis | Display, capture history, cycle navigation, linked zoom/pan, standalone viewer, moving analysis, phasors, harmonics, sequences and protection analysis. |

The two former native protection/signal adapter files were consolidated into
`code/native/wolfeye/bridge.cpp` and its header. SIGNAL now calls the original
company loader too. ADC still invokes that loader once per cycle to retain
all received cycles. The fixed-buffer 32-sample correction remains in place.
Public Python import aliases in `beacheye.py` preserve existing integrations;
the application widgets call the dedicated WolfEye boundary directly.

The company's ImGui rendering and full ASIO DataProvider are not compiled
into this DLL. The active Windows transport remains the existing local
adapter. This is a deliberate Qt/native boundary, not a claim that the entire
company desktop or every source line has been ported unchanged. The older
file inventory identifies replaced/unported workflows. Review of that
inventory must not be presented as a complete manual line-by-line code audit.

### Editable source bodies

A separate development checkout has been prepared at
`%LOCALAPPDATA%\DEVolf\Development\WolfEye`, on `codex/devolf-core`, starting
from the master SHA above. Its complete tracked source layout is available
for editing, including `WolfEye/src/TCCCalculator.cpp`, `SettingsView.cpp`
and `FaultViewer.cpp`. Private source remains outside this repository.
The pristine release cache remains separate.

Build the application with those edits:

```powershell
.\build.ps1 -WolfEyeSourceDirectory "$env:LOCALAPPDATA\DEVolf\Development\WolfEye"
```

Native-only build:

```powershell
.\build-native.ps1 -WolfEyeSourceDirectory "$env:LOCALAPPDATA\DEVolf\Development\WolfEye"
```

Omit that argument for a release from the recorded pristine pins. Development
builds use a separate CMake build directory and allow edited WolfEye sources;
they do not rewrite either source manifest. Editing either source slice also
triggers CMake regeneration. A development build was verified by temporarily
changing the company TD return value by 7 ms: its DLL returned 1007 instead
of 1000. The source was then restored exactly; the final application uses
the pristine release build, not that verification DLL.

EmWolf/EWS2 source files and both signal-analysis modules were verified by
SHA-256 against the start of this refactor. They were unchanged. Existing
viewer sampling/history and real native-TCP simulation tests pass through
the new DLL. No physical relay read/write is implied by these tests.

Release verification: **181 tests passed in 99.701 seconds**, plus all five
additional wire-contract tests. `Dist/DEVolf-new.exe` passed packaged startup
(the existing `DEVolf.exe` was in use, so the build used its normal alternate name).
Both DLLs inside its archive matched the SHA-256 hashes of the tested release
DLLs. The existing saved 2560-byte hardware SIGNAL also decoded exactly with
the company 32-sample channel offsets. Build log:
`build-wolfeye-core-release.log`; hashes and details:
`Dist/DEVolf-new-build-info.json`.

The dated audit below describes earlier builds; its ABI numbers, paths and
verification counts are historical.

> The [2026-10-21 SIGNAL/ADC audit](SIGNAL_ADC_PARITY_2026-10-21.md)
> records the confirmed fixed-size 32-sample SIGNAL regression and correction,
> plus ADC timing, diagnostics and current hardware verification limits.

> Sampling update (2026-10-20): the active pins are WolfEye master
> `7e58f4af439c6fa9c9db51e4558936264401732a` and BeachEye ver_50_remaster
> `bee19ba2851658f03601375aec458a21633055bb`; bridge ABI is **11**.
> INFO bit `0x02` selects 32 instead of 64 samples. SIGNAL/ADC channel stride,
> signal timing and capture analysis follow that profile. The unchanged ADC
> loader is called once per cycle, superseding the multi-cycle limitation below.
> The remaining audit and its verification figures describe the October 17 build.

The reference is company [WolfEye master at 989f9ff](https://github.com/majidnow/wolfeye/tree/989f9fffe4b58bce5b98213de945625780addcda), inspected through an authenticated, clean external checkout. BeachEye is [ver_50_remaster at 18d5e16](https://github.com/majidnow/BeachEye/tree/18d5e1696730c1167cae854f83d77eb0c20d9ac5). Full commits are pinned in `wolfeye-source.json` and `beacheye-source.json`. This audit supersedes older blanket parity claims in the historical synchronization notes.

## Protected user additions

EmWolf, EWS2/SSH board integration, FC22 Tester, test lots, checklist/report generation, automatic tester readings, signal analysis and capture history remain user features. Their algorithms, protocols and data files were not replaced with the company's older equivalents. Shared relay service fixes continue to feed the existing tester integration. No test method was added.

## Verified integration and corrections

| Company process | DEVolf implementation and result |
| --- | --- |
| Device connection | Sequenced TCP on port 6536, INFO followed by GET_SETTINGS, 15-second native response deadline. Sequence starts at 1, advances after a valid matching response, and wraps 255 to 1. CRC errors requeue the active request with its existing sequence. Legacy TCP/HTTP and fallback are removed. |
| Settings on the device | The original BeachEye `Settings::Default`, `PrepareLists`, `Deserialize` and `Serialize` run inside the DLL. Current payloads are 3439 bytes for AR and 877 for S. Reading a snapshot and writing it back without editing preserved the complete payload for both profiles. |
| Settings editor | Company desktop `SettingsView.cpp` edits `Configure` directly and disables engineering-range validation in `Base.h`. DEVolf now assigns typed `Configure` members through `settings_editor.cpp`, then calls the original serializer. Internal UI JSON is only marshalling; it never invokes the company's mutating JSON exporter. This restores all 16 functions, signed admittance, full stored timer/current values, sectionalizer mode and fast-trip `max_mode`. The original company JSON functions remain compiled unchanged and separately callable. |
| TCC calculation | The actual company `WolfEye/src/TCCCalculator.cpp` is compiled unchanged. Curve type ordering, float32 constants, integer-millisecond conversion, Ta addition and Tmin/Tmax follow that source. Python only converts UI units and calls the DLL. Non-TD currents at or below pickup are guarded before calling the upstream singular expression. |
| AR stage changes | The exact pure transition functions from `SettingsView.cpp` are included from the private checkout at build time. Stage buttons call those functions, including changes to related delayed/fast/highset stages and disabled buttons. The private source is neither rewritten nor copied into tracked project files. |
| Measurements | Original BI/AI/CC deserializers and `DisablePoints` select wire values and names for the model/build. Presentation now uses the original DNP3 indices and ordering. Snapshot dictionaries retain their existing keys/values for the user's tester. |
| Live signal | Original ten-channel float signal layout, 64 samples per channel, with current/voltage channel ordering preserved. |
| Raw ADC | GET_ADC frame 0x11 is available. The exact company `SignalsBuf`/`load_signal()` source is included from `FaultViewer.cpp`. Raw counts are shown in a dedicated waveform window without changing the user's calibrated signal analysis or capture history. |
| Events | Original variable-length `Event::Deserialize` and `SerializeSize`, original model point names, zero-time omission and 12600000-ms device offset. See retained presentation differences below. |
| Firmware and bootloader | Existing native workflow uses bootloader support check, DFHB-VER hardware validation, CRC16, existing-file check, FIRST/LAST upload chunks of `MAX_DATA_SIZE - 4`, uploaded-file verification, update signal and disconnection after RESETTING. Desktop progress converts to percent. This is an adapter implementation of the company workflow, not the company's complete DataProvider compiled verbatim. |
| Setup save | Original serialized payload + model flag (AR=1, S=0) + CRC16. Loader validates length, model and CRC before deserializing. The company GUI's inconsistent raw-Configure loader is described below. |

The 60 tracked company entries are indexed in [the file mapping](UPSTREAM_SYNC.md#file-by-file-mapping). CRC and cJSON support files match the company source after newline normalization. Local compatibility headers and Windows/C ABI code remain integration code outside the company checkouts. Bridge ABI is 10.

## Limits on a claim of literal identity

The application remains Python/Qt with a C ABI and Windows socket adapter; it is not a byte-for-byte copy of the company's ImGui/ASIO application. The following differences are explicit, rather than hidden behind a claim of complete identity:

- The current event service retains its existing bounded retries and diagnostics. The decoder retains all valid received records, full 32-bit counters and ON/OFF binary display. Company `Events::AddToList` is a 1000-entry ring and its text formatter reads a 16-bit value. User data handling was not silently reduced to that display limit.
- Complete measurement blocks whose counts do not match the known company profile retain explicit wire-index labels. They are not assigned guessed company point names.
- Settings writes reject unexpected failure statuses; company GUI reports most non-0x09 responses as applied. The transport adapter also queues requests, whereas the original UI has one command slot.
- Company `LoadSetting`/GUI file-open reads a raw `Configure`, while GUI file-save writes a serialized payload plus flag and CRC. DEVolf loads the validated save format. It does not read arbitrary compiler-layout memory dumps.
- The original ADC loader overwrites the first 64 output positions for every input cycle. Because the unchanged function is used, this upstream multi-cycle behavior remains; a single cycle is mapped correctly. The wrapper clears stale samples between requests.
- The company admittance GUI has inert AR buttons and binds its trip/reset time controls to `min_Vn_mult` rather than Tt/Tr. The existing DEVolf controls retain their intended Configure bindings; the company source was not patched to repair these UI errors.
- Some desktop-only Configure members, including C_MAX, are omitted from company serialization. Their values can be edited for the current desktop session but cannot be added to the device payload or persisted in the company's packed setup format.
- The company exposes unfinished or inert controls: the Log tab is commented out, the DNP3 master example is uncalled, scatter-file startup returns immediately, and some protection controls are placeholders. File presence is not evidence of an active company workflow. Those paths were not invented in DEVolf.
- Engineering ranges are disabled in the company GUI, but DEVolf still prevents integer overflow and packed-width overflow. Input at the inverse-curve singularity is guarded. These integration boundaries are explicit.

Physical relay reads/writes and firmware updates were not executed. Local build verification cannot establish hardware equivalence. The user additions above are intentionally outside company parity.

## Verification

All **166 existing tests passed in 88.285 seconds** during `build.ps1`. The x64 DLL and `Dist/DEVolf.exe` were built successfully; the existing offscreen startup check passed. No new test methods were introduced. The final build result and executable hash are recorded alongside the built executable in Dist.
