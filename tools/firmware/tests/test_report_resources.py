import unittest

from tools.firmware.report_resources import ResourceUsage, markdown_report


class ResourceReportTests(unittest.TestCase):
    def test_stable_markdown_contains_deltas_and_reserve(self):
        report = markdown_report(
            ResourceUsage(flash_used=387348, flash_capacity=466432,
                          ram_used=59956, ram_capacity=262144),
            flash_baseline=381808, ram_baseline=58804,
        )
        self.assertIn("| Flash | 387348 | 466432 | 79084 | 83.04% | +5540 | PASS |", report)
        self.assertIn("| RAM | 59956 | 262144 | 202188 | 22.87% | +1152 | PASS |", report)

    def test_exact_eighty_five_percent_passes(self):
        usage = ResourceUsage(85, 100, 85, 100)
        self.assertNotIn("FAIL", markdown_report(usage, 0, 0))

    def test_above_eighty_five_percent_fails(self):
        usage = ResourceUsage(86, 100, 1, 100)
        self.assertIn("| Flash | 86 | 100 | 14 | 86.00% | +86 | FAIL |", markdown_report(usage, 0, 0))


if __name__ == "__main__":
    unittest.main()
