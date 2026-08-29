cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico CACHE STRING "Board type") # plain Pico (RP2040)

# SDK lives next to this project in src/pico-sdk unless overridden.
if (NOT DEFINED ENV{PICO_SDK_PATH} AND NOT PICO_SDK_PATH)
    set(PICO_SDK_PATH ${CMAKE_CURRENT_LIST_DIR}/../pico-sdk)
endif()

include(pico_sdk_import.cmake)

project(detector_firmware C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

add_executable(detector-firmware
    main.c
    ssd1306.c
    pi_engine.c
)

pico_generate_pio_header(detector-firmware ${CMAKE_CURRENT_LIST_DIR}/ws2812.pio)

target_link_libraries(detector-firmware
    pico_stdlib
    hardware_adc
    hardware_pwm
    hardware_i2c
    hardware_pio
    hardware_spi
)

# Debug console on UART0 (GP0/GP1); USB stdio off so no tinyusb submodule needed.
pico_enable_stdio_uart(detector-firmware 1)
pico_enable_stdio_usb(detector-firmware 0)

pico_add_extra_outputs(detector-firmware) # .uf2 for drag-and-drop flashing
