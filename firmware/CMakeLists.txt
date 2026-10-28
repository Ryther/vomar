cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(vimar_30805_platform)

target_sources(app PRIVATE
    src/main.c
    src/dimmer_config.c
    src/phase_cut_control.c
    src/dimmer_model.c
    src/gesture_classifier.c
    src/local_action_mapper.c
    src/led_controller.c
    src/settings_record.c
    src/settings_store.c
    src/app_settings_backend.c
    src/application_controller.c
    src/zigbee_custom_codec.c
    src/ota_runtime_contract.c
    src/zigbee_device.c
    src/zigbee_report_policy.c
    src/wireless_status_led.c
    src/connection_pairing.c
    src/connection_capability.c
    src/connection_intent_zephyr.c
    src/zboss_mem_globals.c
)

target_include_directories(app PRIVATE src)
zephyr_link_libraries(-Wl,--undefined=vimar_connection_pairing_capability)

if(CONFIG_LTO)
    set_source_files_properties(src/zboss_mem_globals.c PROPERTIES COMPILE_OPTIONS -fno-lto)
endif()

if(CONFIG_ZBOSS_RESET_ON_ASSERT)
    # The pinned SDK fatal reset writes SYS_REBOOT_COLD=1 into GPREGRET1,
    # colliding with MCUboot's BOOTLOADER=1. Wrap only its external abort entry.
    # Keep the SDK translation unit outside LTO so calls cannot inline the
    # original register write before the linker applies --wrap.
    set(vimar_zb_platform "${ZEPHYR_NCS_ZIGBEE_MODULE_DIR}/subsys/osif/zb_nrf_platform.c")
    if(NOT EXISTS "${vimar_zb_platform}" OR NOT TARGET ..__ncs-zigbee__subsys)
        message(FATAL_ERROR "Zigbee reset guard requires the pinned ncs-zigbee OSIF target")
    endif()
    file(SHA256 "${vimar_zb_platform}" vimar_zb_platform_sha256)
    if(NOT vimar_zb_platform_sha256 STREQUAL "6dda587ed95c3c7bdc4d810907b2afe06ab63526e76510abf8799e7f0ad8de8f")
        message(FATAL_ERROR "Zigbee reset guard requires review of the changed SDK reset path")
    endif()
    set_property(SOURCE "${vimar_zb_platform}" TARGET_DIRECTORY ..__ncs-zigbee__subsys
        APPEND PROPERTY COMPILE_OPTIONS -fno-lto)
    target_sources(app PRIVATE src/zigbee_reset_guard.c)
    set_source_files_properties(src/zigbee_reset_guard.c PROPERTIES COMPILE_OPTIONS -fno-lto)
    zephyr_link_libraries(-Wl,--wrap=zb_osif_abort)
endif()

if(CONFIG_VIMAR_FAULT_DIAGNOSTICS)
    if(NOT VIMAR_FAULT_BUILD_ID_HEADER OR NOT EXISTS "${VIMAR_FAULT_BUILD_ID_HEADER}")
        message(FATAL_ERROR "Fault capture requires an immutable generated build ID")
    endif()
    target_sources(app PRIVATE src/fault_diag.c src/fault_diag_zephyr.c)
    target_compile_definitions(app PRIVATE VIMAR_FAULT_BUILD_ID_HEADER="${VIMAR_FAULT_BUILD_ID_HEADER}")
    set(vimar_zb_utils "${ZEPHYR_NCS_ZIGBEE_MODULE_DIR}/subsys/lib/zigbee_app_utils/zigbee_app_utils.c")
    set(vimar_zb_errors "${ZEPHYR_NCS_ZIGBEE_MODULE_DIR}/include/zigbee/zigbee_error_handler.h")
    file(SHA256 "${vimar_zb_utils}" vimar_zb_utils_sha)
    file(SHA256 "${vimar_zb_errors}" vimar_zb_errors_sha)
    if(NOT vimar_zb_utils_sha STREQUAL "58431692bc9461bab199d55353ff56c25d12c9d8530dbfbe6c52b37e83f37fef" OR
       NOT vimar_zb_errors_sha STREQUAL "a5470831abcb5c99ab805d33206c2b668a8e303d7707b8ab01038fd88526320f")
        message(FATAL_ERROR "Fault capture requires review of changed SDK checked-error sites")
    endif()
    set(vimar_diag_hook "${CMAKE_CURRENT_SOURCE_DIR}/src/fault_diag_error_hook.h")
    set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/src/zigbee_device.c" APPEND PROPERTY
        COMPILE_OPTIONS "-include${vimar_diag_hook}" -DVIMAR_DIAG_ERROR_SITE=1 -fno-lto -fno-optimize-sibling-calls)
    set_property(SOURCE "${vimar_zb_utils}" TARGET_DIRECTORY ..__ncs-zigbee__subsys__lib__zigbee_app_utils APPEND PROPERTY
        COMPILE_OPTIONS "-include${vimar_diag_hook}" -DVIMAR_DIAG_ERROR_SITE=2 -fno-lto -fno-optimize-sibling-calls)
    target_include_directories(..__ncs-zigbee__subsys__lib__zigbee_app_utils PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
    set_source_files_properties(src/fault_diag.c src/fault_diag_zephyr.c PROPERTIES COMPILE_OPTIONS -fno-lto)
endif()

if(CONFIG_VIMAR_HARDWARE)
    target_sources(app PRIVATE src/platform_io_vimar.c src/vimar_identity.c src/vimar_level.c src/vimar_led.c src/vimar_buttons.c src/vimar_attachment.c src/vimar_attachment_gpio.c
        research/src/research_output.c research/src/research_protocol.c research/src/research_handoff.c)
    target_include_directories(app PRIVATE research/src)
else()
    target_sources(app PRIVATE src/platform_io_dk.c)
endif()

if(CONFIG_VIMAR_ZIGBEE_OTA)
target_sources(app PRIVATE src/zigbee_ota.c ota/ota_stage.c ota/ota_transaction.c ota/ota_storage.c ota/ota_format.c ota/ota_image.c ota/ota_split_stage.c ota/ota_pair.c)
target_include_directories(app PRIVATE ota)
target_compile_definitions(app PRIVATE OTA_IMAGE_AUTH_ONLY)
endif()

if(CONFIG_VIMAR_P031_PROTECTION)
  target_sources(app PRIVATE src/candidate_power_protection.c src/vimar_power_protection.c src/boot_trace.c src/boot_trace_zephyr.c)
  target_include_directories(app PRIVATE src research/src)
endif()

if(CONFIG_VIMAR_OTA_SPLIT_STAGING)
  if(NOT VIMAR_OTA_PAIR_BINDINGS_HEADER OR NOT EXISTS "${VIMAR_OTA_PAIR_BINDINGS_HEADER}")
    message(FATAL_ERROR "Split OTA requires frozen authorized pair bindings header")
  endif()
  target_compile_definitions(app PRIVATE VIMAR_OTA_PAIR_BINDINGS_HEADER="${VIMAR_OTA_PAIR_BINDINGS_HEADER}")
endif()

include(${CMAKE_CURRENT_SOURCE_DIR}/loader_contract/runtime.cmake)
