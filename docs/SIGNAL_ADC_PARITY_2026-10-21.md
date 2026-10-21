# SIGNAL / ADC audit — 2026-10-21

## Structure and reference

The application entry is `code/main.py`. Qt widgets in `code/wolfeye/widgets`
use `DeviceService`; `services/beacheye.py` marshals the C ABI implemented in
`code/native/beacheye`. The native transport strips the sequence byte before
the service decodes a response. External, pristine WolfEye/BeachEye checkouts
supply company settings, point maps, signal loader and TCC code. EmWolf uses
its own EWS2 service; FC22 Tester consumes the existing device state.
Build scripts resolve the source pins, compile the DLL, run tests and package
the application. The 60-entry upstream inventory is in `UPSTREAM_SYNC.md`.

Authenticated GitHub CLI verified WolfEye master at
`7e58f4af439c6fa9c9db51e4558936264401732a` on this date. This is the configured
pin and the inspected pristine checkout. Relevant company sources:

- `DataProvider/src/DataProvider.cpp`: `InfoDeserialize`, SIGNAL/ADC response
  handling and sequence removal.
- `WolfEye/src/FaultViewer.cpp`: `SignalsBuf`, `load_signal()`.
- BeachEye `include/MeasureType.h`: sampling constants and Signals fields.

BeachEye remains pinned to `bee19ba2851658f03601375aec458a21633055bb`.
Its current branch head was also inspected: `0b5b4cce5755a5dba3db1b27413434fb0b6d6c7e`.
The only subsequent change fixes the JSON Admittance export start member
(`forward_susceptance` to `min_In`). It changes neither sampling nor the wire
serializer. DEVolf's active settings editor assigns Configure members directly;
the separately exposed company JSON API still follows the pinned source.
Neither dependency pin was changed by this audit.

## Confirmed SIGNAL regression

The existing local diagnostic (2026-10-20 06:14:15 UTC, FC22AR build 51,
firmware 200, hardware 2) has INFO flags 3 and a 2560-byte SIGNAL body.
Flag `0x02` means **32 samples per channel**, not 32-bit ADC resolution.
SIGNAL values are float32 in both profiles; ADC words are unsigned uint16.

The previous decoder required 1280 or 1536 bytes for the 32-sample profile,
so it rejected this complete response. Selecting 64 samples from its length
would also be incorrect: it combines successive channels and plots unused
tail bytes. The company's loader selects its stride from INFO and reads
only the first 10 * 32 floats, irrespective of additional response bytes.

Both ABI and Python validation now accept 2560/3072-byte fixed buffers for
32-sample devices in addition to compact 1280/1536-byte buffers. Exactly ten
channels are extracted with the INFO-selected stride. Only displayed samples
are checked for finite values; unused tails are ignored. The 64-sample profile
still requires a complete 2560/3072-byte body. Arbitrary/partial lengths remain
errors. No sample filtering, gain correction or guessed channel remapping is
applied.

## ADC and timing

The existing adapter already uses the unchanged company ADC loader separately
for each cycle, preserving every cycle instead of upstream's overwritten first
cycle. Its wire order is: each half-cycle contains interleaved six voltage
channels followed by interleaved four current channels. Native tests exercise
both sampling profiles, multiple cycles and full unsigned counts.

Python now validates complete ADC cycles and the returned native count.
The ADC viewer receives the INFO-selected rate (1600/3200 samples/s), so its
horizontal axis shows milliseconds. ADC values remain raw counts. Exact ADC
responses and INFO metadata are now saved independently to
`%LOCALAPPDATA%/DEVolf/diagnostics/adc-response.bin` and `.json`, including on
decode failure. SIGNAL retains its own diagnostic files.

The saved SIGNAL diagnostic was decoded successfully with the rebuilt DLL;
every displayed value matched the scalar offsets in company `load_signal()`.
The diagnostic was read only during this audit. No saved ADC
response was available and no physical relay was contacted, so the cause of
the reported hardware ADC failure cannot yet be established. A fixed-size
ADC response must not be truncated based solely on the SIGNAL behavior:
multiple ADC cycles are valid. Reproduce with the rebuilt executable to
capture the actual ADC body if the problem persists.

## Validation

Regression coverage in `tests/test_signal_sampling.py` includes compact and
padded SIGNAL bodies, non-finite unused tails, INFO-driven service delivery,
malformed payloads, ADC channel order, unsigned counts, native output capacity,
multiple cycles and viewer timing/history. Full release validation is recorded
in `build-signal-parity.log`; the build script runs the complete project suite,
packages the DLL with the application and checks packaged Qt startup.

The full build suite passed 178 tests in 99.768 seconds. A subsequent focused
run passed all 13 sampling tests, including a new integration test: actual
button clicks send SIGNAL/ADC through the native TCP transport to a local
fake relay; fragmented, sequenced replies populate both viewers for 32- and
64-sample profiles. That test verifies the ADC window becomes visible and
contains the expected counts. The physical ADC failure remains unconfirmed.
All five additional wire-contract tests in `code/tests` also passed.
`Dist/DEVolf.exe` was rebuilt successfully with the corrected native DLL and
passed the packaged startup smoke test; its hash and verification metadata
are in `Dist/DEVolf.exe.sha256` and `Dist/DEVolf-build-info.json`.
