cmake_minimum_required(VERSION 3.21)
project(FlowchartsDesktop VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
if(MSVC)
    add_compile_options(/utf-8)
endif()

find_package(Qt6 6.4 REQUIRED COMPONENTS Widgets)
include(CTest)

add_library(flowcharts-ui STATIC
    src/commandline.cpp src/commandline.h
    src/protocol.cpp src/protocol.h
    src/engineclient.cpp src/engineclient.h
    src/workspace.cpp src/workspace.h
    src/drawing.cpp src/drawing.h
    src/graphlayout.cpp src/graphlayout.h
    src/graphview.cpp src/graphview.h
    src/sourceview.cpp src/sourceview.h
    src/chartbrowser.cpp src/chartbrowser.h
    src/mainwindow.cpp src/mainwindow.h src/mainwindow_data.cpp
)
target_include_directories(flowcharts-ui PUBLIC src)
target_link_libraries(flowcharts-ui PUBLIC Qt6::Widgets)
if(MSVC)
    target_compile_options(flowcharts-ui PRIVATE /W4)
else()
    target_compile_options(flowcharts-ui PRIVATE -Wall -Wextra -Wpedantic)
endif()

qt_add_executable(flowcharts-desktop WIN32 src/main.cpp)
target_link_libraries(flowcharts-desktop PRIVATE flowcharts-ui)
# Development launcher only. Release bundles will supply an engine executable instead.
get_filename_component(FLOWCHARTS_PROJECT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
target_compile_definitions(flowcharts-desktop PRIVATE
    FLOWCHARTS_PROJECT_DIR="${FLOWCHARTS_PROJECT_DIR}")

if(BUILD_TESTING)
    find_package(Qt6 6.4 REQUIRED COMPONENTS Test)
    foreach(test_name IN ITEMS commandline protocol workspace graphlayout widgets engineclient)
        qt_add_executable(test-${test_name} tests/test_${test_name}.cpp)
        target_link_libraries(test-${test_name} PRIVATE flowcharts-ui Qt6::Test)
        add_test(NAME desktop-${test_name} COMMAND test-${test_name})
        set_tests_properties(desktop-${test_name} PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen" TIMEOUT 30)
    endforeach()
    qt_add_executable(test-integration tests/test_integration.cpp)
    target_link_libraries(test-integration PRIVATE flowcharts-ui Qt6::Test)
    target_compile_definitions(test-integration PRIVATE
        FLOWCHARTS_PROJECT_DIR="${FLOWCHARTS_PROJECT_DIR}")
    add_test(NAME desktop-integration COMMAND test-integration)
    set_tests_properties(desktop-integration PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen" TIMEOUT 60)
    qt_add_executable(fake-engine tests/fake_engine.cpp)
    target_link_libraries(fake-engine PRIVATE Qt6::Core)
    add_dependencies(test-engineclient fake-engine)
endif()
