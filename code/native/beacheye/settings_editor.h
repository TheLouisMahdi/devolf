#pragma once
#include "Settings.h"
#include "cJSON.h"

// UI marshalling only. Wire serialization remains Settings::Serialize and
// Settings::Deserialize from the unmodified company dependency.
cJSON* editor_snapshot(Configure& config);
bool editor_apply(Configure& config, const cJSON* document);
