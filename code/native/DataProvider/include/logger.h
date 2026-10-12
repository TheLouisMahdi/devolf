#pragma once
#include <iostream>
#include <iomanip>


#define	LOG_SYSTEM 			((uint32_t)0x001)
#define	LOG_DEBUG  			((uint32_t)0x002)
#define LOG_TCP				((uint32_t)0x004)

#define LOG_LEVEL			(LOG_DEBUG | LOG_SYSTEM | LOG_TCP)

#define LOG(LogFilter, ...) do { \
    if ((LogFilter & LOG_LEVEL)) { \
        char msg[256]; \
        sprintf_s(msg, __VA_ARGS__); \
        const char* type = get_log_type(LogFilter); \
        std::cout << "[" << type << "]" \
                  << std::setw(static_cast<int>(10 - strlen(type))) \
                  << ' ' << msg << std::endl; \
    } \
} while (0)

static const char* get_log_type(uint32_t filter)
{
	switch (filter)
	{
	case LOG_SYSTEM: return "SYSTEM"; break;
	case LOG_DEBUG: return "DEBUG"; break;
	case LOG_TCP: return "TCP"; break;
	default: return "UNKNOWN"; break;
	}
}