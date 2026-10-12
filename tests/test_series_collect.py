"""scripts/ecos_series_collect.py 단위·통합 테스트 (네트워크 없음, fixture 전용)."""

from __future__ import annotations

import csv
import shutil
import unittest
from datetime import datetime
from pathlib import Path

import requests

from tests._support import (API_KEY, EXISTING_OUTPUTS, FIXED_TODAY, FIXTURES, FakeEcos,
                            FakeResponse, load_fixture, make_root, registry_dataset, sha256,
                            synth_rows)

import ecos_series_collect as c  # noqa: E402
import validate_series  # noqa: E402

NOW = datetime(2026, 10, 12, 6, 30, tzinfo=c._KST)


def run(root: Path, fake, *args: str, now: datetime = NOW, key: str = API_KEY):
    logs: list[str] = []
    sleeps: list[float] = []
    code = c.run(list(args), root=root, http_get=fake, sleep=sleeps.append, now=now,
                 api_key=key, log=logs.append)
    return code, logs, sleeps


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class DateConversionTest(unittest.TestCase):
    CASES = [
        ("D", "20260930", "2026-09-30"),
        ("D", "20240229", "2024-02-29"),
        ("M", "202609", "2026-09-01"),
        ("Q", "2026Q1", "2026-01-01"),
        ("Q", "2026Q3", "2026-07-01"),
        ("Q", "2025Q4", "2025-10-01"),
        ("A", "2026", "2026-01-01"),
    ]

    def test_round_trip(self):
        for cycle, raw, iso in self.CASES:
            with self.subTest(cycle=cycle, raw=raw):
                self.assertEqual(c.time_to_iso(raw, cycle), iso)
                self.assertEqual(c.iso_to_time(iso, cycle), raw)

    def test_wrong_format_for_cycle_raises(self):
        for cycle, raw in [("M", "20260930"), ("Q", "2026Q5"), ("D", "202609"), ("A", "2026Q1")]:
            with self.subTest(cycle=cycle, raw=raw):
                with self.assertRaises(ValueError):
                    c.time_to_iso(raw, cycle)

    def test_shift_and_range(self):
        self.assertEqual(c.shift_periods("2026-01-01", "M", -6), "2025-07-01")
        self.assertEqual(c.shift_periods("2026-07-01", "Q", -8), "2024-07-01")
        self.assertEqual(c.query_range("D", None, FIXED_TODAY, False), ("19900101", "20261011"))
        self.assertEqual(c.query_range("Q", "2026-04-01", FIXED_TODAY, False), ("2024Q2", "2026Q4"))
        self.assertEqual(c.query_range("M", "2026-08-01", FIXED_TODAY, True), ("196001", "202610"))


class ResultCodeTest(unittest.TestCase):
    """HTTP 200 이어도 본문 RESULT.CODE 로 판정한다."""

    def test_info200_is_no_data(self):
        with self.assertRaises(c.EcosError) as cm:
            c.parse_body(load_fixture("ecos_info200.json"))
        self.assertEqual((cm.exception.category, cm.exception.code), ("NO_DATA", "INFO-200"))

    def test_auth_error(self):
        with self.assertRaises(c.EcosError) as cm:
            c.parse_body(load_fixture("ecos_auth_error.json"))
        self.assertEqual((cm.exception.category, cm.exception.code), ("AUTH_ERROR", "INFO-100"))

    def test_rate_limit_retried_with_backoff_then_raised(self):
        fake = FakeEcos(overrides={("731Y001", "D", "0000001"): load_fixture("ecos_rate_limit.json")})
        sleeps: list[float] = []
        with self.assertRaises(c.EcosError) as cm:
            c.fetch_rows("731Y001", "D", "0000001", "20260901", "20260930", api_key=API_KEY,
                         http_get=fake, sleep=sleeps.append, log=lambda m: None)
        self.assertEqual(cm.exception.category, "RATE_LIMIT")
        self.assertEqual(len(fake.calls), c.MAX_ATTEMPTS)
        self.assertEqual(sleeps, [2.0, 4.0, 8.0])

    def test_no_data_and_auth_not_retried(self):
        for fx in ("ecos_info200.json", "ecos_auth_error.json"):
            fake = FakeEcos(overrides={("X", "M", "1"): load_fixture(fx)})
            with self.subTest(fx=fx), self.assertRaises(c.EcosError):
                c.fetch_rows("X", "M", "1", "202601", "202609", api_key=API_KEY,
                             http_get=fake, sleep=lambda s: None, log=lambda m: None)
            self.assertEqual(len(fake.calls), 1)

    def test_http_5xx_is_transient_and_recovers(self):
        rows = synth_rows("X", "M", "1")
        state = {"n": 0}

        def flaky(url):
            state["n"] += 1
            if state["n"] == 1:
                return FakeResponse({}, status_code=503)
            return FakeEcos({("X", "M", "1"): rows})(url)

        fake = FakeEcos(overrides={("X", "M", "1"): flaky})
        got = c.fetch_rows("X", "M", "1", "202001", "202609", api_key=API_KEY,
                           http_get=fake, sleep=lambda s: None, log=lambda m: None)
        self.assertTrue(got)


class PagingTest(unittest.TestCase):
    def test_pages_merged_by_list_total_count(self):
        rows = synth_rows("802Y001", "D", "0001000")  # ~460 영업일
        fake = FakeEcos({("802Y001", "D", "0001000"): rows})
        got = c.fetch_rows("802Y001", "D", "0001000", "19900101", "20261011", api_key=API_KEY,
                           http_get=fake, sleep=lambda s: None, page_size=100,
                           log=lambda m: None)
        self.assertEqual(len(fake.calls), -(-len(rows) // 100))
        self.assertEqual([r["TIME"] for r in got], [r["TIME"] for r in rows])
        self.assertIn("/1/100/", fake.calls[0])
        self.assertIn("/101/200/", fake.calls[1])

    def test_same_url_path_as_ecos_fetch(self):
        url = c.build_url("KEY", 1, 200, "721Y001", "M", "202201", "202610", "5020000")
        self.assertEqual(url, f"{c.ecos_fetch.BASE_URL}/KEY/json/kr/1/200/721Y001/M/202201/202610/5020000")


class MaskingTest(unittest.TestCase):
    def test_mask_secret(self):
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/{API_KEY}/json/kr/1/10/X/M/1/2"
        self.assertNotIn(API_KEY, c.mask_secret(url, API_KEY))
        self.assertNotIn(API_KEY, c.mask_secret(url, None))  # 키를 몰라도 경로 세그먼트로 가림
        self.assertIn("StatisticSearch/***/json", c.mask_secret(url))

    def test_key_never_reaches_logs_or_files(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root)

        def boom(url, timeout=0):
            raise requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")

        def http_error(url, timeout=0):
            raise RuntimeError(f"404 Client Error: Not Found for url: {url}")

        for fake in (boom, http_error):
            code, logs, _ = run(root, fake, "--series", "KOSPI", "--no-kosis")
            self.assertEqual(code, 1)
            self.assertTrue(any("StatisticSearch/***/" in line for line in logs))
            self.assertFalse(any(API_KEY in line for line in logs))
        for p in (root / "data").rglob("*"):
            if p.is_file():
                self.assertNotIn(API_KEY, p.read_text(encoding="utf-8", errors="ignore"), p)
        self.assertEqual(validate_series.validate(root), [])


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root)
        self.data = registry_dataset()
        self.fake = FakeEcos(self.data)

    def test_full_run_writes_schema_and_leaves_existing_outputs_untouched(self):
        before = {rel: sha256(self.root / rel) for rel in EXISTING_OUTPUTS}
        code, logs, _ = run(self.root, self.fake)
        self.assertEqual(code, 0, "\n".join(logs))
        after = {rel: sha256(self.root / rel) for rel in EXISTING_OUTPUTS}
        self.assertEqual(before, after)

        meta = read_csv(self.root / "data/series/ecos_meta.csv")
        self.assertEqual(list(meta[0].keys()), c.META_COLUMNS)
        ids = {m["series_id"] for m in meta}
        self.assertNotIn("CD_BOK_SPREAD", ids)       # 파생 스프레드는 저장 안 함
        self.assertNotIn("USD_KRW_DAILY", ids)       # UNVERIFIED 후보는 수집 안 함
        self.assertIn("USD_KRW", ids)
        usd = next(m for m in meta if m["series_id"] == "USD_KRW")
        self.assertEqual(usd["unit"], "원")          # UNIT_NAME 그대로
        self.assertEqual(usd["item_code1"], "0000001/0000100")
        self.assertEqual(usd["source_kind"], "ECOS")
        kospi = next(m for m in meta if m["series_id"] == "KOSPI")
        self.assertEqual(kospi["observation_end"], "2026-10-09")
        self.assertEqual(kospi["publication_lag_days"], "3")
        gdp = next(m for m in meta if m["series_id"] == "GDP_GROWTH_YOY")
        self.assertEqual(gdp["series_type"], "RAW;calc=yoy_pct")
        self.assertEqual(gdp["observation_end"], "2026-04-01")

        hist = read_csv(self.root / "data/series/ecos/CPI_YOY.csv")
        src = self.data[("901Y009", "M", "0")]
        self.assertEqual(len(hist), len(src))
        self.assertEqual(hist[-1], {"date": "2026-08-01", "value": src[-1]["DATA_VALUE"]})
        self.assertEqual(validate_series.validate(self.root), [])

    def test_idempotent(self):
        run(self.root, self.fake)
        snap = {p: p.read_bytes() for p in (self.root / "data/series/ecos").glob("*.csv")}
        code, _, _ = run(self.root, self.fake)
        self.assertEqual(code, 0)
        self.assertEqual(snap, {p: p.read_bytes() for p in (self.root / "data/series/ecos").glob("*.csv")})
        self.assertFalse((self.root / "data/series/_revisions.csv").exists())
        log = read_csv(self.root / "data/series/_collect_log.csv")
        second = [r for r in log if r["series_id"] == "CPI_YOY"][-1]
        self.assertEqual((second["rows_added"], second["rows_revised"], second["status"]), ("0", "0", "OK"))

    def test_incremental_requests_only_recent_window(self):
        run(self.root, self.fake, "--series", "CPI_YOY")
        self.fake.calls.clear()
        run(self.root, self.fake, "--series", "CPI_YOY")
        self.assertEqual(len(self.fake.calls), 1)
        self.assertIn("/901Y009/M/202602/202610/0", self.fake.calls[0])  # 2026-08 - 6개월

    def test_revision_detected_and_logged(self):
        run(self.root, self.fake, "--series", "CPI_YOY")
        rows = self.data[("901Y009", "M", "0")]
        old = rows[-2]["DATA_VALUE"]
        rows[-2] = dict(rows[-2], DATA_VALUE="999.9")
        code, _, _ = run(self.root, self.fake, "--series", "CPI_YOY")
        self.assertEqual(code, 0)
        revs = read_csv(self.root / "data/series/_revisions.csv")
        self.assertEqual(revs, [{"series_id": "CPI_YOY", "date": "2026-07-01", "old_value": old,
                                 "new_value": "999.9", "detected_at": "2026-10-12T06:30:00+0900"}])
        hist = {r["date"]: r["value"] for r in read_csv(self.root / "data/series/ecos/CPI_YOY.csv")}
        self.assertEqual(hist["2026-07-01"], "999.9")

    def test_numeric_equal_strings_not_revision(self):
        run(self.root, self.fake, "--series", "CPI_YOY")
        rows = self.data[("901Y009", "M", "0")]
        rows[-1] = dict(rows[-1], DATA_VALUE=rows[-1]["DATA_VALUE"] + "0")
        run(self.root, self.fake, "--series", "CPI_YOY")
        self.assertFalse((self.root / "data/series/_revisions.csv").exists())

    def test_missing_preserved(self):
        run(self.root, self.fake, "--series", "CPI_YOY")
        rows = self.data[("901Y009", "M", "0")]
        kept = rows[-1]["DATA_VALUE"]
        rows[-1] = dict(rows[-1], DATA_VALUE="-")             # 응답 값 결측
        del rows[-3]                                         # 응답에서 관측 누락
        rows.append(dict(rows[-1], TIME="202609", DATA_VALUE=""))  # 새 결측 관측
        run(self.root, self.fake, "--series", "CPI_YOY")
        hist = {r["date"]: r["value"] for r in read_csv(self.root / "data/series/ecos/CPI_YOY.csv")}
        self.assertEqual(hist["2026-08-01"], kept)
        self.assertIn("2026-06-01", hist)
        self.assertEqual(hist["2026-09-01"], "")              # 빈 값 그대로, 메우지 않음
        meta = {m["series_id"]: m for m in read_csv(self.root / "data/series/ecos_meta.csv")}
        self.assertEqual(meta["CPI_YOY"]["observation_end"], "2026-08-01")
        self.assertEqual(validate_series.validate(self.root), [])

    def test_rebase_triggers_full_refetch(self):
        run(self.root, self.fake, "--series", "CPI_YOY")
        rows = self.data[("901Y009", "M", "0")]
        for i, r in enumerate(rows):
            rows[i] = dict(r, DATA_VALUE=str(round(float(r["DATA_VALUE"]) * 0.9, 3)))
        self.fake.calls.clear()
        run(self.root, self.fake, "--series", "CPI_YOY")
        self.assertTrue(any("/196001/" in u for u in self.fake.calls))
        hist = read_csv(self.root / "data/series/ecos/CPI_YOY.csv")
        self.assertEqual(hist[0]["value"], rows[0]["DATA_VALUE"])

    def test_ambiguous_item_fails_instead_of_picking(self):
        rows = synth_rows("731Y004", "M", "0000001/0000100")
        dup = [dict(r, DATA_VALUE="1.0") for r in rows]
        self.fake.data[("731Y004", "M", "0000001/0000100")] = sorted(rows + dup, key=lambda r: r["TIME"])
        code, _, _ = run(self.root, self.fake, "--series", "USD_KRW")
        self.assertEqual(code, 1)
        self.assertFalse((self.root / "data/series/ecos/USD_KRW.csv").exists())
        log = read_csv(self.root / "data/series/_collect_log.csv")
        self.assertEqual(log[-1]["status"], "AMBIGUOUS_ITEM")

    def test_failure_isolated(self):
        self.fake.overrides[("901Y009", "M", "0")] = load_fixture("ecos_info200.json")
        code, logs, _ = run(self.root, self.fake, "--series", "CPI_YOY", "PPI_YOY")
        self.assertEqual(code, 1)
        self.assertTrue((self.root / "data/series/ecos/PPI_YOY.csv").exists())
        self.assertIn("| CPI_YOY | NO_DATA |", "\n".join(logs))

    def test_auth_error_aborts_with_exit_2(self):
        self.fake.overrides[("722Y001", "M", "0101000")] = load_fixture("ecos_auth_error.json")
        code, _, _ = run(self.root, self.fake)
        self.assertEqual(code, 2)
        self.assertEqual(len(self.fake.calls), 1)

    def test_missing_key_exit_2_and_no_writes(self):
        code, _, _ = run(self.root, self.fake, key="")
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "data/series").exists())


class RegistryAndCandidateTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root)
        self.data = registry_dataset()
        self.fake = FakeEcos(self.data)

    def _add_invalid(self, key, stat, item):
        with (self.root / "data/ecos_invalid_codes.csv").open("a", encoding="utf-8") as f:
            f.write(f"{key},{stat},{item},INFO-200,2026-10-12,test\n")

    def test_invalid_registry_excludes_series(self):
        self._add_invalid("KOSDAQ", "802Y001", "0089000")
        run(self.root, self.fake)
        self.assertFalse((self.root / "data/series/ecos/KOSDAQ.csv").exists())
        self.assertFalse(any("/0089000" in u for u in self.fake.calls))
        self.assertTrue((self.root / "data/series/ecos/KOSPI.csv").exists())

    def test_repo_invalid_registry_has_removed_v36_codes(self):
        keys, combos = c.load_invalid_registry(c.Paths(c.ROOT))
        self.assertEqual(len(keys), 12)
        self.assertIn(("901Y054", "AB"), combos)
        current = {s.series_id for s in c.series_from_registry()}
        self.assertFalse(keys & current)

    def test_probe_confirms_only_with_rows_and_matching_name(self):
        fx = synth_rows("731Y001", "D", "0000001", "원", "원/미국달러(매매기준율)")
        self.fake.data[("731Y001", "D", "0000001")] = fx
        self.fake.data[("817Y002", "D", "010200000")] = synth_rows(
            "817Y002", "D", "010200000", "연%", "국고채(10년)")          # 이름 불일치
        # 817Y002/010210000 · 010502000 · 722Y001/D 는 데이터 없음 -> INFO-200
        code, logs, _ = run(self.root, self.fake, "--probe", "--series", "USD_KRW_DAILY")
        self.assertEqual(code, 0, "\n".join(logs))
        cands = {r["series_id"]: r for r in read_csv(self.root / "data/series/ecos_candidates.csv")}
        self.assertEqual(cands["USD_KRW_DAILY"]["status"], "CONFIRMED")
        self.assertEqual(cands["GOV_BOND_3Y_DAILY"]["status"], "NAME_MISMATCH")
        self.assertEqual(cands["CD_91D_DAILY"]["status"], "NO_DATA")
        self.assertEqual(cands["CD_91D_DAILY"]["result_code"], "INFO-200")
        hist = read_csv(self.root / "data/series/ecos/USD_KRW_DAILY.csv")
        self.assertEqual(len(hist), len(fx))
        # 기존 월평균 USD_KRW 는 별도 파일 — 이번 실행에서 건드리지 않음
        self.assertFalse((self.root / "data/series/ecos/USD_KRW.csv").exists())

    def test_probe_auth_error_recorded(self):
        for k in [("731Y001", "D", "0000001")]:
            self.fake.overrides[k] = load_fixture("ecos_auth_error.json")
        code, _, _ = run(self.root, self.fake, "--probe")
        self.assertEqual(code, 2)
        cands = {r["series_id"]: r for r in read_csv(self.root / "data/series/ecos_candidates.csv")}
        self.assertEqual(cands["USD_KRW_DAILY"]["status"], "AUTH_ERROR")
        self.assertEqual(cands["GOV_BOND_3Y_DAILY"]["status"], "UNVERIFIED")

    def test_invalid_candidate_not_probed(self):
        self._add_invalid("USD_KRW_DAILY", "731Y001", "0000001")
        run(self.root, self.fake, "--probe", "--series", "NONE")
        self.assertFalse(any("/731Y001/" in u for u in self.fake.calls))

    def test_candidate_without_probe_not_collected(self):
        self.fake.data[("731Y001", "D", "0000001")] = synth_rows("731Y001", "D", "0000001")
        run(self.root, self.fake)
        self.assertFalse(any("/731Y001/" in u for u in self.fake.calls))


class KosisCopyTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root)
        self.fake = FakeEcos(registry_dataset())

    def test_empty_kosis_not_filled_with_ecos(self):
        # 저장소 현재 kosis_latest.csv 는 헤더만 있음(그날 KOSIS 전량 실패)
        (self.root / "data/kosis_latest.csv").write_text(
            "﻿series_id,label,value,date,unit,stat_code,period,chg_prev,chg_mid,chg_yoy,note\n",
            encoding="utf-8")
        code, _, _ = run(self.root, self.fake)
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "data/series/ecos/CPI_YOY.csv").exists())
        self.assertFalse((self.root / "data/series/kosis").exists())
        meta = read_csv(self.root / "data/series/ecos_meta.csv")
        self.assertFalse([m for m in meta if m["source_kind"] == "KOSIS_COPY"])

    def test_copy_as_is_and_missing_rows_skipped(self):
        shutil.copy(FIXTURES / "kosis_latest_partial.csv", self.root / "data/kosis_latest.csv")
        code, _, _ = run(self.root, self.fake)
        self.assertEqual(code, 0)
        kdir = self.root / "data/series/kosis"
        self.assertEqual(sorted(p.stem for p in kdir.glob("*.csv")),
                         ["KOSIS_CLI_LEADING", "KOSIS_CPI_YOY"])
        self.assertEqual(read_csv(kdir / "KOSIS_CPI_YOY.csv"), [{"date": "2026-09-01", "value": "2.88"}])
        meta = {m["series_id"]: m for m in read_csv(self.root / "data/series/ecos_meta.csv")}
        self.assertEqual(meta["KOSIS_CPI_YOY"]["source_kind"], "KOSIS_COPY")
        self.assertEqual(meta["KOSIS_CPI_YOY"]["unit"], "%")
        self.assertNotIn("KOSIS_UNEMP_RATE", meta)
        log = read_csv(self.root / "data/series/_collect_log.csv")
        self.assertIn({"run_at": "2026-10-12T06:30:00+0900", "series_id": "KOSIS_UNEMP_RATE",
                       "rows_added": "0", "rows_revised": "0", "status": "KOSIS_MISSING",
                       "error": ""}, log)
        self.assertEqual(validate_series.validate(self.root), [])

    def test_kosis_failure_day_keeps_previous_rows(self):
        shutil.copy(FIXTURES / "kosis_latest_partial.csv", self.root / "data/kosis_latest.csv")
        run(self.root, self.fake)
        (self.root / "data/kosis_latest.csv").write_text(
            "series_id,label,value,date,unit,stat_code,period,chg_prev,chg_mid,chg_yoy,note\n",
            encoding="utf-8")
        run(self.root, self.fake, now=datetime(2026, 10, 13, 6, 30, tzinfo=c._KST))
        kdir = self.root / "data/series/kosis"
        self.assertEqual(read_csv(kdir / "KOSIS_CPI_YOY.csv"), [{"date": "2026-09-01", "value": "2.88"}])
        meta = {m["series_id"]: m for m in read_csv(self.root / "data/series/ecos_meta.csv")}
        self.assertEqual(meta["KOSIS_CPI_YOY"]["probed_at"], "2026-10-12T06:30:00+0900")


class ValidateSeriesTest(unittest.TestCase):
    def test_detects_violations(self):
        root = make_root()
        self.addCleanup(shutil.rmtree, root)
        run(root, FakeEcos(registry_dataset()), "--series", "CPI_YOY", "--no-kosis")
        p = root / "data/series/ecos/CPI_YOY.csv"
        p.write_text(p.read_text(encoding="utf-8") + "2026-08-15,1.0\n2026-09-01,abc\n", encoding="utf-8")
        (root / "data/series/ecos/KOSDAQ_X.csv").write_text(
            f"date,value\n2026-01-01,1\n# StatisticSearch/{API_KEY}/json\n", encoding="utf-8")
        errs = "\n".join(validate_series.validate(root))
        self.assertIn("주기 M 날짜 규약 위반 2026-08-15", errs)
        self.assertIn("숫자 아님 'abc'", errs)
        self.assertIn("KOSDAQ_X.csv: ecos_meta.csv 에 메타 없음", errs)
        self.assertIn("API 키 노출 의심", errs)


if __name__ == "__main__":
    unittest.main()
