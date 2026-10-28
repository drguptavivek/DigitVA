cmake_minimum_required(VERSION 3.22.1)
project(digitva_smartva_jni)

add_library(smartva_rust SHARED IMPORTED)
set_target_properties(smartva_rust PROPERTIES
  IMPORTED_LOCATION "${CMAKE_CURRENT_LIST_DIR}/../jniLibs/${ANDROID_ABI}/libsmartva_rust.so")

add_library(smartva_jni SHARED SmartVaJni.cpp)
target_link_options(smartva_jni PRIVATE "-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384")
target_link_libraries(smartva_jni smartva_rust)
