"""scripts/fx_cross_check.py — 리포트 수치만 검증 (네트워크 없음)."""

from __future__ import annotations

import unittest

from tests._support import FIXTURES

import fx_cross_check as fx  # noqa: E402


class FxCrossCheckTest(unittest.TestCase):
    def setUp(self):
        self.ecos = fx.load_series_csv((FIXTURES / "ecos_usd_krw_daily.csv").read_text(encoding="utf-8"))
        self.fred = fx.load_series_csv((FIXTURES / "fred_dexkous.csv").read_text(encoding="utf-8"))

    def test_fred_missing_marker_is_none(self):
        self.assertIsNone(self.fred["2026-09-03"])

    def test_stats(self):
        res = fx.compare(self.ecos, self.fred)
        # 겹침: 09-01(+0.9), 09-02(-1.0), 09-04(-1.5), 09-08(-1.2)
        self.assertEqual(res["overlap_days"], 4)
        self.assertEqual(res["missing_in_fred"], 2)   # 09-03('.'), 09-05
        self.assertEqual(res["missing_in_ecos"], 0)
        self.assertEqual(res["mean_diff"], -0.7)
        self.assertEqual(res["mean_abs_diff"], 1.15)
        self.assertEqual(res["max_abs_diff"], 1.5)
        self.assertEqual(res["max_abs_diff_date"], "2026-09-04")

    def test_since_filter_and_render(self):
        res = fx.compare(self.ecos, self.fred, since="2026-09-04")
        self.assertEqual(res["overlap_days"], 2)
        self.assertIn("최대 절대차", fx.render(res))

    def test_missing_ecos_file_exit_3(self):
        self.assertEqual(fx.main(["--ecos-csv", "/nonexistent.csv",
                                  "--fred-csv", str(FIXTURES / "fred_dexkous.csv")]), 3)


if __name__ == "__main__":
    unittest.main()
