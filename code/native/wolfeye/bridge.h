#pragma once
#include <stddef.h>
#include <stdint.h>
extern "C" {
#define WE_API __declspec(dllexport)
WE_API uint32_t __cdecl we_abi_version();
WE_API int __cdecl we_ar_cycle(uint8_t*, uint8_t*, uint32_t, uint32_t, uint32_t);
WE_API int __cdecl we_tcc_trip_ms(uint32_t, uint16_t, float, uint32_t, uint32_t, uint32_t, uint32_t, uint16_t, uint32_t*);
WE_API int __cdecl we_signal(const uint8_t*, size_t, float*, size_t, uint32_t);
WE_API int __cdecl we_adc(const uint8_t*, size_t, float*, size_t, uint32_t);
}
