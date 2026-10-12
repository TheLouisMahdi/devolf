#pragma once

#include <cstdint>

#include <ser4cpp/container/SequenceTypes.h>
#include <ser4cpp/container/WSeq.h>

// Minimal source-compatible little-endian serializers used by BeachEye.
// edited to solve bridge problem poimu
namespace ser4cpp {
template <typename T, unsigned Bytes>
struct LittleEndian {
    static void write_to(wseq_t& output, T value) {
        if (output.length() < Bytes) return;
        for (unsigned i = 0; i < Bytes; ++i)
            output.current()[i] = static_cast<uint8_t>(value >> (i * 8));
        output.advance(Bytes);
    }

    static void read_from(rseq_t& input, T& value) {
        if (input.length() < Bytes) return;
        value = 0;
        for (unsigned i = 0; i < Bytes; ++i)
            value |= static_cast<T>(input.current()[i]) << (i * 8);
        input.advance(Bytes);
    }
};

using UInt8 = LittleEndian<uint8_t, 1>;
using UInt16 = LittleEndian<uint16_t, 2>;
using UInt32 = LittleEndian<uint32_t, 4>;

class UInt48Type {
public:
    UInt48Type(uint64_t value = 0) : value_(value & 0x0000FFFFFFFFFFFFULL) {}
    uint64_t Get() const { return value_; }
    void Set(uint64_t value) { value_ = value & 0x0000FFFFFFFFFFFFULL; }

private:
    uint64_t value_;
};

struct UInt48 {
    static void write_to(wseq_t& output, const UInt48Type& value) {
        if (output.length() < 6) return;
        const uint64_t raw = value.Get();
        for (unsigned i = 0; i < 6; ++i)
            output.current()[i] = static_cast<uint8_t>(raw >> (i * 8));
        output.advance(6);
    }

    static void read_from(rseq_t& input, UInt48Type& value) {
        if (input.length() < 6) return;
        uint64_t raw = 0;
        for (unsigned i = 0; i < 6; ++i)
            raw |= static_cast<uint64_t>(input.current()[i]) << (i * 8);
        value.Set(raw);
        input.advance(6);
    }
};
}
