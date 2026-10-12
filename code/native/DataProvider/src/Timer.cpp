
#include "Timer.h"

namespace utils
{
    Timer::Timer()
    {
        Reset();
    }
	void Timer::Reset()
	{
		start = std::chrono::steady_clock::now();
	}
    uint64_t Timer::Interval(TimeUnit unit)
	{
		end = std::chrono::steady_clock::now();

        switch (unit)
        {
        case MINIUTE:
            return std::chrono::duration_cast<std::chrono::minutes>(end - start).count();
        break;
        case SECOND:
            return std::chrono::duration_cast<std::chrono::seconds>(end - start).count();
        break;
        case MILLI:
            return std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
        break;
        case MICRO:
            return std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
        break;
        }
	}
}
