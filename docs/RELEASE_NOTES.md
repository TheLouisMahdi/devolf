# Release-ready branch

## DEVolf 0.2 — native WolfEye core and signal fixes (2026-10-21)

- Separate WolfEye company algorithms into `wolfeye_core.dll` (ABI 1), with
  BeachEye device/settings integration in `wolfeye_beacheye.dll` (ABI 12).
  Both libraries are bundled in the Windows x64 executable.
- Execute the original company TCC calculator, pure AR stage transitions and
  SIGNAL/ADC loader from pinned WolfEye master `7e58f4a`. BeachEye remains
  pinned to `bee19ba` on `ver_50_remaster`.
- Support INFO-selected 32/64 samples, including fixed 2560/3072-byte buffers
  from 32-sample devices. Keep all ADC cycles and use the correct time axis.
- Save separate raw SIGNAL/ADC diagnostics for hardware investigation.
- Preserve the Qt appearance, existing EmWolf/EWS2 source and user signal
  analysis, history, navigation and standalone viewers.
- Add `-WolfEyeSourceDirectory` for editable company-source development, with
  a separate build directory and unchanged release pins.
- Include the existing FC22AR scenario and documentation updates in this tree.
- Validation: 181 project tests and five additional wire-contract tests passed;
  the packaged executable passed startup and both embedded DLL hash checks.
  Physical relay validation and complete line-by-line parity with master are
  not claimed. The transport remains the existing native adapter.

The dated entries below describe earlier builds and their earlier ABI versions.

## Company 32/64 signal sampling (2026-10-20)

- Pin WolfEye master to `7e58f4af439c6fa9c9db51e4558936264401732a`.
  BeachEye remains at the already selected `bee19ba2851658f03601375aec458a21633055bb`.
- Read INFO flag `0x02` as the company's 32-sample mode; clear means 64.
  Decode SIGNAL/ADC using that stride, with 1600/3200 Sa/s for calibrated signals.
- Keep each capture's cycle size for history, plot timing, fault origin and
  analysis windows. Existing analysis calculations and nonoverlapping steps remain.
- Invoke the unchanged company ADC loader per cycle so multiple cycles are
  retained without the upstream compile-time stride or first-cycle overwrite.
- Bridge ABI **11** rejects older DLLs. Rebuild DLL and EXE together.
  Cover both models, flag transitions, all channels, malformed payloads, ADC
  cycles and mixed capture history in `tests/test_signal_sampling.py`.
  Hardware verification still requires a connected relay.
- Verification: all **174** root tests passed in **96.206 seconds**, plus all
  **5** existing `code/tests` signal tests. `build.ps1` rebuilt the x64 native
  DLL and `Dist/DEVolf.exe`; the packaged Qt startup smoke test passed.

## Company core process audit (2026-10-17)

- Preserve EmWolf, FC22 Tester and the user's analysis/report integrations.
- Pin pristine WolfEye master alongside pristine BeachEye; bridge ABI **10**.
- Execute original company TCC calculation, AR stage rules and raw ADC loader.
- Bind settings directly to Configure so JSON export cannot clamp or omit UI values.
- Display company DNP3 measurement indices and advance transport sequence only
  after a valid matching response; resend CRC failures with the same sequence.
- Document remaining adapter/UI differences in [the parity audit](COMPANY_PARITY_AUDIT.md).
  No new test methods were added.

## Unmodified company DLL and transport cleanup (2026-10-17)

- Removed Legacy TCP, Legacy HTTP, discovery and automatic fallback from both
  the application and the native provider. Relay requests always use BeachEye's
  sequenced protocol. Failed INFO handshakes are reported and closed.
- Removed all company-source rewrites from dependency resolution. A separate
  pristine checkout of `majidnow/BeachEye` `ver_50_remaster` is required and
  checked before and after compilation.
- Removed custom legacy settings, measurement, event and signal interpretations,
  extra settings JSON fields and byte-difference patching. Settings JSON and
  wire bytes now use the unmodified company implementation.
- Bridge ABI is **9**; rebuild the DLL and EXE together. Earlier entries below
  document superseded behavior. No new tests were added.

## Remove extra frame and measurement restrictions (2026-10-15)

- General frame creation and queued requests no longer reject data at the
  firmware file-chunk size. Both directions use the two-byte wire length,
  with the sequence byte included for native requests. File upload partitioning
  remains aligned with the company source.
- Complete Measurements blocks with different point counts use wire-index
  labels instead of failing a model/build profile check. Empty channels and
  repeated blocks retain all received values. Known profiles retain company names.
  Status cards remain unavailable when only indexed readings exist, rather than
  displaying an invented zero or OFF state for an unidentified point.
- Event reception retains the deployed 5112-byte CC16 correction, current CC32
  support, dynamic frame assembly, CRC and sequence checks. Truncated or corrupt
  data remains distinguishable from a valid larger response.
- Event file downloads use the reported file length without the former desktop
  1 MiB rejection, and chunk sequences wrap within their uint16 wire field.

## FC22 interface consolidation (2026-10-15)

- Four fixed workflow steps, grouped form inputs and a single editable test
  table replace the crowded results sidebar. Sources, verdicts and rule
  tooltips stay next to observations; the complete diagnostic view is optional.
- Setup retains the WI03 revision 00 procedure, existing DUT autofill and
  shared EmWolf board connection. Custom Test Lot JSON and equipment adapters
  remain available in expandable settings. Reports expose optional approval
  fields and enable Open/Print after a PDF exists.
- This release is built from the current `devolf` tree, retaining ABI 8 event
  decoding and full 16-bit receive lengths. The 5112-byte short-counter stream,
  fragmented 5512-byte socket response and frame sizes through 65535 bytes
  remain covered by the native regressions.

This branch contains the cleaned, release-oriented `DEVolf` product tree.
It is based on the `wolfeye` branch at commit `1718877`, but removes the
repository's nested legacy layouts and keeps one canonical application source.

## Product features

- Synced with company WolfEye `master` at `989f9ff` and pinned BeachEye
  `ver_50_remaster` at `222c24e`; see [the synchronization manifest](UPSTREAM_SYNC.md) for the commit map and previous pins.
- User-facing product identity and the default executable name are `DEVolf`;
  compatibility-facing WolfEye/BeachEye package, DLL, and schema names remain
  unchanged.
- BeachEye is now resolved exclusively from an authenticated private GitHub
  repository into an external cache. The bundled mirror, generated DLL, and
  source-diff patches are no longer tracked.
- Complete UV/OV stage and voltage auto-reclose settings added to the native
  mapping and FC22AR protection editor.
- Independent digital-output recognition time added beside pulse duration.
- Fast-trip TCC max-current mode/multiplier and min/max-bounded curve plotting.
- Binary, analog, and 32-bit counter event decoding using the current BeachEye
  stream API from the same selected `ver_50_remaster` dependency for every device build.

- Native BeachEye/DataProvider TCP transport with automatic one-time fallback
  to the legacy protocol when the native handshake fails.
- FC22AR and FC22S device-specific protection menus.
- Shared setting synchronization across device views.
- TCC element editor and curve chart using the company IEC/ANSI formulas.
- Settings read/write support for both the current 3,439-byte layout and the
  deployed pre-menu-split 3,243-byte revision-50 layout.
- Byte-exact settings round trips so unchanged payloads remain unchanged.
- Write completion based on the company's status response (`0x00` or `0x09`),
  without a second read that can race or report a false failure.
- Company-source measurement/event decoding: FC22AR build 51 uses the
  `ver_50_remaster` 410-BI/122-AI packed profile (300 bytes), with serializer
  declaration order and no automatic `ver_51_compatible` DLL switch.
- FC22AR and FC22S share the same company branch for builds 50, 51 and later.
  INFO retains its 16-bit build; the company's 8-bit revision argument saturates
  instead of wrapping at 256. Simulated read/write and measurement coverage
  includes builds 50, 51, 52, 100, 255, 256, 257, 306 and 65535 for both models.
  Future compatibility follows the current branch's `>50` map and wire format.
- Alternate source/revision build options and old branch API paths removed.
  Fourteen unused native source/header files removed; six required company
  CRC/JSON/configuration files remain. The 60-entry mapping records removals
  and the active implementations replacing them.
- Signal analysis, event handling, firmware/bootloader transfer, EmWolf test
  scenarios, FC22 tester sessions, and PDF reports.
- One 64-bit Windows package using Python 3.11, PySide6, and PyInstaller 6.
  The Python 3.8/MinGW legacy build mode has been removed.

## Event reception fix (2026-10-13)

- Reported `invalid 5512 bytes` failure covered with ring-decoder and socket
  regressions. Receive frames accept the full 16-bit length with CRC/sequence
  validation; outgoing frames at that stage retained the former 5 KiB policy
  (superseded by the frame restriction removal above).
- Ring counter events, full/wrapped boundaries and empty slots corrected.
  Truncated AI/CC records fail explicitly. Serialized events use the same
  pinned company implementation and point maps.
- Event downloads guard repeated clicks, retry interrupted requests/chunks
  twice, validate sequences/file sizes and release busy state on every exit.
  Invalid data and device metadata are saved under the local DEVolf diagnostics
  folder. Event filters reapply on reload and timestamps show milliseconds.
- Native bridge ABI is now 7; rebuild the DLL/application before running.
  Tests use synthetic responses; the original physical-device response has
  not yet been captured. See [event verification details](UPSTREAM_SYNC.md#event-reception-correction).

## Real-device Counter compatibility (2026-10-13)

- Actual AR51 capture (5,112 bytes) now decodes to 627 visible events, including
  all four Counters. Company history confirms the older serializer advanced
  by 10 bytes for a 12-byte Counter, leaving only its low 16 bits in the stream.
- Event wire sizes come from the pinned company API. The complete stream is
  validated before selecting CC16/CC32; packet size, INFO model and build do
  not choose its layout. Current 32-bit values stay intact and transmitted
  widths are retained. Short Counter values are identified in viewer tooltips.
- ABI 8 requires a native/application rebuild. The real capture passed both
  models and native/chunked service paths. Source selection remains the same
  pinned `ver_50_remaster`; no alternate dependency branch or DLL was added.

## Connection reliability (2026-10-14)

- Native TCP connects directly and obtains identity through company INFO;
  optional HTTP identity is only probed for the legacy fallback. Unavailable
  or malformed HTTP metadata no longer blocks the native handshake.
- Stopping during HTTP discovery or TCP establishment prevents a late
  successful connection from being published or used for requests.
- Windows nonblocking connect checks both writable and exception socket sets
  and reports the actual endpoint and Winsock error. The Python bridge retains
  that detail instead of replacing it with a generic failure message.
- Regression coverage includes a complete AR51 INFO/settings handshake over
  localhost TCP, cancellation, text-valued legacy identity and failed socket
  error reporting. Physical device reachability requires its actual IP/error;
  this software validation does not establish the current device's availability.

## Updating company source during builds (2026-10-14)

- Added -UpdateBeachEye to release builds, native-only builds and source
  resolution. It selects the latest ver_50_remaster commit once and records
  it after preparing the private checkout. Normal builds repeat the pin.
- Updated the company pin to 18d5e16. SEF defaults now match 10 seconds for
  both models. New upstream ROCOF struct attributes do not change serialized
  Settings or JSON lists, so no new wire settings are assumed.
- Added [guidebuild.txt](../guidebuild.txt) with English build commands and
  source-update, runtime, output-name, wheelhouse and toolchain/cache options.

## Differences from `wolfeye`

| Area | `wolfeye` branch | This branch |
| --- | --- | --- |
| Repository layout | Multiple app copies, including a nested `wolfeye/` tree | One canonical product tree at repository root |
| Connection mode | Manual native/legacy selection | Native-first connection with one automatic legacy fallback |
| Protection UI | Older combined configuration presentation | Separate FC22AR/FC22S menus with synchronized shared fields |
| TCC workflow | Basic element editing | Dedicated editor and chart with company curve calculations |
| Legacy settings | Current 3,439-byte layout only | Current and deployed 3,243-byte layouts with preserved offsets |
| Settings write | Follow-up readback after status | Validates status directly and clears failed/pending writes safely |
| Build-51 measurements | Company branch point maps | Uses the selected `ver_50_remaster` Database with the INFO build number |
| Release contents | Historical and duplicated project trees | Source, tests, docs, official scenarios, and build scripts only |

## Verification

Run `build.ps1` with Python 3.11 x64, CMake, MSYS2 UCRT64 GCC/Ninja,
and authenticated access to the private BeachEye repository. The
build executes the tests and performs a packaged EXE startup smoke test.
The old Windows x86/Windows 7 build and its toolchain parameters were removed.
The device-level protocol fallback and deployed settings compatibility remain.

The native build now uses GCC/Ninja explicitly because the pinned BeachEye
headers do not compile under MSVC. The GCC cache is separate from the previous
Visual Studio build directory.
