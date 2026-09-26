import csv
import unittest

from pi_energy_import.cli import (
    build_monthly_electricity_panel,
    build_monthly_gas_panel,
    build_water_charge_panel,
)


class DashboardPanelTests(unittest.TestCase):
    def test_monthly_electricity_uses_all_electric_rows_and_only_electric_rows(self) -> None:
        panel = build_monthly_electricity_panel([
            {"kind": "電気", "display_month": "2022-01-01", "status": "表示実績", "usage": "120"},
            {"kind": "電気", "display_month": "2026-09-01", "status": "予測", "usage": "130"},
            {"kind": "ガス", "display_month": "2026-09-01", "status": "表示実績", "usage": "9"},
        ])

        rows = list(csv.DictReader(panel["targets"][0]["csvContent"].splitlines()))
        self.assertEqual(panel["id"], 3)
        self.assertEqual(panel["fieldConfig"]["defaults"]["unit"], "kWh")
        self.assertEqual(panel["fieldConfig"]["defaults"]["custom"]["barWidthFactor"], 0.2)
        self.assertEqual(rows, [
            {"Time": "2022-01-01", "actual": "120", "in_progress": "", "forecast": ""},
            {"Time": "2026-09-01", "actual": "", "in_progress": "", "forecast": "130"},
        ])

    def test_monthly_gas_is_independent_from_electricity(self) -> None:
        panel = build_monthly_gas_panel([
            {"kind": "電気", "display_month": "2026-09-01", "status": "表示実績", "usage": "130"},
            {"kind": "ガス", "display_month": "2026-09-01", "status": "集計途中", "usage": "11"},
        ])

        rows = list(csv.DictReader(panel["targets"][0]["csvContent"].splitlines()))
        self.assertEqual(panel["id"], 4)
        self.assertEqual(panel["fieldConfig"]["defaults"]["unit"], "m3")
        self.assertEqual(rows, [
            {"Time": "2026-09-01", "actual": "", "in_progress": "11", "forecast": ""},
        ])

    def test_water_charges_are_stacked_without_total_value_label(self) -> None:
        panel = build_water_charge_panel([
            {"billing_months": "2025-10 ～ 2025-11", "water_fee_yen": "4000", "sewer_fee_yen": "2000"},
        ])

        self.assertEqual(panel["options"]["stacking"], "normal")
        self.assertEqual(panel["options"]["showValue"], "never")
        self.assertNotIn("total_fee_yen", panel["targets"][0]["csvContent"])


if __name__ == "__main__":
    unittest.main()
