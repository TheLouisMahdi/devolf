#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BE_API __declspec(dllexport)

typedef struct {
    uint32_t model, firmware, hardware, bootloader, build, flags;
    char commit[8];
} BEInfo;

typedef struct {
    uint32_t type, index, value;
} BEPoint;

typedef struct {
    uint32_t type, source_index, dnp_index, value;
    char name[64];
} BENamedPoint;

typedef struct {
    uint64_t time_ms;
    uint32_t type, index, value, reserved;
} BEEvent;

typedef struct {
    uint64_t time_ms;
    uint32_t type, source_index, value, reserved;
    char name[64];
} BENamedEvent;

BE_API uint32_t __cdecl be_abi_version(void);
BE_API int __cdecl be_info(const uint8_t*, size_t, BEInfo*);
BE_API int __cdecl be_measurements(const uint8_t*, size_t, BEPoint*, size_t);
BE_API int __cdecl be_measurements_named(const uint8_t*, size_t, uint32_t, uint32_t, BENamedPoint*, size_t);
BE_API int __cdecl be_events(const uint8_t*, size_t, BEEvent*, size_t);
BE_API int __cdecl be_events_named(const uint8_t*, size_t, uint32_t, uint32_t, BENamedEvent*, size_t);
BE_API int __cdecl be_signal(const uint8_t*, size_t, float*, size_t);
BE_API int __cdecl be_frame_build(uint8_t, const uint8_t*, size_t, uint8_t*, size_t);
BE_API int __cdecl be_frame_decode(const uint8_t*, size_t, uint8_t*, uint8_t*, size_t);
BE_API int __cdecl be_point_catalog_json(uint32_t, uint32_t, char*, size_t);
BE_API int __cdecl be_settings_default_json(uint32_t, char*, size_t);
BE_API int __cdecl be_settings_default_file(uint32_t, uint8_t*, size_t);
BE_API int __cdecl be_settings_payload_json(const uint8_t*, size_t, uint32_t, char*, size_t);
BE_API int __cdecl be_settings_encode_json(const char*, size_t, uint32_t, uint8_t*, size_t);
BE_API int __cdecl be_settings_decode_json(const uint8_t*, size_t, char*, size_t);
BE_API int __cdecl be_settings_file_from_payload(const uint8_t*, size_t, uint32_t, uint8_t*, size_t);
BE_API int __cdecl be_settings_patch_payload_json(
    const uint8_t*, size_t, const char*, size_t, uint32_t, uint8_t*, size_t
);
BE_API size_t __cdecl be_settings_legacy_size(void);
BE_API int __cdecl be_settings_legacy_payload_json(const uint8_t*, size_t, char*, size_t);
BE_API int __cdecl be_settings_legacy_patch_payload_json(
    const uint8_t*, size_t, const char*, size_t, uint8_t*, size_t
);

#ifdef __cplusplus
}
#endif
