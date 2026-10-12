#pragma once

#include <cstddef>
#include <cstdint>

// Minimal source-compatible subset used by the supplied BeachEye files.
// edited to solve bridge problem poimu
namespace ser4cpp {
class rseq_t {
public:
    rseq_t(const uint8_t* data, size_t size) : data_(data), size_(size) {}
    const uint8_t* current() const { return data_; }
    size_t length() const { return size_; }
    void advance(size_t count) {
        if (count > size_) count = size_;
        data_ += count;
        size_ -= count;
    }

private:
    const uint8_t* data_;
    size_t size_;
};
}
