# Release-ready branch

This branch contains the cleaned, release-oriented `DEVolf` product tree.
It is based on the `wolfeye` branch at commit `1718877`, but removes the
repository's nested legacy layouts and keeps one canonical application source.

## Product features

- Synced with company WolfEye `master` at `989f9ff` and pinned BeachEye
  `ver_50_remaster` at `110dd0c`; see `UPSTREAM_SYNC.md` for the commit map.
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
  stream API, while retaining the older revision-51 decoder profile.

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
- Revision-selected measurement/event decoding: revision 50 remains the main
  BeachEye source, while revision 51 uses its exact 394-BI/121-AI point profile.
- Signal analysis, event handling, firmware/bootloader transfer, EmWolf test
  scenarios, FC22 tester sessions, and PDF reports.
- One reproducible x86 Windows package for Windows 7 SP1 through Windows 11,
  including 32-bit systems and 64-bit systems through WOW64.

## Differences from `wolfeye`

| Area | `wolfeye` branch | This branch |
| --- | --- | --- |
| Repository layout | Multiple app copies, including a nested `wolfeye/` tree | One canonical product tree at repository root |
| Connection mode | Manual native/legacy selection | Native-first connection with one automatic legacy fallback |
| Protection UI | Older combined configuration presentation | Separate FC22AR/FC22S menus with synchronized shared fields |
| TCC workflow | Basic element editing | Dedicated editor and chart with company curve calculations |
| Legacy settings | Current 3,439-byte layout only | Current and deployed 3,243-byte layouts with preserved offsets |
| Settings write | Follow-up readback after status | Validates status directly and clears failed/pending writes safely |
| Build-51 measurements | Uses the main decoder profile | Loads the exact revision-51 decoder after device INFO |
| Release contents | Historical and duplicated project trees | Source, tests, docs, official scenarios, and build scripts only |

## Verification

Targeted native and service tests cover the 3,243-byte settings round trip,
write status handling, revision-50 compatibility, and the deployed revision-51
measurement profile. The official Windows executable is built with 32-bit
Python 3.8.10 and an i686 MinGW-w64 POSIX/MSVCRT toolchain:

```powershell
$universalToolchain = "C:\Toolchains\mingw32"
$universalPython = "C:\Python38-32\python.exe"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 `
  -UniversalToolchainRoot $universalToolchain `
  -PythonExecutable $universalPython
```

This produces `Dist\DEVolf.exe`. The build validates the x86 Python,
native DLL, and packaged EXE architectures, runs the complete test suite
against the packaged native DLL set, and performs a Qt startup smoke test.
