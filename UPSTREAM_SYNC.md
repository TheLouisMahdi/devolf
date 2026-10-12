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

## Reproduction

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
