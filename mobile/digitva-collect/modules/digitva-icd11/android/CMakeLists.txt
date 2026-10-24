cmake_minimum_required(VERSION 3.22.1)
project(digitvaicd11shim C)

add_library(digitvaicd11shim SHARED src/main/cpp/shim.c)
target_link_libraries(digitvaicd11shim dl)
