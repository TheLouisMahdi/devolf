#include "bridge.h"
#include "ls_config.h"
#include "MeasureType.h"
#include <cstring>
#include <mutex>
#include <vector>

namespace {
// The unmodified company load_signal() uses this DataProvider signal view.
struct { struct { bool is_adc; size_t size; uint8_t* buffer; } signal; } dp;
#include "company_signal_loader.inc"
std::mutex signal_mutex;
}

int __cdecl be_adc(const uint8_t* data, size_t size, float* out, size_t capacity) {
    constexpr size_t cycle_bytes = 10 * SIG_BUFF_SIZE * sizeof(uint16_t);
    if (!data || !out || !size || size % cycle_bytes || capacity < size / 2 || size / 2 > INT32_MAX)
        return -1;
    std::lock_guard<std::mutex> lock(signal_mutex);
    // A uint16 buffer guarantees the alignment required by the original loader.
    std::vector<uint16_t> aligned(size / 2);
    std::memcpy(aligned.data(), data, size);
    dp.signal = {true, size, reinterpret_cast<uint8_t*>(aligned.data())};
    // Clear between responses so no sample from a prior request is retained.
    sig = SignalsBuf{};
    load_signal();
    const std::vector<float>* channels[] = {&sig.ia, &sig.ib, &sig.ic, &sig.in,
        &sig.va, &sig.vb, &sig.vc, &sig.vr, &sig.vs, &sig.vt};
    size_t offset = 0;
    for (auto* channel : channels) {
        std::memcpy(out + offset, channel->data(), channel->size() * sizeof(float));
        offset += channel->size();
    }
    dp.signal.buffer = nullptr;
    return static_cast<int>(offset);
}
