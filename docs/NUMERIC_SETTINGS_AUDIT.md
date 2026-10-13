# Numeric settings alignment

Reference: company WolfEye **master**, commit
`989f9fffe4b58bce5b98213de945625780addcda`, inspected on 2026-10-13.
The company source was inspected in an external private cache.

Master disables the `VALIDATE` macro in `WolfEye/include/Base.h`. Its numeric
editors therefore accept values outside the engineering intervals described by
`MenuItemAttr`. DEVolf now follows that behavior, retaining storage and packed
wire limits so values do not wrap during transmission.

[The CSV inventory](NUMERIC_SETTINGS_AUDIT.csv) lists every one of the 1,252 numeric configuration
paths in General and Protection, including all four groups, previous DEVolf
bounds, new bounds, decimal precision, storage width and scale. The central
implementation is `code/wolfeye/numeric_schema.py`; form editors, tables and
the TCC dialog share its definitions.

| Area | Result |
| --- | --- |
| Measurement, deadbands, coefficients, LSD | Full stored ranges; scaled voltage deadband and LSD preserve 0.001 precision. Voltage deadband is displayed in kV, consistent with its scale. |
| DNP3, IEC and transport ports | Full stored address/retry ranges; millisecond timers preserve three decimals. DNP3 hold time remains integer seconds stored as one byte. |
| Digital I/O, heater and functions | Stored ranges, full uint32 analog comparator, independent recognition/pulse timers, one-millisecond validation precision. |
| Synchronization | Packed nibble limits retained for the four voltage multipliers and synchronism slip frequency; byte limits and correct scales for other numbers. |
| OC, EF, SEF and NPS | Pickup currents and timers use full storage ranges; TD/inverse/highset/SEF visibility and enable rules remain company-specific. |
| Voltage, frequency, ABR and sectionalizing | Old voltage stages retain uint32 multipliers; added stages retain byte multipliers. ABR operation/trip counts retain nibble limits and sectionalizing retains its two-bit trip count. |
| Admittance | Signed int16 conductance/susceptance, including -327.68 through +327.67; negative values survive native JSON and serialization. |
| CLP, IR, harmonics, overload, live line and BC46 | Storage ranges and wire scales preserved across the editors and native conversion. |
| TCC and loaded values | Switching elements no longer restores small engineering caps. Unchanged float values retain their original precision when other fields are edited. |
| Security | Password retains the full uint32 field. |

The private dependency's numeric JSON exporter previously replaced values
outside engineering intervals with defaults and mutated the settings object
while reading it. `resolve-beacheye-source.ps1` applies a narrow, idempotent
numeric-export transformation **only to the authenticated external BeachEye
cache**. This is necessary to read and save the numbers accepted by company
master. Enum handling and the wire layout are retained. The bridge exports
admittance words with their actual signed values.

Limits are checked before writing normalized settings to the native object.
Non-finite numbers and storage overflow raise an error. The raw Native
Settings tree remains an advanced ABI editor; it is not a replacement for
the normalized field validation.

Company limitations retained:

- `C_MAX` is a desktop TCC setting and is absent from the company's serialized
  Settings lists. It is preserved in the desktop session, not added to device
  wire bytes.
- DNP3 Max Event Buffer is unused by the company ABI and has no serialized
  mapping. Its existing editor is disabled and explains this limitation.
- TCC plot axes retain positive lower bounds for valid logarithmic plotting.
- A device can reject an otherwise representable setting. Matching desktop
  master does not change device firmware or prove hardware acceptance.

Verification uses the existing Python 3.11 environment and separately compiled
revision-50/51 native DLLs in `build/numeric-verification`. It covers all bound
numeric controls, extended and boundary values through both FC22AR and FC22S
serialization, overflow rejection, signed quantities, millisecond precision,
unchanged floats and TCC element switching. No final application EXE is built.

Initial numeric-audit result on 2026-10-13, before the later read/write source
alignment: both native profiles compiled successfully; the complete
suite passed **96 tests** in 142.539 seconds. No physical device write was
performed.

Build the final application from this clone:

```powershell
Set-Location 'C:\Users\poimu\Desktop\devolf'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

Output: `Dist\DEVolf.exe`. The build resolves the private dependency, builds
the selected company native library, installs requirements, runs tests, packages and smoke
tests the application.
