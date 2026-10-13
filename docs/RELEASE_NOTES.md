# Release-ready branch

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
- Signal analysis, event handling, firmware/bootloader transfer, EmWolf test
  scenarios, FC22 tester sessions, and PDF reports.
- One 64-bit Windows package using Python 3.11, PySide6, and PyInstaller 6.
  The Python 3.8/MinGW legacy build mode has been removed.

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
