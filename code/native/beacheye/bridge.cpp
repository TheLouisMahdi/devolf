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

// edited to solve bridge problem poimu
static_assert(sizeof(BEInfo) == 32 && sizeof(BEPoint) == 12 && sizeof(BEEvent) == 24);
static_assert(sizeof(BENamedPoint) == 80 && sizeof(BENamedEvent) == 88);
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
static_assert(SIG_BUFF_SIZE == 64 && offsetof(Signals, Vbat) == 10 * 64 * 4);

namespace {
constexpr uint8_t START_CAT = 0x41;
constexpr uint8_t START_DOG = 0x24;

uint32_t little(const uint8_t* p, size_t count) {
    uint32_t value = 0;
    for (size_t i = 0; i < count; ++i) value |= uint32_t(p[i]) << (8 * i);
    return value;
}

uint64_t little64(const uint8_t* p) {
    uint64_t value = 0;
    for (size_t i = 0; i < 8; ++i) value |= uint64_t(p[i]) << (8 * i);
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
    bool binary_packed;
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
        if (!count || (type != M_TYPE_BI && type != M_TYPE_AI && type != M_TYPE_BC)) return -1;
        const size_t bytes = type == M_TYPE_BI ? (count + 7) / 8 : count * (type == M_TYPE_AI ? 2 : 4);
        if (bytes > size - offset) return -1;
        blocks.push_back({type, count, data + offset, true});
        offset += bytes;
    }
    return 0;
}

int parse_legacy_blocks(const uint8_t* data, size_t size, std::vector<Block>& blocks) {
    if (!data) return -1;
    size_t offset = 0;
    while (offset < size) {
        if (size - offset < 2) return -1;
        const uint32_t header = little(data + offset, 2);
        offset += 2;
        const uint32_t type = header & 15;
        const uint32_t count = header >> 4;
        if (!count || (type != M_TYPE_BI && type != M_TYPE_AI && type != M_TYPE_BC)) return -1;
        const size_t bytes = count * (type == M_TYPE_BI ? 1 : type == M_TYPE_AI ? 2 : 4);
        if (bytes > size - offset) return -1;
        blocks.push_back({type, count, data + offset, false});
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
    // DataProvider initializes the revision to 50 until INFO is received.  The
    // Python service always reads INFO before measurements; keep the company
    // default for direct/offline decoder calls as well.
    return static_cast<uint8_t>(build ? build : 50);
}

// BeachEye revision 50 accepts an explicit device revision while the newer
// branches derive the layout from their branch and expose a one-argument API.
template <typename T>
auto disable_points(T& points, bool recloser, uint8_t revision, int)
    -> decltype(points.DisablePoints(recloser, revision), void()) {
    points.DisablePoints(recloser, revision);
}

template <typename T>
void disable_points(T& points, bool recloser, uint8_t, long) {
    points.DisablePoints(recloser);
}

template <typename T>
void disable_points(T& points, bool recloser, uint8_t revision) {
    disable_points(points, recloser, revision, 0);
}

int append_native_binaries(
    const Block& block, bool recloser, uint32_t build,
    BENamedPoint* out, size_t capacity, size_t& used
) {
    BIs points;
    for (auto& point : points.list) point.Enable();
    disable_points(points, recloser, company_revision(build));
    auto sorted = enabled_in_wire_order(points.list);
    // The separately recognized legacy byte-per-binary format used DNP order.
    if (!block.binary_packed) {
        std::sort(sorted.begin(), sorted.end(), [](const auto* a, const auto* b) {
            return a->dnp3.index < b->dnp3.index;
        });
    }
    if (block.count != sorted.size() || block.count > capacity - used) return -1;
    for (size_t wire = 0; wire < sorted.size(); ++wire) {
        auto* point = sorted[wire];
        auto& target = out[used++];
        target = {
            M_TYPE_BI,
            point->id,
            point->dnp3.index,
            block.binary_packed
                ? (block.values[wire / 8] >> (wire % 8)) & 1u
                : block.values[wire],
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
    for (size_t wire = 0; wire < sorted.size(); ++wire) {
        auto* point = sorted[wire];
        auto& target = out[used++];
        target = {
            M_TYPE_AI, point->id, point->dnp3.index,
            little(block.values + wire * 2, 2), {}
        };
        copy_name(target, point->Name());
    }
    return 0;
}

bool looks_like_event_ring(const uint8_t* data, size_t size) {
    if (!data || size < 24 || (size - 8) % 16 != 0) return false;
    const size_t slots = (size - 8) / 16;
    const size_t next = little(data, 2);
    const uint8_t wrapped = data[2];
    if (!slots || wrapped > 1 || next >= slots) return false;
    for (size_t i = 3; i < 8; ++i) if (data[i] != 0) return false;

    const size_t count = wrapped ? slots : next;
    for (size_t i = 0; i < count; ++i) {
        const uint8_t* record = data + 8 + i * 16;
        if (record[14] > 1) return false;
    }
    return true;
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

bool select_settings_wire_layout(
    const std::shared_ptr<Settings>& settings, bool recloser, size_t payload_size
) {
    if (settings->SerializeSize() == payload_size) return true;

    // Revision-50 devices in the field use the layout from before the final
    // branch commits appended seven DO timers and the new voltage elements.
    // Those fields were appended to each typed list, so trimming only their
    // tails preserves every original byte offset and keeps the branch model.
    const size_t removed_dwords = recloser ? 39 : 7;
    const size_t removed_bytes = recloser ? 32 : 0;
    const size_t removed_dbits = recloser ? 32 : 0;
    if (
        settings->dword_list.size() < removed_dwords ||
        settings->byte_list.size() < removed_bytes ||
        settings->dbit_list.size() < removed_dbits
    ) return false;

    settings->dword_list.resize(settings->dword_list.size() - removed_dwords);
    settings->byte_list.resize(settings->byte_list.size() - removed_bytes);
    settings->dbit_list.resize(settings->dbit_list.size() - removed_dbits);
    return settings->SerializeSize() == payload_size;
}

void add_number(cJSON* object, const char* name, double value) {
    cJSON_AddItemToObject(object, name, cJSON_CreateNumber(value));
}

void add_number(cJSON* array, double value) {
    cJSON_AddItemToArray(array, cJSON_CreateNumber(value));
}

uint32_t object_number(cJSON* object, const char* name, uint32_t fallback, uint32_t maximum);

void add_fast_trip_max_mode(cJSON* group, const char* pack_name, const OCEF_Pack& pack) {
    cJSON* pack_json = cJSON_GetObjectItemCaseSensitive(group, pack_name);
    if (!cJSON_IsObject(pack_json)) return;
    const char* directions[] = {"f", "r"};
    const ElementPack* packs[] = {&pack.forward, &pack.reverse};
    for (size_t index = 0; index < 2; ++index) {
        cJSON* direction = cJSON_GetObjectItemCaseSensitive(pack_json, directions[index]);
        cJSON* fast = cJSON_GetObjectItemCaseSensitive(direction, "f");
        cJSON* tcc = cJSON_GetObjectItemCaseSensitive(fast, "t");
        if (!cJSON_IsObject(tcc)) continue;
        cJSON_DeleteItemFromObjectCaseSensitive(tcc, "mm");
        add_number(tcc, "mm", packs[index]->fast_trip.tcc.max_mode);
    }
}

void apply_fast_trip_max_mode(cJSON* group, const char* pack_name, OCEF_Pack& pack) {
    cJSON* pack_json = cJSON_GetObjectItemCaseSensitive(group, pack_name);
    if (!cJSON_IsObject(pack_json)) return;
    const char* directions[] = {"f", "r"};
    ElementPack* packs[] = {&pack.forward, &pack.reverse};
    for (size_t index = 0; index < 2; ++index) {
        cJSON* direction = cJSON_GetObjectItemCaseSensitive(pack_json, directions[index]);
        cJSON* fast = cJSON_GetObjectItemCaseSensitive(direction, "f");
        cJSON* tcc = cJSON_GetObjectItemCaseSensitive(fast, "t");
        packs[index]->fast_trip.tcc.max_mode = static_cast<uint8_t>(
            object_number(tcc, "mm", packs[index]->fast_trip.tcc.max_mode, 1)
        );
    }
}

cJSON* function_json(const Configure::Function& function) {
    cJSON* item = cJSON_CreateObject();
    cJSON* operands = cJSON_CreateArray();
    cJSON* state = cJSON_CreateArray();
    if (!item || !operands || !state) {
        cJSON_Delete(item);
        cJSON_Delete(operands);
        cJSON_Delete(state);
        return nullptr;
    }
    add_number(item, "t", function.time);
    add_number(item, "v", function.avalue);
    add_number(operands, function.doperands[0]);
    add_number(operands, function.doperands[1]);
    add_number(operands, function.doperands[2]);
    add_number(operands, function.aoperand);
    add_number(state, static_cast<uint8_t>(function.enabled));
    add_number(state, static_cast<uint8_t>(function.dvalue));
    add_number(state, static_cast<uint8_t>(function.source));
    add_number(state, static_cast<uint8_t>(function.doperator));
    add_number(state, static_cast<uint8_t>(function.aoperator));
    add_number(state, static_cast<uint8_t>(function.action));
    cJSON_AddItemToObject(item, "o", operands);
    cJSON_AddItemToObject(item, "s", state);
    return item;
}

bool add_settings_extensions(cJSON* root, const Configure& config) {
    cJSON* system = cJSON_GetObjectItemCaseSensitive(root, "sy");
    cJSON* protection = cJSON_GetObjectItemCaseSensitive(root, "p");
    if (!cJSON_IsObject(system) || !cJSON_IsObject(protection)) return false;

    cJSON* functions = cJSON_CreateArray();
    if (!functions) return false;
    for (const auto& function : config.funcs) {
        cJSON* item = function_json(function);
        if (!item) {
            cJSON_Delete(functions);
            return false;
        }
        cJSON_AddItemToArray(functions, item);
    }
    cJSON_ReplaceItemInObjectCaseSensitive(system, "fn", functions);

    cJSON* groups = cJSON_GetObjectItemCaseSensitive(protection, "g");
    if (!cJSON_IsArray(groups)) return false;
    for (int index = 0; index < 4; ++index) {
        cJSON* group = cJSON_GetArrayItem(groups, index);
        cJSON* sectionalizing = cJSON_GetObjectItemCaseSensitive(group, "sc");
        if (!cJSON_IsObject(sectionalizing)) return false;
        cJSON_DeleteItemFromObjectCaseSensitive(sectionalizing, "s");
        add_number(sectionalizing, "s", config.prot.groups[index].sectionalizing_mode);
        add_fast_trip_max_mode(group, "o", config.prot.groups[index].ocef.oc);
        add_fast_trip_max_mode(group, "e", config.prot.groups[index].ocef.ef);
        add_fast_trip_max_mode(group, "nps", config.nps[index]);

        // The company array helper views these signed words as uint16_t.
        // Export their actual signed values after lossless numeric conversion.
        cJSON* admittance = cJSON_GetObjectItemCaseSensitive(group, "ad");
        cJSON* conductance = cJSON_GetObjectItemCaseSensitive(admittance, "c");
        const auto& adm = config.admittance[index];
        const int16_t signed_values[] = {
            adm.forward_susceptance, adm.reverse_susceptance,
            adm.forward_conductance, adm.reverse_conductance,
        };
        for (int field = 0; field < 4; ++field) {
            cJSON* number = cJSON_GetArrayItem(conductance, field + 1);
            if (cJSON_IsNumber(number)) cJSON_SetNumberValue(number, signed_values[field]);
        }

#ifdef BE_HAS_C_MAX
        cJSON* maximums = cJSON_CreateArray();
        if (!maximums) return false;
        const auto& values = config.c_max[index];
        add_number(maximums, values.oc2_f);
        add_number(maximums, values.oc2_r);
        add_number(maximums, values.ef2_f);
        add_number(maximums, values.ef2_r);
        add_number(maximums, values.nps2_f);
        add_number(maximums, values.nps2_r);
        cJSON_DeleteItemFromObjectCaseSensitive(group, "cm");
        cJSON_AddItemToObject(group, "cm", maximums);
#endif
    }
    return true;
}

uint32_t number_value(cJSON* value, uint32_t fallback, uint32_t maximum) {
    if (!cJSON_IsNumber(value) || value->valuedouble < 0) return fallback;
    return static_cast<uint32_t>(std::min<double>(value->valuedouble, maximum));
}

uint32_t object_number(cJSON* object, const char* name, uint32_t fallback, uint32_t maximum) {
    return number_value(cJSON_GetObjectItemCaseSensitive(object, name), fallback, maximum);
}

void apply_settings_extensions(cJSON* root, Configure& config) {
    cJSON* system = cJSON_GetObjectItemCaseSensitive(root, "sy");
    cJSON* functions = cJSON_GetObjectItemCaseSensitive(system, "fn");
    if (cJSON_IsArray(functions)) {
        const int count = std::min(16, cJSON_GetArraySize(functions));
        for (int index = 0; index < count; ++index) {
            cJSON* item = cJSON_GetArrayItem(functions, index);
            if (!cJSON_IsObject(item)) continue;
            auto& function = config.funcs[index];
            function.time = object_number(item, "t", function.time, UINT32_MAX);
            function.avalue = object_number(item, "v", function.avalue, UINT32_MAX);
            cJSON* operands = cJSON_GetObjectItemCaseSensitive(item, "o");
            if (cJSON_IsArray(operands) && cJSON_GetArraySize(operands) >= 4) {
                function.doperands[0] = number_value(cJSON_GetArrayItem(operands, 0), function.doperands[0], UINT16_MAX);
                function.doperands[1] = number_value(cJSON_GetArrayItem(operands, 1), function.doperands[1], UINT16_MAX);
                function.doperands[2] = number_value(cJSON_GetArrayItem(operands, 2), function.doperands[2], UINT16_MAX);
                function.aoperand = number_value(cJSON_GetArrayItem(operands, 3), function.aoperand, UINT16_MAX);
            }
            cJSON* state = cJSON_GetObjectItemCaseSensitive(item, "s");
            if (cJSON_IsArray(state) && cJSON_GetArraySize(state) >= 6) {
                function.enabled = static_cast<EnDi>(number_value(cJSON_GetArrayItem(state, 0), static_cast<uint8_t>(function.enabled), 1));
                function.dvalue = static_cast<TrFa>(number_value(cJSON_GetArrayItem(state, 1), static_cast<uint8_t>(function.dvalue), 1));
                function.source = static_cast<FNSourceType>(number_value(cJSON_GetArrayItem(state, 2), static_cast<uint8_t>(function.source), 1));
                function.doperator = static_cast<DOperator>(number_value(cJSON_GetArrayItem(state, 3), static_cast<uint8_t>(function.doperator), 2));
                function.aoperator = static_cast<AOperator>(number_value(cJSON_GetArrayItem(state, 4), static_cast<uint8_t>(function.aoperator), 1));
                function.action = static_cast<IOAction>(number_value(cJSON_GetArrayItem(state, 5), static_cast<uint8_t>(function.action), 2));
            }
        }
    }

    cJSON* protection = cJSON_GetObjectItemCaseSensitive(root, "p");
    cJSON* groups = cJSON_GetObjectItemCaseSensitive(protection, "g");
    if (!cJSON_IsArray(groups)) return;
    const int count = std::min(4, cJSON_GetArraySize(groups));
    for (int index = 0; index < count; ++index) {
        cJSON* group = cJSON_GetArrayItem(groups, index);
        cJSON* sectionalizing = cJSON_GetObjectItemCaseSensitive(group, "sc");
        config.prot.groups[index].sectionalizing_mode = static_cast<uint8_t>(
            object_number(sectionalizing, "s", config.prot.groups[index].sectionalizing_mode, 1)
        );
        apply_fast_trip_max_mode(group, "o", config.prot.groups[index].ocef.oc);
        apply_fast_trip_max_mode(group, "e", config.prot.groups[index].ocef.ef);
        apply_fast_trip_max_mode(group, "nps", config.nps[index]);

#ifdef BE_HAS_C_MAX
        cJSON* maximums = cJSON_GetObjectItemCaseSensitive(group, "cm");
        if (cJSON_IsArray(maximums) && cJSON_GetArraySize(maximums) >= 6) {
            auto& values = config.c_max[index];
            values.oc2_f = number_value(cJSON_GetArrayItem(maximums, 0), values.oc2_f, UINT16_MAX);
            values.oc2_r = number_value(cJSON_GetArrayItem(maximums, 1), values.oc2_r, UINT16_MAX);
            values.ef2_f = number_value(cJSON_GetArrayItem(maximums, 2), values.ef2_f, UINT16_MAX);
            values.ef2_r = number_value(cJSON_GetArrayItem(maximums, 3), values.ef2_r, UINT16_MAX);
            values.nps2_f = number_value(cJSON_GetArrayItem(maximums, 4), values.nps2_f, UINT16_MAX);
            values.nps2_r = number_value(cJSON_GetArrayItem(maximums, 5), values.nps2_r, UINT16_MAX);
        }
#endif
    }
}

char* settings_json(const Configure& config) {
    char* company_json = setting_to_json(const_cast<Configure*>(&config));
    if (!company_json) return nullptr;
    cJSON* root = cJSON_Parse(company_json);
    json_free(company_json);
    if (!root) return nullptr;
    if (!add_settings_extensions(root, config)) {
        cJSON_Delete(root);
        return nullptr;
    }
    char* result = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return result;
}

int copy_settings_json(const std::shared_ptr<Settings>& settings, char* out, size_t capacity) {
    if (!out || !capacity) return -1;
    char* json = settings_json(settings->config);
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

uint32_t __cdecl be_abi_version(void) { return 6; }

int __cdecl be_info(const uint8_t* data, size_t size, BEInfo* out) {
    if (!data || !out || size < 16) return -1;
    *out = {data[0], data[1], data[2], data[3], little(data + 4, 2), little(data + 6, 2), {}};
    std::memcpy(out->commit, data + 8, 8);
    return 0;
}

int __cdecl be_measurements(const uint8_t* data, size_t size, BEPoint* out, size_t capacity) {
    if (!data || !out) return -1;
    std::vector<Block> blocks;
    if (parse_blocks(data, size, blocks) < 0) {
        blocks.clear();
        if (parse_legacy_blocks(data, size, blocks) < 0) return -1;
    }
    size_t used = 0;
    for (const auto& block : blocks) {
        if (block.count > capacity - used || used + block.count > INT32_MAX) return -1;
        for (uint32_t i = 0; i < block.count; ++i) {
            const uint32_t value = block.type == M_TYPE_BI
                ? (block.binary_packed
                    ? ((block.values[i / 8] >> (i % 8)) & 1u)
                    : block.values[i])
                : little(block.values + i * (block.type == M_TYPE_AI ? 2 : 4), block.type == M_TYPE_AI ? 2 : 4);
            out[used++] = {block.type, i, value};
        }
    }
    return static_cast<int>(used);
}

int __cdecl be_measurements_named(
    const uint8_t* data, size_t size, uint32_t model, uint32_t build,
    BENamedPoint* out, size_t capacity
) {
    if (!data || !out) return -1;
    std::vector<Block> blocks;
    if (parse_blocks(data, size, blocks) < 0) {
        blocks.clear();
        if (parse_legacy_blocks(data, size, blocks) < 0) return -1;
    }
    size_t used = 0;
    for (const auto& block : blocks) {
        if (block.type == M_TYPE_BC) {
            if (block.count > capacity - used) return -1;
            for (uint32_t i = 0; i < block.count; ++i) {
                auto& target = out[used++];
                target = {M_TYPE_BC, i, i, little(block.values + i * 4, 4), {}};
                char name[32]{};
                std::snprintf(name, sizeof(name), "Counter %u", i);
                copy_name(target, name);
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
    if (!data || !out) return -1;
    size_t offset = 0, used = 0;
    // Keep DataProvider::EventsDeserialize's tolerance for the device's short
    // trailing bytes, while retaining support for one final 8-byte BI record.
    while (offset + 8 <= size) {
        if (used >= capacity || used >= INT32_MAX) return -1;
        const auto type = (little(data + offset, 2) >> 12) & 3;
#ifdef BE_EVENT_RSEQ_API
        const size_t length = type == 0 ? 8 : type == 1 ? 10 : type == 2 ? 12 : 0;
#else
        const size_t length = type == 0 ? 8 : type == 1 ? 10 : 0;
#endif
        if (!length) return -1;
        if (size - offset < length) break;
        uint8_t record[12]{};
        std::memcpy(record, data + offset, length);
        BeachWolf::Event event;
#ifdef BE_EVENT_RSEQ_API
        ser4cpp::rseq_t sequence(record, length);
        event.Deserialize(sequence);
#else
        event.Deserialize(record);
#endif
        out[used++] = {
            event.Time(), static_cast<uint32_t>(event.Type()), event.Position(),
            *event.Ptr(), 0
        };
        offset += event.SerializeSize();
    }
    return static_cast<int>(used);
}

int __cdecl be_events_named(
    const uint8_t* data, size_t size, uint32_t model, uint32_t build,
    BENamedEvent* out, size_t capacity
) {
    if (!data || !out) return -1;
    // Some FC22 firmware generations report a new/unknown build while still
    // downloading the raw Events struct.  Detect its strict 8-byte header and
    // 16-byte slot layout instead of trusting the INFO revision alone.
    if (looks_like_event_ring(data, size)) {
        const size_t slots = (size - 8) / 16;
        const size_t next = little(data, 2);
        const bool wrapped = data[2] != 0;
        const size_t count = wrapped ? slots : std::min(next, slots);
        if (count > capacity || count > INT32_MAX || (count && next >= slots)) return -1;
        for (size_t i = 0; i < count; ++i) {
            const size_t index = (next + slots - 1 - i) % slots;
            const uint8_t* record = data + 8 + index * 16;
            auto& target = out[i];
            target = {
                little64(record),
                record[14],
                static_cast<uint32_t>(little(record + 12, 2)),
                little(record + 8, 4),
                0,
                {}
            };
            const char* name = event_name(target.type, target.source_index, model, build);
            if (name) copy_name(target, name);
            else {
                char fallback[32]{};
                const char* prefix = target.type == 0 ? "BI" : target.type == 1 ? "AI" : "CC";
                std::snprintf(fallback, sizeof(fallback), "%s %u", prefix, target.source_index);
                copy_name(target, fallback);
            }
        }
        return static_cast<int>(count);
    }
    std::vector<BEEvent> decoded(std::max<size_t>(1, size / 8));
    const int count = be_events(data, size, decoded.data(), decoded.size());
    if (count < 0 || static_cast<size_t>(count) > capacity) return -1;
    for (int i = 0; i < count; ++i) {
        const auto& source = decoded[i];
        auto& target = out[i];
        target = {source.time_ms, source.type, source.index, source.value, 0, {}};
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

int __cdecl be_signal(const uint8_t* data, size_t size, float* out, size_t capacity) {
    constexpr size_t modern_bytes = offsetof(Signals, Vbat);
    constexpr size_t legacy_bytes = 7 * SIG_BUFF_SIZE * sizeof(float);
    if (!data || !out || capacity < modern_bytes / sizeof(float)) return -1;
    if (size >= modern_bytes) {
        std::memcpy(out, data, modern_bytes);
        return static_cast<int>(modern_bytes / sizeof(float));
    }
    if (size >= legacy_bytes) {
        std::memcpy(out, data, legacy_bytes);
        std::memset(reinterpret_cast<uint8_t*>(out) + legacy_bytes, 0, modern_bytes - legacy_bytes);
        return static_cast<int>(legacy_bytes / sizeof(float));
    }
    return -1;
}

int __cdecl be_frame_build(
    uint8_t type, const uint8_t* payload, size_t payload_size,
    uint8_t* out, size_t capacity
) {
    if (!out || (payload_size && !payload) || payload_size > MAX_DATA_SIZE || capacity < payload_size + 7) return -1;
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
    if (payload_size > MAX_DATA_SIZE || size != payload_size + 7 || payload_size > capacity || (payload_size && !payload)) return -1;
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
    if (!select_settings_wire_layout(settings, recloser, size)) return -1;
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
    apply_settings_extensions(parsed, settings->config);
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
    if (!select_settings_wire_layout(settings, recloser, size - 3)) return -1;
    settings->Deserialize(const_cast<uint8_t*>(data));
    return copy_settings_json(settings, out, capacity);
}

int __cdecl be_settings_file_from_payload(
    const uint8_t* data, size_t size, uint32_t model, uint8_t* out, size_t capacity
) {
    if (!data || !out || size + 3 > capacity || size + 3 > INT32_MAX) return -1;
    const bool recloser = model != 2;
    auto settings = new_settings(recloser);
    if (!select_settings_wire_layout(settings, recloser, size)) return -1;
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
    auto original = new_settings(recloser);
    if (!select_settings_wire_layout(original, recloser, base_size)) return -1;
    const size_t payload_size = original->SerializeSize();
    if (capacity < payload_size || payload_size > INT32_MAX) return -1;

    // The company's JSON conversion is not byte-idempotent: applying an
    // unchanged JSON document also normalizes legacy/reserved members. Build
    // both the unchanged and edited forms, then copy only the byte differences
    // caused by the user's edit onto the exact input payload.
    original->Deserialize(const_cast<uint8_t*>(base));
    char* original_json = settings_json(original->config);
    if (!original_json) return -1;

    auto serialize_with_json = [&](const char* source, size_t source_size, std::vector<uint8_t>& target) {
        std::string document(source, source_size);
        cJSON* parsed = cJSON_Parse(document.c_str());
        if (!parsed) return false;
        auto settings = new_settings(recloser);
        if (!select_settings_wire_layout(settings, recloser, payload_size)) {
            cJSON_Delete(parsed);
            return false;
        }
        settings->Deserialize(const_cast<uint8_t*>(base));
        if (!json_to_setting(document.c_str(), settings)) {
            cJSON_Delete(parsed);
            return false;
        }
        apply_settings_extensions(parsed, settings->config);
        cJSON_Delete(parsed);
        target.resize(payload_size);
        settings->Serialize(target.data());
        return true;
    };

    std::vector<uint8_t> baseline;
    std::vector<uint8_t> edited;
    const bool baseline_ok = serialize_with_json(
        original_json, std::strlen(original_json), baseline
    );
    cJSON_free(original_json);
    if (!baseline_ok || !serialize_with_json(json, json_size, edited)) return -1;

    std::memcpy(out, base, payload_size);
    for (size_t i = 0; i < payload_size; ++i) {
        if (edited[i] != baseline[i]) out[i] = edited[i];
    }
    return static_cast<int>(payload_size);
}

size_t __cdecl be_settings_legacy_size(void) {
    return sizeof(Configure);
}

int __cdecl be_settings_legacy_payload_json(
    const uint8_t* data, size_t size, char* out, size_t capacity
) {
    if (!data || !size || size > sizeof(Configure) || !out || !capacity) return -1;
    Configure config{};
    std::memcpy(&config, data, size);
    char* json = settings_json(config);
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

int __cdecl be_settings_legacy_patch_payload_json(
    const uint8_t* base, size_t base_size,
    const char* json, size_t json_size,
    uint8_t* out, size_t capacity
) {
    if (!base || !base_size || base_size > sizeof(Configure) || !json || !json_size ||
        !out || capacity < base_size) return -1;

    Configure original{};
    std::memcpy(&original, base, base_size);
    char* original_json = settings_json(original);
    if (!original_json) return -1;

    auto apply = [&](const char* source, size_t source_size, std::vector<uint8_t>& target) {
        std::string document(source, source_size);
        cJSON* parsed = cJSON_Parse(document.c_str());
        if (!parsed) return false;
        auto settings = std::make_shared<Settings>();
        std::memset(&settings->config, 0, sizeof(Configure));
        std::memcpy(&settings->config, base, base_size);
        if (!json_to_setting(document.c_str(), settings)) {
            cJSON_Delete(parsed);
            return false;
        }
        apply_settings_extensions(parsed, settings->config);
        cJSON_Delete(parsed);
        target.resize(sizeof(Configure));
        std::memcpy(target.data(), &settings->config, sizeof(Configure));
        return true;
    };

    std::vector<uint8_t> baseline;
    std::vector<uint8_t> edited;
    const bool baseline_ok = apply(original_json, std::strlen(original_json), baseline);
    cJSON_free(original_json);
    if (!baseline_ok || !apply(json, json_size, edited)) return -1;

    std::memcpy(out, base, base_size);
    for (size_t i = 0; i < base_size; ++i) {
        if (edited[i] != baseline[i]) out[i] = edited[i];
    }
    return static_cast<int>(base_size);
}
