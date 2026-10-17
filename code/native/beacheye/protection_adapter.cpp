#include "bridge.h"
#include "TCCCalculator.h"

#include <cmath>

namespace {
struct btn_stage_status_t { bool e1[4], e2[4], e3[4]; };
#include "company_stage_rules.inc"
#undef L
#undef R
#undef D
#undef A
}

int __cdecl be_ar_cycle(uint8_t* modes, uint8_t* disabled, uint32_t row, uint32_t stage, uint32_t sef) {
    if (!modes || !disabled || stage >= 4 || row >= (sef ? 1u : 3u)) return -1;
    Element elements[3]{};
    bool blocked[12]{};
    const size_t count = sef ? 4 : 12;
    for (size_t i = 0; i < count; ++i) {
        if (modes[i] > AR_MODE_LOCK) return -1;
        elements[i / 4].ar_mode[i % 4] = static_cast<AR_MODE>(modes[i]);
        blocked[i] = disabled[i] != 0;
    }
    if (sef) sef_change_stage_mode(elements, static_cast<uint8_t>(stage), blocked);
    else {
        btn_stage_status_t status{};
        for (int i = 0; i < 4; ++i) {
            status.e1[i] = blocked[i]; status.e2[i] = blocked[i + 4]; status.e3[i] = blocked[i + 8];
        }
        change_stage_mode(elements + row, static_cast<uint8_t>(stage), &status, static_cast<uint8_t>(row + 1));
        for (int i = 0; i < 4; ++i) {
            blocked[i] = status.e1[i]; blocked[i + 4] = status.e2[i]; blocked[i + 8] = status.e3[i];
        }
    }
    for (size_t i = 0; i < count; ++i) {
        modes[i] = elements[i / 4].ar_mode[i % 4];
        disabled[i] = blocked[i];
    }
    return 0;
}

// Only the ABI conversion lives here. The calculator itself is compiled from
// the pinned, pristine company WolfEye checkout.
int __cdecl be_tcc_trip_ms(
    uint32_t type, uint16_t pickup, float multiplier,
    uint32_t minimum, uint32_t maximum, uint32_t adder,
    uint32_t definite_time, uint16_t current, uint32_t* out
) {
    if (!out || type > IEC_LTI || !pickup || !std::isfinite(multiplier) || multiplier < 0)
        return -1;
    TCC curve{};
    curve.type = static_cast<TCC_TYPE>(type);
    curve.Ip = pickup;
    curve.TM = multiplier;
    curve.Tmin = minimum;
    curve.Tmax = maximum;
    curve.Ta = adder;
    curve.Tt = definite_time;
    // Avoid the upstream inverse curve's division by zero and undefined
    // floating-point to uint32 conversion outside its operating range.
    if (type != TD && current <= pickup) {
        *out = maximum;
        return 0;
    }
    TCCCalculator calculator;
    *out = calculator.GetTripTime(&curve, current);
    return 0;
}
