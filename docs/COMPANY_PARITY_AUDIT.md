# Company process audit

## Current architecture - Python WolfEye / native BeachEye - 2026-10-21

User-directed scope: keep BeachEye's working DLL, remove the WolfEye core DLL.
Company `majidnow/wolfeye` master was verified through GitHub CLI at
`7e58f4af439c6fa9c9db51e4558936264401732a`.

- `wolfeye_beacheye.dll`, ABI 12, retains device transport, settings serializers,
  point maps, measurements and event decoding. Its source implementation
  was not changed for this migration.
- `services/wolfeye.py` directly reads SIGNAL float32 and ADC uint16 using
  `struct`, following `FaultViewer.cpp::load_signal()` with INFO-selected
  32/64-sample channel strides. Multiple ADC cycles remain intact; padded
  32-sample SIGNAL responses use only their valid prefix.
- TCC follows `TCCCalculator.cpp` and the actual `IEC_Def` / `ANSI_Def` field
  order in company headers, including float32 intermediate rounding, uint32
  milliseconds, Ta, Tmin and Tmax.
- `services/ar_rules.py` ports `SettingsView.cpp` stage transitions and
  disabled-button flags. No algorithm calls a WolfEye DLL.
- `Get signal` dispatches independently of pending settings-editor validation.
- CMake and packaging no longer build or include `wolfeye_core.dll`.
  BeachEye remains native and must match the Python/EXE architecture.
  32 samples per cycle is independent of the process's bitness.

Validation: 191 existing tests passed, plus four new regression tests.
Golden outputs cover 12,000 AR transitions and 6,000 TCC values from the
previous unchanged company C++ functions. Signal tests also exercise
fragmented TCP responses through BeachEye into both 32/64-sample Qt viewers.
Python 3.8 uses an equal-length zip compatibility helper for signal analysis
and socket.timeout handling for EmWolf; numerical and scenario rules remain unchanged.

The development WolfEye C++ checkout is now a reference for these Python
ports. Editing its algorithms does not change the active implementation.
`-UpdateWolfEye` refreshes native-support source provenance; a new algorithm
revision requires an explicit Python port and parity review.

Both x64/Qt6 and x86/Qt5 builds are supported. Qt 5 exec_() calls are adapted
centrally; large numeric values use explicit float conversion in double editors.
