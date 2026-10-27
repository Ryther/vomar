import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


class WirelessStatusLedTests(unittest.TestCase):
    def test_wireless_modes_preserve_faults_and_normal_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "wireless_status_led_test"
            command = [
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(REPO / "firmware/src"),
                str(REPO / "tools/firmware/tests/wireless_status_led_test.c"),
                str(REPO / "firmware/src/wireless_status_led.c"),
                str(REPO / "firmware/src/led_controller.c"),
                str(REPO / "firmware/src/dimmer_config.c"),
                "-o", str(executable),
            ]
            built = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            executed = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)


if __name__ == "__main__":
    unittest.main()


def test_pairing_has_one_deadline_and_three_second_success(tmp_path):
    source = tmp_path / 'pairing.c'
    source.write_text(r'''
#include <assert.h>
#include "connection_pairing.h"
int main(void) {
 struct connection_pairing p={0};
 connection_pairing_start(&p,100);
 assert(!connection_pairing_tick(&p,120099));
 assert(connection_pairing_tick(&p,120100));
 assert(!connection_pairing_tick(&p,120101));
 assert(!connection_pairing_joined(&p,120102));
 connection_pairing_start(&p,200000);
 assert(!connection_pairing_joined(&p,320000));
 assert(connection_pairing_tick(&p,320000));
 connection_pairing_start(&p,400000);
 assert(connection_pairing_joined(&p,519999));
 assert(connection_pairing_mode(&p)==WIRELESS_STATUS_LED_PAIRED);
 assert(!connection_pairing_tick(&p,522998));
 assert(connection_pairing_mode(&p)==WIRELESS_STATUS_LED_PAIRED);
 assert(!connection_pairing_tick(&p,522999));
 assert(connection_pairing_mode(&p)==WIRELESS_STATUS_LED_NORMAL);
 assert(!connection_pairing_joined(&p,523000));
 return 0;
}
''')
    executable=tmp_path/'pairing'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-I',str(REPO/'firmware/src'),str(source),str(REPO/'firmware/src/connection_pairing.c'),
        '-o',str(executable)],check=True,capture_output=True)
    subprocess.run([str(executable)],check=True)
