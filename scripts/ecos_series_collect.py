"""
scripts/ecos_series_collect.py
ECOS 시리즈별 전체 이력을 data/series/ 에 누적 저장하는 수집기.

기존 산출물(data/ecos_latest.*, kosis_latest.*, macro_latest.csv, ecos_signals.md,
ecos_regime.md, kosis_status_log.csv)은 읽기만 하고(kosis_latest.csv) 절대 쓰지 않는다.

저장 위치 (스키마는 docs/SERIES_SCHEMA.md):
  data/series/ecos/{series_id}.csv   date,value  (ECOS 원자료 DATA_VALUE 그대로, 변환·환산 없음)
  data/series/kosis/{series_id}.csv  date,value  (kosis_latest.csv 값 그대로 복사, KOSIS_COPY)
  data/series/ecos_meta.csv          실측 메타
  data/series/ecos_candidates.csv    후보 코드 검증 상태 (CONFIRMED 만 수집)
  data/series/_revisions.csv         개정 감지 이력 (append)
  data/series/_collect_log.csv       실행 로그 (append)
  data/ecos_invalid_codes.csv        무효 코드 레지스트리 (읽기 전용 — 여기 있는 키는 수집·검증 제외)

시리즈 정의는 ecos_fetch.SERIES 를 import 해 재사용한다(복제 금지).
파생 스프레드(item_code SPREAD/CSPREAD)는 ECOS 원자료가 아니므로 저장 대상이 아니다.

후보 코드 검증 규칙 (docs/AUDIT_ecos.md 2절):
  - StatisticItemList 의 "항목 존재"만으로 CONFIRMED 처리하지 않는다.
  - ecos_fetch.py 와 동일한 StatisticSearch URL 경로로 실제 조회해 데이터 행이
    1개 이상 반환되고, ITEM_NAME 이 기대 키워드를 포함할 때만 CONFIRMED.
  - RESULT.CODE 를 해석해 데이터 없음(INFO-200)·인증 오류·호출 한도 초과를 구분 기록.

사용법:
  python scripts/ecos_series_collect.py            # 증분 수집 (+ KOSIS 복사)
  python scripts/ecos_series_collect.py --probe    # UNVERIFIED 후보 실조회 검증 후 수집
  python scripts/ecos_series_collect.py --full     # 전 구간 재조회 (기준연도 개편 등)
  python scripts/ecos_series_collect.py --series KOSPI CD_91D

종료코드: 0=전부 성공, 1=일부 시리즈 실패, 2=인증 오류 등으로 수집 중단.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ecos_fetch  # noqa: E402  (SERIES·BASE_URL 재사용 — 정의 복제 금지)

_KST = ZoneInfo("Asia/Seoul")

PAGE_SIZE = 1000
CALL_INTERVAL = 0.3
MAX_ATTEMPTS = 4          # 최초 1회 + 재시도 3회 (2s, 4s, 8s)
BACKOFF_BASE = 2.0

# 전 구간 조회 시작점. ECOS 는 데이터 시작 이전 구간을 요청하면 존재하는 구간만
# 돌려주는 것으로 알려져 있으나 실호출로 확인하지 못했다(docs/AUDIT_ecos.md).
DEFAULT_START = {"D": "19900101", "M": "196001", "Q": "1960Q1", "A": "1960"}

# 증분 수집 시 저장된 max(date) 에서 거슬러 재조회하는 기간 수 (개정 흡수용).
# 근거는 docs/AUDIT_ecos.md 5절.
REVISION_WINDOW = {"D": 10, "M": 6, "Q": 8, "A": 3}

# 재조회 구간의 기존 관측 중 이 비율 이상이 바뀌면 기준연도 개편 등 전면 개정으로
# 보고 해당 시리즈만 전 구간을 다시 받는다.
REBASE_RATIO = 0.5
REBASE_MIN_ROWS = 3

MISSING_TOKENS = (None, "", " ", "-")

# 일별 후보 (전부 UNVERIFIED 로 시작 — data/series/ecos_candidates.csv 가 상태의 정본).
# 코드값은 ECOS 공개 문서 기억에 근거한 추정이며 실호출 검증 전에는 수집하지 않는다.
DEFAULT_CANDIDATES = [
    # series_id,           stat_code, cycle, item_code,  expect (ITEM_NAME 포함 키워드, | 는 AND)
    ("USD_KRW_DAILY",       "731Y001", "D", "0000001",   "미국달러",
     "원/미국달러 매매기준율(일별). 기존 USD_KRW(731Y004 월평균)와 별개 계열 — 병합·대체 금지"),
    ("GOV_BOND_3Y_DAILY",   "817Y002", "D", "010200000", "국고채|3년",
     "국고채 3년 일별(시장금리 일별). 기존 GOV_BOND_3Y(721Y001 월) 와 별개"),
    ("GOV_BOND_10Y_DAILY",  "817Y002", "D", "010210000", "국고채|10년",
     "국고채 10년 일별. 기존 GOV_BOND_10Y(721Y001 월) 와 별개"),
    ("CD_91D_DAILY",        "817Y002", "D", "010502000", "CD|91",
     "CD 91일 일별. 기존 CD_91D(721Y001 월) 와 별개"),
    ("BOK_BASE_RATE_DAILY", "722Y001", "D", "0101000",   "기준금리",
     "기준금리 일별. 기존 BOK_BASE_RATE(722Y001 월) 와 별개"),
]

# ECOS RESULT.CODE 분류. 코드표는 ECOS 개발가이드 기준(docs/AUDIT_ecos.md 2절).
CODE_CATEGORY = {
    "INFO-100": "AUTH_ERROR",      # 인증키가 유효하지 않음
    "INFO-200": "NO_DATA",         # 해당하는 데이터가 없음
    "ERROR-100": "REQUEST_ERROR",  # 필수 값 누락
    "ERROR-101": "REQUEST_ERROR",  # 주기와 다른 형식의 날짜
    "ERROR-200": "REQUEST_ERROR",  # 파일타입 값 누락/오류
    "ERROR-300": "REQUEST_ERROR",  # 조회건수 값 누락
    "ERROR-301": "REQUEST_ERROR",  # 조회건수 값 타입 오류
    "ERROR-400": "TRANSIENT",      # 검색범위 초과로 60초 TIMEOUT
    "ERROR-500": "TRANSIENT",      # 서버 오류
    "ERROR-600": "TRANSIENT",      # DB Connection 오류
    "ERROR-601": "TRANSIENT",      # SQL 오류
    "ERROR-602": "RATE_LIMIT",     # 과도한 OpenAPI 호출로 이용 제한
}
RETRYABLE = {"TRANSIENT", "RATE_LIMIT", "NETWORK"}
# --probe 가 다시 조회하는 후보 상태. NO_DATA·NAME_MISMATCH 는 사람이 코드를 재탐색해야
# 하므로 자동 재조회하지 않는다 (CONFIRMED 는 이미 수집 대상).
REPROBE_STATUSES = {"", "UNVERIFIED", "ERROR", "RATE_LIMIT", "AUTH_ERROR"}

META_COLUMNS = [
    "series_id", "stat_code", "item_code1", "cycle", "unit", "series_type",
    "seasonal_adj", "observation_start", "observation_end", "publication_lag_days",
    "source_kind", "probed_at",
]
CANDIDATE_COLUMNS = [
    "series_id", "stat_code", "item_code1", "cycle", "expect_name", "status",
    "result_code", "rows_returned", "item_name", "probed_at", "note",
]
INVALID_COLUMNS = ["key", "stat_code", "item_code", "error", "verified_at", "note"]
LOG_COLUMNS = ["run_at", "series_id", "rows_added", "rows_revised", "status", "error"]
REVISION_COLUMNS = ["series_id", "date", "old_value", "new_value", "detected_at"]


# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
@dataclass
class Paths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def series(self) -> Path:
        return self.data / "series"

    @property
    def ecos(self) -> Path:
        return self.series / "ecos"

    @property
    def kosis(self) -> Path:
        return self.series / "kosis"

    @property
    def meta(self) -> Path:
        return self.series / "ecos_meta.csv"

    @property
    def candidates(self) -> Path:
        return self.series / "ecos_candidates.csv"

    @property
    def revisions(self) -> Path:
        return self.series / "_revisions.csv"

    @property
    def collect_log(self) -> Path:
        return self.series / "_collect_log.csv"

    @property
    def invalid(self) -> Path:
        return self.data / "ecos_invalid_codes.csv"

    @property
    def kosis_latest(self) -> Path:
        return self.data / "kosis_latest.csv"


# ---------------------------------------------------------------------------
# 키 마스킹
# ---------------------------------------------------------------------------
_KEY_IN_PATH = re.compile(
    r"(Statistic(?:Search|ItemList|TableList|Word|Meta)|KeyStatisticList)/[^/\s?]+/"
)


def mask_secret(text: object, api_key: str | None = None) -> str:
    """로그·예외·파일에 쓰기 전 API 키를 가린다. ECOS 키는 URL 경로 세그먼트로 들어간다."""
    s = str(text)
    if api_key and len(api_key) >= 4:
        s = s.replace(api_key, "***")
    return _KEY_IN_PATH.sub(r"\1/***/", s)


# ---------------------------------------------------------------------------
# 주기별 날짜 변환 (D=YYYYMMDD, M=YYYYMM, Q=YYYYQn, A=YYYY  <->  ISO)
# ---------------------------------------------------------------------------
def time_to_iso(raw: str, cycle: str) -> str:
    raw = str(raw).strip()
    if cycle == "D" and re.fullmatch(r"\d{8}", raw):
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
    if cycle == "M" and re.fullmatch(r"\d{6}", raw):
        return date(int(raw[:4]), int(raw[4:6]), 1).isoformat()
    m = re.fullmatch(r"(\d{4})Q([1-4])", raw)
    if cycle == "Q" and m:
        return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1).isoformat()
    if cycle == "A" and re.fullmatch(r"\d{4}", raw):
        return date(int(raw), 1, 1).isoformat()
    raise ValueError(f"주기 {cycle} 에 맞지 않는 TIME 값: {raw!r}")


def iso_to_time(iso: str, cycle: str) -> str:
    d = date.fromisoformat(iso)
    if cycle == "D":
        return d.strftime("%Y%m%d")
    if cycle == "M":
        return d.strftime("%Y%m")
    if cycle == "Q":
        return f"{d.year}Q{(d.month - 1) // 3 + 1}"
    if cycle == "A":
        return str(d.year)
    raise ValueError(f"지원하지 않는 주기: {cycle}")


def shift_periods(iso: str, cycle: str, n: int) -> str:
    """ISO 날짜를 주기 단위로 n 기간 이동 (음수=과거)."""
    d = date.fromisoformat(iso)
    if cycle == "D":
        return (d + timedelta(days=n)).isoformat()
    months = {"M": 1, "Q": 3, "A": 12}[cycle] * n
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1).isoformat()


def safe_end(cycle: str, today: date) -> str:
    """조회 종료 시점. 일별은 어제(ecos_fetch._date_range 와 동일 규칙)."""
    if cycle == "D":
        return (today - timedelta(days=1)).strftime("%Y%m%d")
    return iso_to_time(today.isoformat(), cycle)


def query_range(cycle: str, last_iso: str | None, today: date, full: bool) -> tuple[str, str]:
    end = safe_end(cycle, today)
    if full or not last_iso:
        return DEFAULT_START[cycle], end
    start_iso = shift_periods(last_iso, cycle, -REVISION_WINDOW[cycle])
    return iso_to_time(start_iso, cycle), end


# ---------------------------------------------------------------------------
# ECOS 호출
# ---------------------------------------------------------------------------
class EcosError(Exception):
    def __init__(self, category: str, code: str, message: str):
        super().__init__(f"[{category}] {code} {message}".strip())
        self.category = category
        self.code = code
        self.message = message


def classify_result(code: str) -> str:
    code = str(code or "").strip()
    return CODE_CATEGORY.get(code, "UNKNOWN_ERROR")


def build_url(api_key: str, start_row: int, end_row: int, stat_code: str,
              cycle: str, start: str, end: str, item_code: str) -> str:
    """ecos_fetch.fetch_series 와 동일한 StatisticSearch 경로 형식."""
    item_part = f"/{item_code}" if item_code else ""
    return (f"{ecos_fetch.BASE_URL}/{api_key}/json/kr/{start_row}/{end_row}"
            f"/{stat_code}/{cycle}/{start}/{end}{item_part}")


def parse_body(body: object) -> tuple[int, list[dict]]:
    """StatisticSearch 응답 본문 해석. HTTP 200 이어도 RESULT.CODE 로 오류를 판정한다."""
    if not isinstance(body, dict):
        raise EcosError("UNKNOWN_ERROR", "", "JSON 객체가 아닌 응답")
    if "RESULT" in body:
        res = body.get("RESULT") or {}
        code = str(res.get("CODE", ""))
        msg = str(res.get("MESSAGE", ""))
        cat = classify_result(code)
        if cat != "OK":
            raise EcosError(cat, code, msg)
    block = body.get("StatisticSearch")
    if not isinstance(block, dict):
        raise EcosError("UNKNOWN_ERROR", "", "응답에 StatisticSearch 키 없음")
    rows = block.get("row") or []
    try:
        total = int(block.get("list_total_count", len(rows)))
    except (TypeError, ValueError):
        total = len(rows)
    return total, rows


HttpGet = Callable[..., object]


def _request_json(url: str, http_get: HttpGet, api_key: str) -> object:
    try:
        resp = http_get(url, timeout=30)
        status = getattr(resp, "status_code", 200)
        if status == 429:
            raise EcosError("RATE_LIMIT", "HTTP-429", "Too Many Requests")
        if status >= 500:
            raise EcosError("TRANSIENT", f"HTTP-{status}", "server error")
        if status >= 400:
            raise EcosError("HTTP_ERROR", f"HTTP-{status}", "client error")
        return resp.json()
    except EcosError:
        raise
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise EcosError("NETWORK", "", mask_secret(exc, api_key)) from None
    except ValueError as exc:  # JSON 디코딩 실패
        raise EcosError("UNKNOWN_ERROR", "", mask_secret(f"JSON 파싱 실패: {exc}", api_key)) from None
    except Exception as exc:  # noqa: BLE001 — 키가 담긴 예외 메시지를 그대로 흘리지 않기 위함
        raise EcosError("UNKNOWN_ERROR", "", mask_secret(exc, api_key)) from None


def call_with_backoff(fn: Callable[[], object], sleep: Callable[[float], None],
                      log: Callable[[str], None] = print) -> object:
    """한도 초과·일시 오류·네트워크 오류만 지수 백오프로 재시도. 그 외는 즉시 전파."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except EcosError as exc:
            if exc.category not in RETRYABLE or attempt == MAX_ATTEMPTS:
                raise
            delay = BACKOFF_BASE ** attempt
            log(f"    [RETRY {attempt}/{MAX_ATTEMPTS - 1}] {exc} — {delay:.0f}s 후 재시도")
            sleep(delay)
    raise AssertionError("unreachable")


def fetch_rows(stat_code: str, cycle: str, item_code: str, start: str, end: str, *,
               api_key: str, http_get: HttpGet = requests.get,
               sleep: Callable[[float], None] = time.sleep,
               page_size: int = PAGE_SIZE, log: Callable[[str], None] = print) -> list[dict]:
    """list_total_count 기준으로 페이지를 나눠 전부 받아 병합한다."""
    rows: list[dict] = []
    start_row = 1
    total = None
    while True:
        end_row = start_row + page_size - 1
        url = build_url(api_key, start_row, end_row, stat_code, cycle, start, end, item_code)
        page_total, page_rows = call_with_backoff(
            lambda u=url: parse_body(_request_json(u, http_get, api_key)), sleep, log)
        total = page_total if total is None else total
        rows.extend(page_rows)
        if not page_rows or len(rows) >= total:
            break
        start_row = end_row + 1
        sleep(CALL_INTERVAL)
    return rows


def _is_future_error(exc: EcosError) -> bool:
    return "미래" in exc.message or "future" in exc.message.lower()


def fetch_range(stat_code: str, cycle: str, item_code: str, start: str, end: str,
                **kw) -> list[dict]:
    """종료 시점이 미래로 판정되면 한 기간씩 당겨 최대 3회 재시도 (ecos_fetch 와 같은 취지)."""
    for _ in range(4):
        try:
            return fetch_rows(stat_code, cycle, item_code, start, end, **kw)
        except EcosError as exc:
            if not _is_future_error(exc):
                raise
            end = iso_to_time(shift_periods(time_to_iso(end, cycle), cycle, -1), cycle)
    return fetch_rows(stat_code, cycle, item_code, start, end, **kw)


# ---------------------------------------------------------------------------
# 이력 파일 I/O · 병합
# ---------------------------------------------------------------------------
def normalize_value(v: object) -> str:
    if v in MISSING_TOKENS:
        return ""
    s = str(v).strip()
    return "" if s in ("", "-") else s


def values_equal(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return Decimal(a) == Decimal(b)
    except (InvalidOperation, ValueError):
        return False


def rows_to_series(rows: list[dict], cycle: str) -> dict[str, str]:
    """ECOS row -> {ISO date: value}. 같은 TIME 에 서로 다른 값이 오면(항목 코드가
    하위 차원을 다 고정하지 못한 경우) 임의 선택하지 않고 오류로 처리한다."""
    out: dict[str, str] = {}
    for r in rows:
        iso = time_to_iso(r.get("TIME", ""), cycle)
        val = normalize_value(r.get("DATA_VALUE"))
        if iso in out and not values_equal(out[iso], val):
            raise EcosError("AMBIGUOUS_ITEM", "",
                            f"{iso} 에 복수 값 반환 — item_code 하위 차원 미고정")
        out[iso] = val
    return out


def read_history(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r["date"]: r["value"] for r in csv.DictReader(f)}


def write_history(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "value"])
        for d in sorted(data):
            w.writerow([d, data[d]])


@dataclass
class MergeResult:
    merged: dict[str, str]
    added: int = 0
    revisions: list[tuple[str, str, str]] = field(default_factory=list)  # (date, old, new)
    overlap: int = 0


def merge_history(existing: dict[str, str], incoming: dict[str, str]) -> MergeResult:
    """기존 이력에 새 관측을 반영한다.
    - 새 날짜는 추가 (값이 비어 있으면 빈 값 그대로 — 결측을 메우지 않는다)
    - 같은 날짜의 값이 바뀌면 개정으로 기록 후 갱신
    - 응답에 빠졌거나 응답 값이 비어 있는 기존 관측은 보존 (삭제·덮어쓰기 없음)
    """
    merged = dict(existing)
    res = MergeResult(merged=merged)
    for d, new in incoming.items():
        if d not in existing:
            merged[d] = new
            res.added += 1
            continue
        old = existing[d]
        if old != "":
            res.overlap += 1
        if new == "" or values_equal(old, new):
            continue
        res.revisions.append((d, old, new))
        merged[d] = new
    return res


def append_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


# ---------------------------------------------------------------------------
# 메타
# ---------------------------------------------------------------------------
def detect_seasonal_adj(names: list[str]) -> str:
    """항목명/통계표명으로 판별 가능한 경우만 SA/NSA. 그 외 UNKNOWN."""
    text = " ".join(n for n in names if n)
    if "계절조정" in text:
        return "SA"
    if "원계열" in text or "원지수" in text:
        return "NSA"
    return "UNKNOWN"


def series_type_for(calc_type: str | None) -> str:
    return "RAW" if not calc_type else f"RAW;calc={calc_type}"


def build_meta_row(spec: "SeriesSpec", rows: list[dict], history: dict[str, str],
                   probed_at: str, today: date, prev: dict | None) -> tuple[dict, list[str]]:
    warns: list[str] = []
    last = rows[-1] if rows else {}
    unit = str(last.get("UNIT_NAME", "") or "").strip()
    if not unit:
        unit = (prev or {}).get("unit", "")
        warns.append(f"{spec.series_id}: 응답에 UNIT_NAME 없음 — 이전 메타 단위 유지({unit!r})")
    names = [str(last.get(k, "") or "") for k in
             ("STAT_NAME", "ITEM_NAME1", "ITEM_NAME2", "ITEM_NAME3", "ITEM_NAME4")]
    sa = detect_seasonal_adj(names) if rows else (prev or {}).get("seasonal_adj", "UNKNOWN")
    if sa == "UNKNOWN":
        warns.append(f"{spec.series_id}: 계절조정 여부를 항목명으로 판별 불가 — UNKNOWN")
    observed = sorted(d for d, v in history.items() if v != "")
    obs_start = observed[0] if observed else ""
    obs_end = observed[-1] if observed else ""
    lag = (today - date.fromisoformat(obs_end)).days if obs_end else ""
    return {
        "series_id": spec.series_id,
        "stat_code": spec.stat_code,
        "item_code1": spec.item_code,
        "cycle": spec.cycle,
        "unit": unit,
        "series_type": series_type_for(spec.calc_type),
        "seasonal_adj": sa,
        "observation_start": obs_start,
        "observation_end": obs_end,
        "publication_lag_days": lag,
        "source_kind": "ECOS",
        "probed_at": probed_at,
    }, warns


# ---------------------------------------------------------------------------
# 대상 시리즈 · 레지스트리
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeriesSpec:
    series_id: str
    stat_code: str
    cycle: str
    item_code: str
    calc_type: str | None = None
    origin: str = "SERIES"          # SERIES | CANDIDATE


DERIVED_ITEMS = {"SPREAD", "CSPREAD"}


def load_invalid_registry(paths: Paths) -> tuple[set[str], set[tuple[str, str]]]:
    keys, combos = set(), set()
    for r in read_csv_rows(paths.invalid):
        if r.get("key"):
            keys.add(r["key"].strip())
        if r.get("stat_code") and r.get("item_code"):
            combos.add((r["stat_code"].strip(), r["item_code"].strip()))
    return keys, combos


def is_invalid(spec_id: str, stat_code: str, item_code: str,
               invalid: tuple[set[str], set[tuple[str, str]]]) -> bool:
    keys, combos = invalid
    return spec_id in keys or (stat_code, item_code) in combos


def series_from_registry() -> list[SeriesSpec]:
    out = []
    for entry in ecos_fetch.SERIES:
        key, stat_code, period, item_code = entry[:4]
        calc_type = entry[6] if len(entry) > 6 else None
        if item_code in DERIVED_ITEMS:
            continue
        out.append(SeriesSpec(key, stat_code, period, item_code, calc_type, "SERIES"))
    return out


def load_candidates(paths: Paths) -> list[dict]:
    rows = read_csv_rows(paths.candidates)
    if rows:
        return rows
    return [{
        "series_id": sid, "stat_code": sc, "item_code1": ic, "cycle": cy,
        "expect_name": exp, "status": "UNVERIFIED", "result_code": "", "rows_returned": "",
        "item_name": "", "probed_at": "", "note": note,
    } for sid, sc, cy, ic, exp, note in DEFAULT_CANDIDATES]


def build_targets(paths: Paths, candidates: list[dict], only: set[str] | None,
                  log: Callable[[str], None] = print) -> list[SeriesSpec]:
    invalid = load_invalid_registry(paths)
    targets: list[SeriesSpec] = []
    for s in series_from_registry():
        if is_invalid(s.series_id, s.stat_code, s.item_code, invalid):
            log(f"  [SKIP] {s.series_id}: 무효 코드 레지스트리에 등재됨")
            continue
        targets.append(s)
    for c in candidates:
        if c.get("status") != "CONFIRMED":
            continue
        if is_invalid(c["series_id"], c["stat_code"], c["item_code1"], invalid):
            log(f"  [SKIP] {c['series_id']}: 무효 코드 레지스트리에 등재됨")
            continue
        targets.append(SeriesSpec(c["series_id"], c["stat_code"], c["cycle"],
                                  c["item_code1"], None, "CANDIDATE"))
    if only:
        targets = [t for t in targets if t.series_id in only]
    return targets


# ---------------------------------------------------------------------------
# 후보 검증 (probe)
# ---------------------------------------------------------------------------
def probe_candidate(c: dict, *, api_key: str, http_get: HttpGet, sleep, today: date,
                    probed_at: str, log: Callable[[str], None] = print) -> dict:
    """ecos_fetch 와 같은 StatisticSearch 경로로 최근 구간을 실조회한다.
    데이터 행 >= 1 이고 ITEM_NAME 이 기대 키워드를 모두 포함해야 CONFIRMED."""
    cycle = c["cycle"]
    end = safe_end(cycle, today)
    lookback = {"D": 30, "M": 24, "Q": 8, "A": 5}[cycle]
    start = iso_to_time(shift_periods(time_to_iso(end, cycle), cycle, -lookback), cycle)
    out = dict(c, probed_at=probed_at)
    try:
        rows = fetch_range(c["stat_code"], cycle, c["item_code1"], start, end,
                           api_key=api_key, http_get=http_get, sleep=sleep, log=log)
    except EcosError as exc:
        status = {"NO_DATA": "NO_DATA", "AUTH_ERROR": "AUTH_ERROR",
                  "RATE_LIMIT": "RATE_LIMIT"}.get(exc.category, "ERROR")
        out.update(status=status, result_code=exc.code or exc.category,
                   rows_returned="0", item_name="")
        return out
    data_rows = [r for r in rows if normalize_value(r.get("DATA_VALUE")) != ""]
    names = " ".join(str(rows[-1].get(k, "") or "") for k in
                     ("ITEM_NAME1", "ITEM_NAME2", "ITEM_NAME3")) if rows else ""
    expect = [k for k in str(c.get("expect_name", "")).split("|") if k]
    out.update(rows_returned=str(len(data_rows)), item_name=names.strip(),
               result_code="OK" if data_rows else "EMPTY_ROWS")
    if not data_rows:
        out["status"] = "NO_DATA"
    elif expect and not all(k in names for k in expect):
        out["status"] = "NAME_MISMATCH"
    else:
        out["status"] = "CONFIRMED"
    return out


# ---------------------------------------------------------------------------
# 시리즈 수집
# ---------------------------------------------------------------------------
@dataclass
class SeriesOutcome:
    series_id: str
    status: str
    rows_added: int = 0
    rows_revised: int = 0
    error: str = ""


def collect_series(spec: SeriesSpec, paths: Paths, *, api_key: str, http_get: HttpGet,
                   sleep, today: date, run_at: str, full: bool, prev_meta: dict | None,
                   cache: dict, log: Callable[[str], None] = print
                   ) -> tuple[SeriesOutcome, dict | None, list[dict]]:
    path = paths.ecos / f"{spec.series_id}.csv"
    existing = read_history(path)
    last = max(existing) if existing else None

    def _fetch(full_range: bool) -> list[dict]:
        start, end = query_range(spec.cycle, last, today, full_range)
        ck = (spec.stat_code, spec.cycle, spec.item_code, start, end)
        if ck not in cache:
            cache[ck] = fetch_range(spec.stat_code, spec.cycle, spec.item_code, start, end,
                                    api_key=api_key, http_get=http_get, sleep=sleep, log=log)
        return cache[ck]

    try:
        rows = _fetch(full)
        incoming = rows_to_series(rows, spec.cycle)
        res = merge_history(existing, incoming)
        rebased = (not full and existing and res.overlap >= REBASE_MIN_ROWS
                   and len(res.revisions) >= REBASE_RATIO * res.overlap)
        if rebased:
            log(f"    [REBASE?] {spec.series_id}: 재조회 구간 {res.overlap}건 중 "
                f"{len(res.revisions)}건 변경 — 전 구간 재조회")
            rows = _fetch(True)
            incoming = rows_to_series(rows, spec.cycle)
            res = merge_history(existing, incoming)
    except EcosError as exc:
        return SeriesOutcome(spec.series_id, exc.category, error=mask_secret(exc, api_key)), None, []
    except ValueError as exc:
        return SeriesOutcome(spec.series_id, "PARSE_ERROR", error=mask_secret(exc, api_key)), None, []

    if res.added or res.revisions or not path.exists():
        write_history(path, res.merged)
    revisions = [{"series_id": spec.series_id, "date": d, "old_value": o, "new_value": n,
                  "detected_at": run_at} for d, o, n in res.revisions]
    meta, warns = build_meta_row(spec, rows, res.merged, run_at, today, prev_meta)
    for w in warns:
        log(f"    [WARN] {w}")
    return (SeriesOutcome(spec.series_id, "OK", res.added, len(res.revisions)),
            meta, revisions)


# ---------------------------------------------------------------------------
# KOSIS 복사 (값 그대로, 결측 보존)
# ---------------------------------------------------------------------------
def copy_kosis(paths: Paths, run_at: str, today: date, prev_meta: dict[str, dict],
               log: Callable[[str], None] = print
               ) -> tuple[list[SeriesOutcome], list[dict], list[dict]]:
    """data/kosis_latest.csv 에 값이 있는 행만 이력에 반영한다.
    KOSIS 수집이 실패한 날(행 없음·값 NaN)은 아무 것도 쓰지 않는다 — ECOS 값이나
    직전 값으로 메우지 않는다(대체 로직은 신호 계산 단계 책임)."""
    outcomes, metas, revisions = [], [], []
    rows = read_csv_rows(paths.kosis_latest)
    if not rows:
        log("  [KOSIS] kosis_latest.csv 비어 있음 — 복사할 값 없음 (결측 그대로 둠)")
        return outcomes, metas, revisions
    for r in rows:
        sid = (r.get("series_id") or "").strip()
        cycle = (r.get("period") or "").strip()
        val = normalize_value(r.get("value"))
        if not sid:
            continue
        if val == "" or val.lower() == "nan":
            outcomes.append(SeriesOutcome(sid, "KOSIS_MISSING"))
            continue
        try:
            iso = time_to_iso(r.get("date", ""), cycle)
        except ValueError as exc:
            outcomes.append(SeriesOutcome(sid, "PARSE_ERROR", error=str(exc)))
            continue
        path = paths.kosis / f"{sid}.csv"
        existing = read_history(path)
        res = merge_history(existing, {iso: val})
        if res.added or res.revisions or not path.exists():
            write_history(path, res.merged)
        revisions += [{"series_id": sid, "date": d, "old_value": o, "new_value": n,
                       "detected_at": run_at} for d, o, n in res.revisions]
        observed = sorted(d for d, v in res.merged.items() if v != "")
        metas.append({
            "series_id": sid,
            "stat_code": (r.get("stat_code") or "").strip(),
            "item_code1": "",
            "cycle": cycle,
            "unit": (r.get("unit") or "").strip(),
            "series_type": "KOSIS_LATEST_AS_IS",
            "seasonal_adj": (prev_meta.get(sid) or {}).get("seasonal_adj", "UNKNOWN"),
            "observation_start": observed[0],
            "observation_end": observed[-1],
            "publication_lag_days": (today - date.fromisoformat(observed[-1])).days,
            "source_kind": "KOSIS_COPY",
            "probed_at": run_at,
        })
        outcomes.append(SeriesOutcome(sid, "OK", res.added, len(res.revisions)))
    return outcomes, metas, revisions


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def run(argv: list[str] | None = None, *, root: Path = ROOT, http_get: HttpGet = requests.get,
        sleep: Callable[[float], None] = time.sleep, now: datetime | None = None,
        api_key: str | None = None, log: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="ECOS 시리즈 전체 이력 수집기")
    ap.add_argument("--full", action="store_true", help="전 구간 재조회")
    ap.add_argument("--probe", action="store_true", help="UNVERIFIED 후보를 실조회로 검증")
    ap.add_argument("--series", nargs="*", help="특정 series_id 만 수집")
    ap.add_argument("--no-kosis", action="store_true", help="KOSIS 복사 생략")
    args = ap.parse_args(argv)

    paths = Paths(root)
    now = now or datetime.now(_KST)
    today = now.date()
    run_at = now.strftime("%Y-%m-%dT%H:%M:%S%z")
    key = api_key if api_key is not None else os.environ.get("ECOS_API_KEY", "")

    _log = log

    def log(msg: str) -> None:  # 모든 출력은 마스킹을 거친다
        _log(mask_secret(msg, key))

    log("=" * 60)
    log(f"ECOS 시계열 이력 수집 ({run_at})")
    log("=" * 60)
    if not key or key == "sample":
        log("[ERROR] ECOS_API_KEY 미설정 — 수집 중단 (실호출 미실행)")
        return 2

    prev_meta = {r["series_id"]: r for r in read_csv_rows(paths.meta)}
    candidates = load_candidates(paths)
    log_rows: list[dict] = []
    revisions: list[dict] = []
    outcomes: list[SeriesOutcome] = []
    aborted = False

    if args.probe:
        invalid = load_invalid_registry(paths)
        for i, c in enumerate(candidates):
            if c.get("status", "") not in REPROBE_STATUSES:
                continue
            if is_invalid(c["series_id"], c["stat_code"], c["item_code1"], invalid):
                log(f"  [PROBE-SKIP] {c['series_id']}: 무효 코드 레지스트리에 등재됨")
                continue
            candidates[i] = probe_candidate(c, api_key=key, http_get=http_get, sleep=sleep,
                                            today=today, probed_at=run_at, log=log)
            log(f"  [PROBE] {c['series_id']:<22} {c['stat_code']}/{c['item_code1']} "
                f"-> {candidates[i]['status']} (rows={candidates[i]['rows_returned']}, "
                f"code={candidates[i]['result_code']}, name={candidates[i]['item_name']!r})")
            sleep(CALL_INTERVAL)
            if candidates[i]["status"] == "AUTH_ERROR":
                aborted = True
                break
        write_csv_rows(paths.candidates, CANDIDATE_COLUMNS, candidates)
    elif not paths.candidates.exists():
        write_csv_rows(paths.candidates, CANDIDATE_COLUMNS, candidates)

    metas: dict[str, dict] = dict(prev_meta)
    if not aborted:
        targets = build_targets(paths, candidates, set(args.series) if args.series else None, log)
        cache: dict = {}
        for i, spec in enumerate(targets, 1):
            log(f"  [{i:02d}/{len(targets)}] {spec.series_id:<24} {spec.stat_code}/{spec.cycle}/{spec.item_code}")
            out, meta, revs = collect_series(
                spec, paths, api_key=key, http_get=http_get, sleep=sleep, today=today,
                run_at=run_at, full=args.full, prev_meta=prev_meta.get(spec.series_id),
                cache=cache, log=log)
            outcomes.append(out)
            revisions += revs
            if meta:
                metas[spec.series_id] = meta
            if out.status != "OK":
                log(f"    [FAIL] {out.status}: {out.error}")
            elif out.rows_added or out.rows_revised:
                log(f"    +{out.rows_added} rows, {out.rows_revised} revised")
            if out.status == "AUTH_ERROR":
                aborted = True
                log("  [ABORT] 인증 오류 — 이후 시리즈 호출 중단")
                break
            sleep(CALL_INTERVAL)

    if not args.no_kosis and not args.series:
        k_out, k_meta, k_rev = copy_kosis(paths, run_at, today, prev_meta, log)
        outcomes += [o for o in k_out if o.status != "KOSIS_MISSING"]
        log_rows += [{"run_at": run_at, "series_id": o.series_id, "rows_added": 0,
                      "rows_revised": 0, "status": o.status, "error": ""}
                     for o in k_out if o.status == "KOSIS_MISSING"]
        revisions += k_rev
        for m in k_meta:
            metas[m["series_id"]] = m

    # 메타: 이번에 실패한 시리즈는 직전 메타를 유지
    order = [s.series_id for s in series_from_registry()] + [c["series_id"] for c in candidates]
    rank = {sid: i for i, sid in enumerate(order)}
    meta_rows = sorted(metas.values(), key=lambda m: (rank.get(m["series_id"], len(rank)),
                                                      m["series_id"]))
    if metas:
        write_csv_rows(paths.meta, META_COLUMNS, meta_rows)

    log_rows += [{"run_at": run_at, "series_id": o.series_id, "rows_added": o.rows_added,
                  "rows_revised": o.rows_revised, "status": o.status,
                  "error": mask_secret(o.error, key)} for o in outcomes]
    append_csv(paths.collect_log, LOG_COLUMNS, log_rows)
    append_csv(paths.revisions, REVISION_COLUMNS, revisions)

    failed = [o for o in outcomes if o.status != "OK"]
    log("-" * 60)
    log(f"성공 {len(outcomes) - len(failed)} / 실패 {len(failed)} / 개정 {len(revisions)}건")
    if failed:
        log("| series_id | status | error |")
        log("|---|---|---|")
        for o in failed:
            log(f"| {o.series_id} | {o.status} | {o.error} |")
    if aborted:
        return 2
    return 1 if failed else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
