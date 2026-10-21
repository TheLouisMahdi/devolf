#include "bridge.h"
#include "TCCCalculator.h"
#include "ls_config.h"
#include "MeasureType.h"
#include <cmath>
#include <climits>
#include <cstring>
#include <mutex>
#include <vector>

uint32_t __cdecl we_abi_version() { return 1; }

namespace {
struct btn_stage_status_t { bool e1[4], e2[4], e3[4]; };
#include "company_stage_rules.inc"
#undef L
#undef R
#undef D
#undef A
}

int __cdecl we_ar_cycle(uint8_t* modes, uint8_t* disabled, uint32_t row, uint32_t stage, uint32_t sef) {
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
int __cdecl we_tcc_trip_ms(
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

namespace {
// The unmodified company load_signal() uses this DataProvider signal view.
struct {
    struct { bool is_adc; size_t size; uint8_t* buffer; } signal;
    struct { bool is_32_sampling; } dev;
} dp;
#include "company_signal_loader.inc"
std::mutex signal_mutex;
void copy_channels(float* out, size_t stride, size_t offset, size_t samples) {
    const std::vector<float>* channels[] = {&sig.ia, &sig.ib, &sig.ic, &sig.in,
        &sig.va, &sig.vb, &sig.vc, &sig.vr, &sig.vs, &sig.vt};
    for (size_t channel = 0; channel < 10; ++channel)
        std::memcpy(out + channel * stride + offset, channels[channel]->data(), samples * sizeof(float));
}

}

int __cdecl we_adc(const uint8_t* data, size_t size, float* out, size_t capacity, uint32_t samples) {
    if (samples != 32 && samples != 64) return -1;
    const size_t cycle_bytes = 10 * samples * sizeof(uint16_t);
    if (!data || !out || !size || size % cycle_bytes || capacity < size / 2 || size / 2 > INT32_MAX)
        return -1;
    std::lock_guard<std::mutex> lock(signal_mutex);
    // A uint16 buffer guarantees the alignment required by the original loader.
    std::vector<uint16_t> aligned(size / 2);
    std::memcpy(aligned.data(), data, size);
    dp.dev.is_32_sampling = samples == 32;
    const size_t cycles = size / cycle_bytes;
    const size_t channel_samples = cycles * samples;
    // Feed one cycle at a time to the unchanged company loader. Its multi-cycle
    // loop overwrites the first cycle and uses a compile-time 64-sample stride.
    for (size_t cycle = 0; cycle < cycles; ++cycle) {
        dp.signal = {true, cycle_bytes, reinterpret_cast<uint8_t*>(aligned.data() + cycle * 10 * samples)};
        sig = SignalsBuf{};
        load_signal();
        copy_channels(out, channel_samples, cycle * samples, samples);
    }
    dp.signal.buffer = nullptr;
    return static_cast<int>(size / 2);
}

int __cdecl we_signal(const uint8_t* data, size_t size, float* out, size_t capacity, uint32_t samples) {
    if (samples != 32 && samples != 64) return -1;
    const size_t bytes = 10 * samples * sizeof(float);
    // INFO selects channel stride, independent of the desktop compile-time macros.
    // The company loader consumes the prefix even when 32-sample firmware sends
    // a fixed 64-sample-sized response. Never interpret that tail as plot data.
    const bool valid_size = size == bytes || size == 12 * samples * sizeof(float)
        || (samples == 32 && (size == 10 * 64 * sizeof(float) || size == 12 * 64 * sizeof(float)));
    if (!data || !out || !valid_size || capacity < 10 * samples) return -1;
    std::lock_guard<std::mutex> lock(signal_mutex);
    std::vector<float> aligned(10 * samples);
    std::memcpy(aligned.data(), data, bytes);
    dp.dev.is_32_sampling = samples == 32;
    dp.signal = {false, bytes, reinterpret_cast<uint8_t*>(aligned.data())};
    sig = SignalsBuf{};
    load_signal();
    copy_channels(out, samples, 0, samples);
    dp.signal.buffer = nullptr;
    return static_cast<int>(10 * samples);
}
