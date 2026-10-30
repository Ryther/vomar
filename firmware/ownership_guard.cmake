function(vimar_ownership_require_selected_library target expected)
  # Match the SDK's source/precompiled selection, including DEFINED semantics.
  if(DEFINED CONFIG_ZBOSS_SOURCES_AVAILABLE AND NOT CONFIG_ZBOSS_LIBRARY_PRECOMPILED)
    message(FATAL_ERROR "Ownership guard requires the reviewed precompiled library")
  endif()
  if(NOT TARGET "${target}")
    message(FATAL_ERROR "Ownership guard native library target is missing")
  endif()
  get_target_property(selected "${target}" INTERFACE_LINK_LIBRARIES)
  list(FILTER selected INCLUDE REGEX "/libzboss[^/]*\\.a$")
  if(NOT "${selected}" STREQUAL "${expected}")
    message(FATAL_ERROR "Ownership guard selected archive differs from the reviewed library")
  endif()
endfunction()

if(CONFIG_VIMAR_ZIGBEE_OWNERSHIP_GUARD)
  if(CONFIG_LTO OR NOT CONFIG_ZIGBEE_ENABLE_TRACES)
    message(FATAL_ERROR "Ownership guard requires the reviewed native library")
  endif()
  if(NOT CONFIG_FPU OR NOT CONFIG_FP_HARDABI OR CONFIG_ZIGBEE_ROLE_END_DEVICE)
    message(FATAL_ERROR "Ownership guard requires the pinned router/coordinator hard-float ABI")
  endif()
  set(vimar_ownership_sdk "${ZEPHYR_NCS_ZIGBEE_MODULE_DIR}/lib/zboss")
  function(vimar_ownership_require_hash relative expected)
    set(path "${vimar_ownership_sdk}/${relative}")
    if(NOT EXISTS "${path}")
      message(FATAL_ERROR "Ownership guard SDK input missing: ${relative}")
    endif()
    file(SHA256 "${path}" actual)
    if(NOT actual STREQUAL expected)
      message(FATAL_ERROR "Ownership guard requires SDK review: ${relative}")
    endif()
  endfunction()
  vimar_ownership_require_selected_library(zboss
    "${vimar_ownership_sdk}/trace/lib/cortex-m4/hard-float/libzboss.a")
  vimar_ownership_require_hash(trace/lib/cortex-m4/hard-float/libzboss.a
    879bc7c8f39a8c66a02ad119db50a4c637835c572f1277bba88aff51a826ebf0)
  vimar_ownership_require_hash(src/include/zb_bufpool.h
    68ba31b056566d764442b91918fbd901a88e43b4bbb4603380d161db4abdc066)
  vimar_ownership_require_hash(src/include/zb_nwk.h
    862973a46358578828a56105bda8f5db2cd3d4dcb9c3a51ff79781d61673d2ef)
  vimar_ownership_require_hash(src/include/zb_nwk_mm.h
    ca7b77b55a6f6270795a2e92086d8c3034ec68a1471eefb98ed5d943739f87c1)
  vimar_ownership_require_hash(src/include/zb_mac.h
    ecde575912a219bd55b9168cb52a4f98db59dc31663916cbd196910259597c97)
  vimar_ownership_require_hash(include/zboss_api_buf.h
    b16102cd3c3e322753453969178d849b90f348bf0897b67735b7dc35127afce3)
  vimar_ownership_require_hash(trace/include/libzboss_config.h
    508789108189c89cf1811da13d1db3d41593bc69cce8a502f7a13c3a57900953)
  set(vimar_ownership_source "${CMAKE_CURRENT_LIST_DIR}/src")
  target_sources(app PRIVATE "${vimar_ownership_source}/zigbee_ownership_guard.c"
    "${vimar_ownership_source}/zigbee_ownership_sdk.c")
  target_include_directories(app PRIVATE "${vimar_ownership_sdk}/src/include"
    "${vimar_ownership_source}")
  set_source_files_properties("${vimar_ownership_source}/zigbee_ownership_guard.c"
    "${vimar_ownership_source}/zigbee_ownership_sdk.c"
    PROPERTIES COMPILE_OPTIONS -fno-lto)
  foreach(symbol zb_bufpool_storage_init zb_bufpool_storage_allocate
      zb_bufpool_storage_free zb_buf_copy_func zb_buf_initial_alloc_func
      zb_buf_reuse_func zb_nlde_data_request zb_schedule_callback
      zb_nwk_handle_mcps_data_confirm)
    zephyr_link_libraries("-Wl,--wrap=${symbol}")
  endforeach()
  zephyr_link_libraries(-Wl,--emit-relocs)
  add_custom_target(vimar_ownership_admission ALL
    COMMAND "${Python3_EXECUTABLE}"
      "${CMAKE_CURRENT_LIST_DIR}/../tools/firmware/check_ownership_link.py"
      "${CMAKE_BINARY_DIR}/zephyr/zephyr.elf"
      --output "${CMAKE_BINARY_DIR}/ownership-link-audit.json"
    DEPENDS zephyr_final
    VERBATIM)
endif()
