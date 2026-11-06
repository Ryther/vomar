"""Execute the real recorder with synthetic SDK queues; no vendor or device use."""
from pathlib import Path
import subprocess
import pytest
from tools.firmware.tests.test_zigbee_ownership_sdk import SDK

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture(scope='module')
def provenance(tmp_path_factory):
    directory=tmp_path_factory.mktemp('allocation-provenance')
    (directory/'zboss_api.h').write_text(SDK+'\ntypedef uint8_t zb_bool_t;\ntypedef uint16_t zb_uint16_t;\ntypedef void (*zb_callback2_t)(zb_uint8_t,zb_uint16_t);\n')
    (directory/'zephyr').mkdir()
    (directory/'zephyr/irq.h').write_text('unsigned irq_lock(void);\nvoid irq_unlock(unsigned);\n')
    (directory/'zephyr/kernel.h').write_text('#include <stdint.h>\n#include <stdbool.h>\nvoid *k_current_get(void);\nbool k_is_in_isr(void);\nuint32_t k_uptime_get_32(void);\n')
    (directory/'trace-build-id.h').write_text('#include <stdint.h>\nextern volatile uint32_t synthetic_retained[64];\n#define ALLOC_RETAINED synthetic_retained\nstatic const uint8_t vimar_fault_build_id[16]={0x66};\n')
    target=directory/'provenance'
    result=subprocess.run(['cc','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
        '-fno-optimize-sibling-calls','-fno-ipa-icf','-fsanitize=undefined','-fno-sanitize-recover=all',
        '-DVIMAR_FAULT_BUILD_ID_HEADER="trace-build-id.h"','-I',str(directory),
        '-I',str(ROOT/'firmware/src'),str(ROOT/'tools/firmware/tests/zigbee_alloc_provenance_test.c'),
        str(ROOT/'firmware/src/zigbee_alloc_trace.c'),'-o',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return target


@pytest.mark.parametrize('case',['hipri_out','hipri_in','immediate','duplicates_wrap','retry','reset','mismatch','suppress_outer','immediate_unknown_outer','mismatch_retry','busy_retry','busy_reset'])
def test_native_request_provenance(provenance,case):
    result=subprocess.run([str(provenance),case],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
