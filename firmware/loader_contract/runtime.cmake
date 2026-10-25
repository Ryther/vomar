# Source-only opt-in: preserve legacy consumers unless explicitly enabled.
if(CONFIG_VIMAR_LOADER_RUNTIME_V2)
  if(NOT VIMAR_LOADER_CONTRACT_BINDINGS_HEADER OR NOT EXISTS "${VIMAR_LOADER_CONTRACT_BINDINGS_HEADER}")
    message(FATAL_ERROR "Typed loader runtime requires a finite validated bindings header")
  endif()
  if(NOT CONFIG_VIMAR_ZIGBEE_OTA AND NOT CONFIG_VIMAR_OTA_INSTALLER AND NOT CONFIG_MIGRATION_COMMON)
    message(FATAL_ERROR "Typed runtime requires the existing authenticated image verifier")
  endif()
  target_sources(app PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/loader_contract.c
    ${CMAKE_CURRENT_LIST_DIR}/loader_runtime.c
    ${CMAKE_CURRENT_LIST_DIR}/loader_pair.c
    ${CMAKE_CURRENT_LIST_DIR}/loader_runtime_zephyr.c)
  if(CONFIG_VIMAR_RECOVERY_IDENTITY)
    target_sources(app PRIVATE ${CMAKE_CURRENT_LIST_DIR}/loader_runtime_cbor.c)
  endif()
  target_include_directories(app PRIVATE ${CMAKE_CURRENT_LIST_DIR})
  target_compile_definitions(app PRIVATE VIMAR_LOADER_CONTRACT_BINDINGS_HEADER="${VIMAR_LOADER_CONTRACT_BINDINGS_HEADER}")
endif()
