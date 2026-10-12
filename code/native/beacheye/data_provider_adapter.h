#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BE_PROVIDER_API __declspec(dllexport)

typedef void (__cdecl *BEProviderCallback)(
    void* context,
    uint32_t event,
    uint32_t tag,
    uint32_t value,
    const uint8_t* data,
    size_t size
);

enum BEProviderEvent : uint32_t {
    BE_PROVIDER_CONNECTED = 1,
    BE_PROVIDER_DISCONNECTED = 2,
    BE_PROVIDER_RESPONSE = 3,
    BE_PROVIDER_TIMEOUT = 4,
    BE_PROVIDER_ERROR = 5,
    BE_PROVIDER_UPDATE_PROGRESS = 6,
    BE_PROVIDER_UPDATE_FINISHED = 7,
};

enum BEProviderUpdateKind : uint32_t {
    BE_PROVIDER_FIRMWARE = 1,
    BE_PROVIDER_BOOTLOADER = 2,
};

BE_PROVIDER_API void* __cdecl be_provider_create(BEProviderCallback callback, void* context);
BE_PROVIDER_API void __cdecl be_provider_destroy(void* provider);
BE_PROVIDER_API int __cdecl be_provider_start(
    void* provider, const char* ip, uint16_t port, uint32_t timeout_ms, uint32_t legacy_protocol
);
BE_PROVIDER_API void __cdecl be_provider_stop(void* provider);
BE_PROVIDER_API int __cdecl be_provider_request(
    void* provider,
    uint32_t tag,
    uint8_t frame_type,
    const uint8_t* payload,
    size_t payload_size
);
BE_PROVIDER_API int __cdecl be_provider_update_file(
    void* provider,
    uint32_t kind,
    const wchar_t* path,
    uint32_t device_hardware,
    uint32_t device_bootloader
);

#ifdef __cplusplus
}
#endif
