cmake_minimum_required(VERSION 3.20)
project(wolfeye_beacheye LANGUAGES C CXX)

if(NOT WIN32)
    message(FATAL_ERROR "This bridge targets Windows, matching the supplied BeachEye sources.")
endif()
set(SER4CPP_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/compat" CACHE PATH "Directory containing ser4cpp headers")
if(NOT EXISTS "${SER4CPP_INCLUDE_DIR}/ser4cpp/serialization/LittleEndian.h")
    message(FATAL_ERROR "Missing ser4cpp-compatible headers: set SER4CPP_INCLUDE_DIR to their parent directory.")
endif()

# DataProvider supplies CRC and cJSON. BeachEye sources come from the revision
# selected by build-native.ps1. Bridge code remains outside both source trees.
set(DATAPROVIDER_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../DataProvider" CACHE PATH "Company DataProvider source directory")
set(BEACHEYE_DIR "" CACHE PATH "Authenticated private BeachEye source directory")
set(WOLFEYE_DIR "" CACHE PATH "Authenticated private WolfEye source directory")
if(NOT BEACHEYE_DIR)
    message(FATAL_ERROR "BEACHEYE_DIR must point to the authenticated private dependency checkout.")
endif()
if(NOT WOLFEYE_DIR)
    message(FATAL_ERROR "WOLFEYE_DIR must point to the authenticated company WolfEye checkout.")
endif()
# Compile only a pristine checkout of the authenticated company dependency.
find_package(Git REQUIRED)
execute_process(
    COMMAND "${GIT_EXECUTABLE}" -C "${BEACHEYE_DIR}" status --porcelain --untracked-files=all
    RESULT_VARIABLE BEACHEYE_STATUS_RESULT
    OUTPUT_VARIABLE BEACHEYE_STATUS
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT BEACHEYE_STATUS_RESULT EQUAL 0 OR NOT BEACHEYE_STATUS STREQUAL "")
    message(FATAL_ERROR "BeachEye must be an unmodified company Git checkout: ${BEACHEYE_DIR}")
endif()
execute_process(
    COMMAND "${GIT_EXECUTABLE}" -C "${WOLFEYE_DIR}" status --porcelain --untracked-files=all
    RESULT_VARIABLE WOLFEYE_STATUS_RESULT
    OUTPUT_VARIABLE WOLFEYE_STATUS
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT WOLFEYE_STATUS_RESULT EQUAL 0 OR NOT WOLFEYE_STATUS STREQUAL "")
    message(FATAL_ERROR "WolfEye must be an unmodified company Git checkout: ${WOLFEYE_DIR}")
endif()

foreach(REQUIRED_FILE
    "${DATAPROVIDER_DIR}/include/crc.h"
    "${DATAPROVIDER_DIR}/src/crc.c"
    "${DATAPROVIDER_DIR}/cJSON/cJSON.h"
    "${DATAPROVIDER_DIR}/cJSON/cJSON.c"
    "${BEACHEYE_DIR}/include/Settings.h"
    "${BEACHEYE_DIR}/src/Settings.cpp"
    "${BEACHEYE_DIR}/src/cJSON_Imp.cpp"
    "${WOLFEYE_DIR}/WolfEye/include/TCCCalculator.h"
    "${WOLFEYE_DIR}/WolfEye/src/TCCCalculator.cpp"
)
    if(NOT EXISTS "${REQUIRED_FILE}")
        message(FATAL_ERROR "A required private/native build input is missing: ${REQUIRED_FILE}")
    endif()
endforeach()

# These pure UI transition functions share a translation unit with ImGui in
# upstream. Include their exact source slice without editing the checkout or
# keeping a second implementation in this repository.
file(READ "${WOLFEYE_DIR}/WolfEye/src/SettingsView.cpp" COMPANY_SETTINGS_VIEW)
string(FIND "${COMPANY_SETTINGS_VIEW}" "#define L AR_MODE::AR_MODE_LOCK" STAGE_RULES_BEGIN)
string(FIND "${COMPANY_SETTINGS_VIEW}" "const char* stage_mode_to_str" STAGE_RULES_END)
if(STAGE_RULES_BEGIN LESS 0 OR STAGE_RULES_END LESS STAGE_RULES_BEGIN)
    message(FATAL_ERROR "Cannot locate the pinned company AR transition functions.")
endif()
math(EXPR STAGE_RULES_LENGTH "${STAGE_RULES_END} - ${STAGE_RULES_BEGIN}")
string(SUBSTRING "${COMPANY_SETTINGS_VIEW}" ${STAGE_RULES_BEGIN} ${STAGE_RULES_LENGTH} COMPANY_STAGE_RULES)
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/company_stage_rules.inc" "${COMPANY_STAGE_RULES}")
file(READ "${WOLFEYE_DIR}/WolfEye/src/FaultViewer.cpp" COMPANY_FAULT_VIEWER)
string(FIND "${COMPANY_FAULT_VIEWER}" "struct SignalsBuf" SIGNAL_BEGIN)
string(FIND "${COMPANY_FAULT_VIEWER}" "void fault_viewer_init()" SIGNAL_END)
if(SIGNAL_BEGIN LESS 0 OR SIGNAL_END LESS SIGNAL_BEGIN)
    message(FATAL_ERROR "Cannot locate the pinned company signal loader.")
endif()
math(EXPR SIGNAL_LENGTH "${SIGNAL_END} - ${SIGNAL_BEGIN}")
string(SUBSTRING "${COMPANY_FAULT_VIEWER}" ${SIGNAL_BEGIN} ${SIGNAL_LENGTH} COMPANY_SIGNAL_LOADER)
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/company_signal_loader.inc" "${COMPANY_SIGNAL_LOADER}")

add_library(wolfeye_beacheye SHARED
    bridge.cpp
    data_provider_adapter.cpp
    protection_adapter.cpp
    settings_editor.cpp
    signal_adapter.cpp
    "${WOLFEYE_DIR}/WolfEye/src/TCCCalculator.cpp"
    "${BEACHEYE_DIR}/src/Database.cpp"
    "${BEACHEYE_DIR}/src/Event.cpp"
    "${BEACHEYE_DIR}/src/MenuItemAttr.cpp"
    "${BEACHEYE_DIR}/src/Settings.cpp"
    "${BEACHEYE_DIR}/src/cJSON_Imp.cpp"
    "${DATAPROVIDER_DIR}/src/crc.c"
    "${DATAPROVIDER_DIR}/cJSON/cJSON.c"
)
target_compile_features(wolfeye_beacheye PRIVATE cxx_std_17)
target_include_directories(wolfeye_beacheye PRIVATE
    .
    "${CMAKE_CURRENT_BINARY_DIR}"
    "${BEACHEYE_DIR}/include"
    "${WOLFEYE_DIR}/WolfEye/include"
    "${SER4CPP_INCLUDE_DIR}"
    "${DATAPROVIDER_DIR}/include"
    "${DATAPROVIDER_DIR}/cJSON"
)

target_link_libraries(wolfeye_beacheye PRIVATE ws2_32)
# Map firmware-only cJSON allocator names to desktop CRT functions.
target_compile_definitions(wolfeye_beacheye PRIVATE
    NOMINMAX
    REVISION=50
    cjosn_helper_malloc=malloc
    cjosn_helper_free=free
    cjson_helper_realloc=realloc
)
set_target_properties(wolfeye_beacheye PROPERTIES PREFIX "" MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
if(MINGW)
    target_link_options(wolfeye_beacheye PRIVATE -static -static-libgcc -static-libstdc++)
endif()
install(TARGETS wolfeye_beacheye RUNTIME DESTINATION .)
