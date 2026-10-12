"""회귀 계약: 기존 파이프라인 산출물 형식·내용이 이번 작업 전후로 동일함을 골든 파일로 고정.

- ecos_fetch.py 를 고정 날짜·합성 fixture 로 돌린 ecos_latest.csv / ecos_latest.md
- merge_macro.py 로 만든 macro_latest.csv
- ecos_fetch.SERIES / SERIES_NOTES 스냅샷

골든은 이번 변경 이전 코드(ecos_fetch.py·merge_macro.py 무수정)로 생성했다.
의도적으로 기존 파이프라인을 바꿀 때만 UPDATE_GOLDEN=1 로 재생성한다.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests._support import FIXED_TODAY, FIXTURES, GOLDEN, FakeEcos, registry_dataset

import ecos_fetch  # noqa: E402
import merge_macro  # noqa: E402

UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


class _FixedDate(_dt.date):
    @classmethod
    def today(cls):
        return cls(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day)


def _datetime_shim() -> types.ModuleType:
    shim = types.ModuleType("datetime")
    shim.__dict__.update({k: getattr(_dt, k) for k in dir(_dt) if not k.startswith("__")})
    shim.date = _FixedDate
    return shim


def _check(test: unittest.TestCase, produced: Path, golden_name: str) -> None:
    golden = GOLDEN / golden_name
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        shutil.copy(produced, golden)
    test.assertTrue(golden.exists(), f"골든 없음: {golden}")
    test.assertEqual(produced.read_bytes(), golden.read_bytes(), f"{golden_name} 골든 불일치")


class GoldenExistingOutputsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="golden_"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def _run_ecos_fetch(self) -> None:
        fake = FakeEcos(registry_dataset())
        with mock.patch.object(ecos_fetch, "DATA_DIR", self.tmp), \
                mock.patch.object(ecos_fetch, "HISTORY_DIR", self.tmp / "hist"), \
                mock.patch.object(ecos_fetch, "date", _FixedDate), \
                mock.patch.object(ecos_fetch.requests, "get", fake), \
                mock.patch.object(ecos_fetch.time, "sleep", lambda s: None), \
                mock.patch.dict(sys.modules, {"datetime": _datetime_shim()}), \
                mock.patch("builtins.print"):
            (self.tmp / "hist").mkdir()
            df = ecos_fetch.drop_failed(ecos_fetch.collect_all())
            ecos_fetch.save_csv(df, "GOLDEN")
            ecos_fetch.save_md(df, "2026-10-12 06:10:00")

    def test_ecos_fetch_outputs(self):
        self._run_ecos_fetch()
        _check(self, self.tmp / "ecos_latest.csv", "ecos_latest.csv")
        _check(self, self.tmp / "ecos_latest.md", "ecos_latest.md")

    def test_merge_macro_output(self):
        self._run_ecos_fetch()
        shutil.copy(FIXTURES / "kosis_latest_partial.csv", self.tmp / "kosis_latest.csv")
        with mock.patch.object(merge_macro, "ECOS_CSV", self.tmp / "ecos_latest.csv"), \
                mock.patch.object(merge_macro, "KOSIS_CSV", self.tmp / "kosis_latest.csv"), \
                mock.patch.object(merge_macro, "OUTPUT_CSV", self.tmp / "macro_latest.csv"), \
                mock.patch("builtins.print"):
            merge_macro.main()
        _check(self, self.tmp / "macro_latest.csv", "macro_latest.csv")

    def test_series_registry_snapshot(self):
        snap = self.tmp / "series_registry.json"
        snap.write_text(json.dumps({"SERIES": [list(s) for s in ecos_fetch.SERIES],
                                    "SERIES_NOTES": ecos_fetch.SERIES_NOTES},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        _check(self, snap, "series_registry.json")


if __name__ == "__main__":
    unittest.main()
