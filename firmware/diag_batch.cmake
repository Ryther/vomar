if(CONFIG_VIMAR_ZIGBEE_DIAGNOSTIC_BATCH)
  set(vimar_diag_trace "${vimar_ownership_sdk}/trace/lib/cortex-m4/hard-float/libzboss.a")
  if(CONFIG_ZIGBEE_ENABLE_TRACES)
    set(vimar_diag_input "${vimar_diag_trace}")
    set(vimar_diag_prepare prepare_diag_batch_sdk.py)
    set(vimar_diag_extra)
  else()
    set(vimar_diag_input "${vimar_ownership_sdk}/lib/cortex-m4/hard-float/libzboss.a")
    set(vimar_diag_prepare prepare_compact_sdk.py)
    set(vimar_diag_extra --trace-archive "${vimar_diag_trace}" --cc "${CMAKE_C_COMPILER}")
  endif()
  set(vimar_diag_output "${CMAKE_BINARY_DIR}/vimar-diag-sdk/libzboss.a")
  set(vimar_diag_report "${CMAKE_BINARY_DIR}/diag-batch-sdk.json")
  execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../tools/firmware/${vimar_diag_prepare}"
      --archive "${vimar_diag_input}" --output "${vimar_diag_output}"
      --ar "${CMAKE_AR}" --objcopy "${CMAKE_OBJCOPY}" --report "${vimar_diag_report}"
      ${vimar_diag_extra}
    RESULT_VARIABLE vimar_diag_status OUTPUT_VARIABLE vimar_diag_stdout ERROR_VARIABLE vimar_diag_stderr)
  if(NOT vimar_diag_status EQUAL 0)
    message(FATAL_ERROR "Diagnostic SDK derivation failed: ${vimar_diag_stdout}${vimar_diag_stderr}")
  endif()
  get_target_property(vimar_diag_libraries zboss INTERFACE_LINK_LIBRARIES)
  list(FIND vimar_diag_libraries "${vimar_diag_input}" vimar_diag_index)
  if(vimar_diag_index LESS 0)
    message(FATAL_ERROR "Reviewed diagnostic SDK input is not selected")
  endif()
  list(REMOVE_AT vimar_diag_libraries ${vimar_diag_index})
  list(INSERT vimar_diag_libraries ${vimar_diag_index} "${vimar_diag_output}")
  set_property(TARGET zboss PROPERTY INTERFACE_LINK_LIBRARIES "${vimar_diag_libraries}")
  vimar_ownership_require_selected_library(zboss "${vimar_diag_output}")
  target_sources(app PRIVATE src/zigbee_diag_batch.c src/zigbee_alloc_trace.c)
  set_source_files_properties(src/zigbee_diag_batch.c src/zigbee_alloc_trace.c
    PROPERTIES COMPILE_OPTIONS -fno-lto)
  add_custom_target(vimar_diag_batch_admission ALL
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../tools/firmware/check_diag_batch_link.py"
      "${CMAKE_BINARY_DIR}/zephyr/zephyr.elf" --sdk-report "${vimar_diag_report}"
      --ar "${CMAKE_AR}"
      --output "${CMAKE_BINARY_DIR}/diag-batch-link-audit.json"
    DEPENDS vimar_ownership_admission
    VERBATIM)
endif()
