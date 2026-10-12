#pragma once

#include "protection_types.h"
#include "def_utils.h"

#define SIGNAL_LENGTH                   1

enum class UpdateType : uint8_t {
    FIRMWARE, BOOTLOADER
};


typedef struct {
    int ip, in, i0, vp, vn, v0;
}teta_t;

typedef struct {
    uint16_t ip, in, i0, vp, vn, v0;
}phase_t;

typedef struct Signal {
    bool ready;
    //CyclePack pack[SIGNAL_LENGTH];
    //phase_t phase;
    //teta_t teta;
    float buffer[64 * 10];
};

typedef struct {
    uint8_t calib_status;
    struct {
        uint16_t antenna;
        uint8_t status, reg_status, ip[4];
    }modem;
    struct {
        uint8_t remote_ip[4], connected;
        uint16_t port;
    }scada;
}status_t;

ENUM_STR(DeviceStatus, DISCONNECTED, CONNECTING, CONNECTED)
ENUM_STR(DeviceType, SECIONALIZER, AUTO_RECLOSER)
typedef struct device_info {
    char ip[18];
    DeviceStatus status;
    char model[16], commit[8];
    DeviceType type;
    uint16_t port, build;
    uint8_t firmware, hardware, bootloader;
    bool is_info_loaded, is_setting_loaded;
}device_info_t;