#pragma once

#include <stdint.h>
#include <chrono>

#include "TimeUnit.h"

namespace utils
{
class Timer
{
public:
    Timer();
	void Reset();
    uint64_t Interval(TimeUnit unit=TimeUnit::MICRO);
private:
    std::chrono::steady_clock::time_point start, end;
};
}
