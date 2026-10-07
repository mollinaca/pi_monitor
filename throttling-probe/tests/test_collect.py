import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("throttling_collect", Path(__file__).parents[1] / "collect.py")
assert SPEC and SPEC.loader
collect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect)


class ThrottlingProbeTests(unittest.TestCase):
    def test_current_and_latched_flags_are_separate(self):
        bits = collect.parse_throttled("throttled=0x50005\n")
        metrics = collect.render_metrics(bits, 123)
        self.assertIn('home_pi_throttling_state{condition="undervoltage",scope="current"} 1', metrics)
        self.assertIn('home_pi_throttling_state{condition="frequency_capped",scope="current"} 0', metrics)
        self.assertIn('home_pi_throttling_state{condition="throttled",scope="current"} 1', metrics)
        self.assertIn('home_pi_throttling_state{condition="undervoltage",scope="since_boot"} 1', metrics)
        self.assertIn('home_pi_throttling_state{condition="throttled",scope="since_boot"} 1', metrics)
        self.assertIn('home_pi_throttling_state{condition="soft_temperature_limit",scope="since_boot"} 0', metrics)

    def test_invalid_output_fails_without_stale_state(self):
        with self.assertRaises(ValueError):
            collect.parse_throttled("throttled=unknown")
        metrics = collect.render_metrics(None, 123)
        self.assertIn("home_pi_throttling_probe_success 0", metrics)
        self.assertNotIn('home_pi_throttling_state{', metrics)


if __name__ == "__main__":
    unittest.main()
