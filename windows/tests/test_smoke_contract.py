from __future__ import annotations

from pathlib import Path
import sys
import unittest

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from presentation.app import scroll_contract_ready


class SmokeContractTests(unittest.TestCase):
    def test_overflow_requires_effective_wheel_scroll(self):
        self.assertTrue(scroll_contract_ready(True, True, [0.0, 0.5], [0.1, 0.6]))
        self.assertFalse(scroll_contract_ready(True, False, [0.0, 0.5], [0.0, 0.5]))

    def test_fully_visible_content_does_not_require_scroll(self):
        self.assertTrue(scroll_contract_ready(False, False, [0.0, 1.0], [0.0, 1.0]))
        self.assertFalse(scroll_contract_ready(False, False, [], []))


if __name__ == "__main__":
    unittest.main()
