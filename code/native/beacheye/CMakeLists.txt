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
if(NOT BEACHEYE_DIR)
    message(FATAL_ERROR "BEACHEYE_DIR must point to the authenticated private dependency checkout.")
endif()
foreach(REQUIRED_FILE
    "${DATAPROVIDER_DIR}/include/crc.h"
    "${DATAPROVIDER_DIR}/src/crc.c"
    "${DATAPROVIDER_DIR}/cJSON/cJSON.h"
    "${DATAPROVIDER_DIR}/cJSON/cJSON.c"
    "${BEACHEYE_DIR}/include/Settings.h"
    "${BEACHEYE_DIR}/src/Settings.cpp"
    "${BEACHEYE_DIR}/src/cJSON_Imp.cpp"
)
    if(NOT EXISTS "${REQUIRED_FILE}")
        message(FATAL_ERROR "A required private/native build input is missing: ${REQUIRED_FILE}")
    endif()
endforeach()

add_library(wolfeye_beacheye SHARED
    bridge.cpp
    data_provider_adapter.cpp
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
    "${BEACHEYE_DIR}/include"
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
