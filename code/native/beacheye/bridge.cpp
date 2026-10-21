#include "bridge.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <limits>
#include <mutex>
#include <string>
#include <vector>

#include "Event.h"
#include "MeasureType.h"
#include "cJSON.h"
#include "cJSON_Imp.h"
#include "crc.h"
#include "ls_config.h"
#include "settings_editor.h"

static_assert(sizeof(BEInfo) == 32 && sizeof(BEPoint) == 12 && sizeof(BEEvent) == 24);
static_assert(sizeof(BENamedPoint) == 80 && sizeof(BENamedEvent) == 88);
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
static_assert(ADC_64_SAMPLING == 1 && ADC_SAMPLING_SIZE == 64);
static_assert(SIG_BUFF_SIZE == 64 && offsetof(Signals, Vbat) == 10 * 64 * 4);
static_assert(sizeof(Signals) == 12 * 64 * sizeof(float));

namespace {
constexpr uint8_t START_CAT = 0x41;
constexpr uint8_t START_DOG = 0x24;

uint32_t little(const uint8_t* p, size_t count) {
    uint32_t value = 0;
    for (size_t i = 0; i < count; ++i) value |= uint32_t(p[i]) << (8 * i);
    return value;
}

void put_little(uint8_t* p, uint32_t value, size_t count) {
    for (size_t i = 0; i < count; ++i) p[i] = static_cast<uint8_t>(value >> (8 * i));
}

uint16_t frame_crc(const uint8_t* data, size_t size) {
    static std::once_flag initialized;
    std::call_once(initialized, crcInit);
    return crcFast(data, static_cast<int>(size));
}

template <typename T>
void copy_name(T& target, const char* name) {
    std::memset(target.name, 0, sizeof(target.name));
    if (name) std::strncpy(target.name, name, sizeof(target.name) - 1);
}

struct Block {
    uint32_t type;
    uint32_t count;
    const uint8_t* values;
};

int parse_blocks(const uint8_t* data, size_t size, std::vector<Block>& blocks) {
    if (!data) return -1;
    size_t offset = 0;
    while (offset < size) {
        if (size - offset < 2) return -1;
        const uint32_t header = little(data + offset, 2);
        offset += 2;
        const uint32_t type = header & 15;
        const uint32_t count = header >> 4;
        if (type != M_TYPE_BI && type != M_TYPE_AI && type != M_TYPE_BC) return -1;
        const size_t bytes = type == M_TYPE_BI ? (count + 7) / 8 : count * (type == M_TYPE_AI ? 2 : 4);
        if (bytes > size - offset) return -1;
        blocks.push_back({type, count, data + offset});
        offset += bytes;
    }
    return 0;
}

template <typename T>
std::vector<typename T::value_type*> enabled_in_wire_order(T& points) {
    std::vector<typename T::value_type*> result;
    for (auto& point : points) if (point.IsEnabled()) result.push_back(&point);
    // Database Serialize/Deserialize walks the enabled declaration list.
    // DataProvider sorts DNP indices only for presentation after decoding.
    return result;
}

uint8_t company_revision(uint32_t build) {
    return static_cast<uint8_t>(build ? build : 50);
}

template <typename T>
void disable_points(T& points, bool recloser, uint8_t revision) {
    points.DisablePoints(recloser, revision);
}

int append_native_binaries(
    const Block& block, bool recloser, uint32_t build,
    BENamedPoint* out, size_t capacity, size_t& used
) {
    BIs points;
    for (auto& point : points.list) point.Enable();
    disable_points(points, recloser, company_revision(build));
    auto sorted = enabled_in_wire_order(points.list);
    if (block.count != sorted.size() || block.count > capacity - used) return -1;
    points.Deserialize(block.values);
    for (size_t wire = 0; wire < sorted.size(); ++wire) {
        auto* point = sorted[wire];
        auto& target = out[used++];
        target = {
            M_TYPE_BI,
            point->id,
            point->dnp3.index,
            static_cast<uint32_t>(point->Value()),
            {},
        };
        copy_name(target, point->Name());
    }
    return 0;
}

int append_native_analogs(
    const Block& block, bool recloser, uint32_t build,
    BENamedPoint* out, size_t capacity, size_t& used
) {
    auto settings = std::make_shared<Settings>();
    AIs points(settings);
    for (auto& point : points.list) point.Enable();
    disable_points(points, recloser, company_revision(build));
    auto sorted = enabled_in_wire_order(points.list);
    if (block.count != sorted.size() || block.count > capacity - used) return -1;
    points.Deserialize(block.values);
    for (size_t wire = 0; wire < sorted.size(); ++wire) {
        auto* point = sorted[wire];
        auto& target = out[used++];
        target = {
            M_TYPE_AI, point->id, point->dnp3.index,
            static_cast<uint32_t>(point->Value()), {}
        };
        copy_name(target, point->Name());
    }
    return 0;
}

int decode_company_event_stream(
    const uint8_t* data, size_t size, BEEvent* out, size_t capacity
) {
    if (!data || !out) return -1;
    size_t offset = 0, used = 0;
    while (offset < size) {
        if (size - offset < 8 || used >= capacity || used >= INT32_MAX) return -1;
        const auto header = little(data + offset, 2);
        const auto type = (header >> 12) & 3;
        if (type > 2) return -1;
        BeachWolf::Event schema(0, 0, static_cast<BeachWolf::EventLogType>(type), 0);
        const size_t record_size = schema.SerializeSize();
        if (record_size > size - offset) return -1;
        BeachWolf::Event event;
        ser4cpp::rseq_t sequence(data + offset, record_size);
        event.Deserialize(sequence);
        out[used++] = {event.Time(), static_cast<uint32_t>(event.Type()),
                      event.Position(), *event.Ptr(), type == 0 ? 1u : type == 1 ? 16u : 32u};
        offset += record_size;
    }
    return static_cast<int>(used);
}

const char* event_name(uint32_t type, uint32_t index, uint32_t model, uint32_t build) {
    static thread_local BIs binaries;
    static thread_local auto settings = std::make_shared<Settings>();
    static thread_local AIs analogs(settings);
    static thread_local CCs counters;
    for (auto& point : binaries.list) point.Enable();
    for (auto& point : analogs.list) point.Enable();
    for (auto& point : counters.list) point.Enable();
    disable_points(binaries, model != 2, company_revision(build));
    disable_points(analogs, model != 2, company_revision(build));
    disable_points(counters, model != 2, company_revision(build));
    if (type == 0 && index < binaries.list.size()) return binaries.list[index].Name();
    if (type == 1 && index < analogs.list.size()) return analogs.list[index].Name();
    if (type == 2 && index < counters.list.size()) return counters.list[index].Name();
    return nullptr;
}

std::shared_ptr<Settings> new_settings(bool recloser) {
    auto settings = std::make_shared<Settings>();
    settings->Default(recloser);
    settings->PrepareLists(&settings->config, recloser);
    return settings;
}

void add_number(cJSON* object, const char* name, double value) {
    cJSON_AddItemToObject(object, name, cJSON_CreateNumber(value));
}

int copy_settings_json(const std::shared_ptr<Settings>& settings, char* out, size_t capacity) {
    if (!out || !capacity) return -1;
    char* json = setting_to_json(&settings->config);
    if (!json) return -1;
    const size_t length = std::strlen(json);
    if (length + 1 > capacity || length > INT32_MAX) {
        cJSON_free(json);
        return -1;
    }
    std::memcpy(out, json, length + 1);
    cJSON_free(json);
    return static_cast<int>(length);
}
}

uint32_t __cdecl be_abi_version(void) { return 12; }

int __cdecl be_info(const uint8_t* data, size_t size, BEInfo* out) {
    if (!data || !out || size < 16) return -1;
    *out = {data[0], data[1], data[2], data[3], little(data + 4, 2), little(data + 6, 2), {}};
    std::memcpy(out->commit, data + 8, 8);
    return 0;
}

int __cdecl be_measurements(const uint8_t* data, size_t size, BEPoint* out, size_t capacity) {
    if (!data || !out) return -1;
    std::vector<Block> blocks;
    if (parse_blocks(data, size, blocks) < 0) return -1;
    size_t used = 0;
    uint32_t binary_offset = 0, analog_offset = 0, counter_offset = 0;
    for (const auto& block : blocks) {
        if (block.count > capacity - used || used + block.count > INT32_MAX) return -1;
        auto& channel_offset = block.type == M_TYPE_BI ? binary_offset
            : block.type == M_TYPE_AI ? analog_offset : counter_offset;
        for (uint32_t i = 0; i < block.count; ++i) {
            const uint32_t value = block.type == M_TYPE_BI
                ? ((block.values[i / 8] >> (i % 8)) & 1u)
                : little(block.values + i * (block.type == M_TYPE_AI ? 2 : 4), block.type == M_TYPE_AI ? 2 : 4);
            out[used++] = {block.type, channel_offset + i, value};
        }
        channel_offset += block.count;
    }
    return static_cast<int>(used);
}

int __cdecl be_measurements_named(
    const uint8_t* data, size_t size, uint32_t model, uint32_t build,
    BENamedPoint* out, size_t capacity
) {
    if (!data || !out) return -1;
    std::vector<Block> blocks;
    if (parse_blocks(data, size, blocks) < 0) return -1;
    size_t used = 0;
    uint32_t named_types = 0;
    for (const auto& block : blocks) {
        if (!block.count) continue;
        // A repeated channel is a valid wire stream, but one model point map
        // cannot name both blocks. Let the indexed decoder retain every value.
        if (named_types & block.type) return -1;
        named_types |= block.type;
        if (block.type == M_TYPE_BC) {
            CCs points;
            for (auto& point : points.list) point.Enable();
            disable_points(points, model != 2, company_revision(build));
            auto enabled = enabled_in_wire_order(points.list);
            if (block.count != enabled.size() || block.count > capacity - used) return -1;
            points.Deserialize(const_cast<uint8_t*>(block.values));
            for (auto* point : enabled) {
                auto& target = out[used++];
                target = {M_TYPE_BC, point->id, point->dnp3.index, point->Value(), {}};
                copy_name(target, point->Name());
            }
            continue;
        }

        const bool recloser = model != 2;
        const int result = block.type == M_TYPE_BI
            ? append_native_binaries(block, recloser, build, out, capacity, used)
            : append_native_analogs(block, recloser, build, out, capacity, used);
        if (result < 0) return -1;
    }
    return used <= INT32_MAX ? static_cast<int>(used) : -1;
}

int __cdecl be_events(const uint8_t* data, size_t size, BEEvent* out, size_t capacity) {
    return decode_company_event_stream(data, size, out, capacity);
}

int __cdecl be_events_named(
    const uint8_t* data, size_t size, uint32_t model, uint32_t build,
    BENamedEvent* out, size_t capacity
) {
    if (!data || !out) return -1;
    std::vector<BEEvent> decoded(std::max<size_t>(1, size / 8));
    const int count = decode_company_event_stream(data, size, decoded.data(), decoded.size());
    if (count < 0 || static_cast<size_t>(count) > capacity) return -1;
    for (int i = 0; i < count; ++i) {
        const auto& source = decoded[i];
        auto& target = out[i];
        target = {source.time_ms, source.type, source.index, source.value, source.reserved, {}};
        const char* name = event_name(source.type, source.index, model, build);
        if (name) copy_name(target, name);
        else {
            char fallback[32]{};
            const char* prefix = source.type == 0 ? "BI" : source.type == 1 ? "AI" : "CC";
            std::snprintf(fallback, sizeof(fallback), "%s %u", prefix, source.index);
            copy_name(target, fallback);
        }
    }
    return count;
}

int __cdecl be_frame_build(
    uint8_t type, const uint8_t* payload, size_t payload_size,
    uint8_t* out, size_t capacity
) {
    if (!out || (payload_size && !payload) || payload_size > BE_FRAME_MAX_PAYLOAD || capacity < payload_size + 7) return -1;
    out[0] = START_CAT;
    out[1] = START_DOG;
    put_little(out + 2, static_cast<uint32_t>(payload_size), 2);
    out[4] = type;
    if (payload_size) std::memcpy(out + 5, payload, payload_size);
    put_little(out + 5 + payload_size, frame_crc(out + 2, payload_size + 3), 2);
    return static_cast<int>(payload_size + 7);
}

int __cdecl be_frame_decode(
    const uint8_t* frame, size_t size, uint8_t* type,
    uint8_t* payload, size_t capacity
) {
    if (!frame || !type || size < 7 || frame[0] != START_CAT || frame[1] != START_DOG) return -1;
    const size_t payload_size = little(frame + 2, 2);
    // Frame length comes from the wire, independently of the file chunk size.
    if (size != payload_size + 7 || payload_size > capacity || (payload_size && !payload)) return -1;
    if (frame_crc(frame + 2, payload_size + 3) != little(frame + 5 + payload_size, 2)) return -2;
    *type = frame[4];
    if (payload_size) std::memcpy(payload, frame + 5, payload_size);
    return static_cast<int>(payload_size);
}

int __cdecl be_point_catalog_json(
    uint32_t model, uint32_t build, char* out, size_t capacity
) {
    if (!out || !capacity) return -1;
    const bool recloser = model != 2;
    BIs binaries;
    auto settings = new_settings(recloser);
    AIs analogs(settings);
    for (auto& point : binaries.list) point.Enable();
    for (auto& point : analogs.list) point.Enable();
    disable_points(binaries, recloser, company_revision(build));
    disable_points(analogs, recloser, company_revision(build));

    cJSON* root = cJSON_CreateObject();
    cJSON* binary = cJSON_CreateArray();
    cJSON* analog = cJSON_CreateArray();
    if (!root || !binary || !analog) {
        cJSON_Delete(root);
        cJSON_Delete(binary);
        cJSON_Delete(analog);
        return -1;
    }
    cJSON_AddItemToObject(root, "binary", binary);
    cJSON_AddItemToObject(root, "analog", analog);
    auto append = [](cJSON* array, auto& points) {
        for (auto& point : points) {
            if (!point.IsEnabled()) continue;
            cJSON* item = cJSON_CreateObject();
            add_number(item, "id", point.id + 1);
            cJSON_AddStringToObject(item, "name", point.Name());
            cJSON_AddItemToArray(array, item);
        }
    };
    append(binary, binaries.list);
    append(analog, analogs.list);
    char* json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) return -1;
    const size_t length = std::strlen(json);
    if (length + 1 > capacity || length > INT32_MAX) {
        cJSON_free(json);
        return -1;
    }
    std::memcpy(out, json, length + 1);
    cJSON_free(json);
    return static_cast<int>(length);
}

int __cdecl be_settings_default_json(uint32_t model, char* out, size_t capacity) {
    return copy_settings_json(new_settings(model != 2), out, capacity);
}

int __cdecl be_settings_default_file(uint32_t model, uint8_t* out, size_t capacity) {
    if (!out) return -1;
    auto settings = new_settings(model != 2);
    const size_t payload_size = settings->SerializeSize();
    if (payload_size + 3 > capacity || payload_size + 3 > INT32_MAX) return -1;
    settings->Serialize(out);
    out[payload_size] = model == 2 ? 0 : 1;
    put_little(out + payload_size + 1, frame_crc(out, payload_size + 1), 2);
    return static_cast<int>(payload_size + 3);
}

int __cdecl be_settings_payload_json(
    const uint8_t* data, size_t size, uint32_t model, char* out, size_t capacity
) {
    if (!data) return -1;
    const bool recloser = model != 2;
    auto settings = new_settings(recloser);
    if (settings->SerializeSize() != size) return -1;
    settings->Deserialize(const_cast<uint8_t*>(data));
    return copy_settings_json(settings, out, capacity);
}

int __cdecl be_settings_encode_json(
    const char* json, size_t json_size, uint32_t model, uint8_t* out, size_t capacity
) {
    if (!json || !out || !json_size) return -1;
    std::string source(json, json_size);
    cJSON* parsed = cJSON_Parse(source.c_str());
    if (!parsed) return -1;
    auto settings = new_settings(model != 2);
    if (!json_to_setting(source.c_str(), settings)) {
        cJSON_Delete(parsed);
        return -1;
    }
    cJSON_Delete(parsed);
    settings->PrepareLists(&settings->config, model != 2);
    const size_t payload_size = settings->SerializeSize();
    if (payload_size + 3 > capacity || payload_size + 3 > INT32_MAX) return -1;
    settings->Serialize(out);
    out[payload_size] = model == 2 ? 0 : 1;
    put_little(out + payload_size + 1, frame_crc(out, payload_size + 1), 2);
    return static_cast<int>(payload_size + 3);
}

int __cdecl be_settings_decode_json(
    const uint8_t* data, size_t size, char* out, size_t capacity
) {
    if (!data || size < 3) return -1;
    const uint8_t flags = data[size - 3];
    if (flags > 1 || frame_crc(data, size - 2) != little(data + size - 2, 2)) return -1;
    const bool recloser = flags == 1;
    auto settings = new_settings(recloser);
    if (settings->SerializeSize() != size - 3) return -1;
    settings->Deserialize(const_cast<uint8_t*>(data));
    return copy_settings_json(settings, out, capacity);
}

int __cdecl be_settings_file_from_payload(
    const uint8_t* data, size_t size, uint32_t model, uint8_t* out, size_t capacity
) {
    if (!data || !out || size + 3 > capacity || size + 3 > INT32_MAX) return -1;
    const bool recloser = model != 2;
    auto settings = new_settings(recloser);
    if (settings->SerializeSize() != size) return -1;
    std::memcpy(out, data, size);
    out[size] = model == 2 ? 0 : 1;
    put_little(out + size + 1, frame_crc(out, size + 1), 2);
    return static_cast<int>(size + 3);
}

int __cdecl be_settings_patch_payload_json(
    const uint8_t* base, size_t base_size,
    const char* json, size_t json_size, uint32_t model,
    uint8_t* out, size_t capacity
) {
    if (!base || !json || !json_size || !out) return -1;
    const bool recloser = model != 2;
    auto settings = new_settings(recloser);
    const size_t payload_size = settings->SerializeSize();
    if (base_size != payload_size || capacity < payload_size || payload_size > INT32_MAX) return -1;
    settings->Deserialize(const_cast<uint8_t*>(base));
    const std::string source(json, json_size);
    if (!json_to_setting(source.c_str(), settings)) return -1;
    settings->PrepareLists(&settings->config, recloser);
    settings->Serialize(out);
    return static_cast<int>(payload_size);
}

int __cdecl be_editor_payload_json(
    const uint8_t* data, size_t size, uint32_t model, char* out, size_t capacity
) {
    if (!data || !out) return -1;
    auto settings = new_settings(model != 2);
    if (settings->SerializeSize() != size) return -1;
    settings->Deserialize(const_cast<uint8_t*>(data));
    cJSON* document = editor_snapshot(settings->config);
    char* json = cJSON_PrintUnformatted(document);
    cJSON_Delete(document);
    if (!json) return -1;
    const size_t length = std::strlen(json);
    if (length + 1 > capacity || length > INT32_MAX) {
        cJSON_free(json);
        return -1;
    }
    std::memcpy(out, json, length + 1);
    cJSON_free(json);
    return static_cast<int>(length);
}

int __cdecl be_editor_patch_payload_json(
    const uint8_t* base, size_t size, const char* json, size_t json_size,
    uint32_t model, uint8_t* out, size_t capacity
) {
    if (!base || !json || !json_size || !out) return -1;
    auto settings = new_settings(model != 2);
    if (settings->SerializeSize() != size || size > capacity || size > INT32_MAX) return -1;
    settings->Deserialize(const_cast<uint8_t*>(base));
    const std::string source(json, json_size);
    cJSON* document = cJSON_Parse(source.c_str());
    const bool valid = editor_apply(settings->config, document);
    cJSON_Delete(document);
    if (!valid) return -1;
    settings->PrepareLists(&settings->config, model != 2);
    settings->Serialize(out);
    return static_cast<int>(size);
}
