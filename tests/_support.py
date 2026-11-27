"""테스트 공용 도구: 결정적 합성 ECOS 데이터와 URL 을 해석하는 가짜 ECOS 서버.

fixture 응답은 실호출 결과가 아니다. RESULT.CODE 값은 ECOS 개발가이드의 코드표를,
행 필드명(TIME·DATA_VALUE·UNIT_NAME·ITEM_NAME1 …)은 ecos_fetch.py 가 읽는 필드를 따른다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden"
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ecos_fetch  # noqa: E402

FIXED_TODAY = date(2026, 10, 12)
API_KEY = "TESTKEY1234567890ABCD"

EXISTING_OUTPUTS = [
    "data/ecos_latest.csv", "data/ecos_latest.md", "data/kosis_latest.csv",
    "data/kosis_latest.md", "data/macro_latest.csv", "data/ecos_signals.md",
    "data/ecos_regime.md", "data/kosis_status_log.csv",
]


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _times(cycle: str) -> list[str]:
    if cycle == "M":
        return [f"{y}{m:02d}" for y in range(2018, 2027) for m in range(1, 13)
                if (y, m) <= (2026, 8)]
    if cycle == "Q":
        return [f"{y}Q{q}" for y in range(2018, 2027) for q in range(1, 5)
                if (y, q) <= (2026, 2)]
    if cycle == "A":
        return [str(y) for y in range(2010, 2026)]
    out, d = [], date(2025, 1, 2)
    while d <= date(2026, 10, 9):
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def synth_rows(stat: str, cycle: str, item: str, unit: str = "", name: str = "") -> list[dict]:
    s = _seed(stat, cycle, item)
    base = 50 + s % 100
    step = ((s >> 8) % 7 + 1) / 100
    rows = []
    for i, t in enumerate(_times(cycle)):
        v = round(base + i * step + ((i * 7 + s) % 5) / 10, 3)
        rows.append({
            "STAT_CODE": stat, "STAT_NAME": f"합성표 {stat}",
            "ITEM_CODE1": item.split("/")[0], "ITEM_NAME1": name or f"합성항목 {item}",
            "UNIT_NAME": unit or "지수", "TIME": t, "DATA_VALUE": f"{v}",
        })
    return rows


def registry_dataset() -> dict[tuple[str, str, str], list[dict]]:
    data = {}
    for entry in ecos_fetch.SERIES:
        key, stat, cycle, item, unit, label = entry[:6]
        if item in ("SPREAD", "CSPREAD"):
            continue
        data[(stat, cycle, item)] = synth_rows(stat, cycle, item, unit, label)
    return data


class FakeResponse:
    def __init__(self, body, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeEcos:
    """StatisticSearch URL 을 해석해 기간·페이지 범위대로 행을 돌려준다.
    데이터가 없으면 실제 ECOS 처럼 HTTP 200 + RESULT INFO-200."""

    def __init__(self, data: dict[tuple[str, str, str], list[dict]] | None = None,
                 overrides: dict[tuple[str, str, str], object] | None = None):
        self.data = data if data is not None else {}
        self.overrides = overrides or {}
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: int = 0):
        self.calls.append(url)
        parts = url.split("/StatisticSearch/", 1)[1].split("/")
        # key/json/kr/s/e/stat/cycle/start/end/item...
        s_row, e_row = int(parts[3]), int(parts[4])
        stat, cycle, start, end = parts[5], parts[6], parts[7], parts[8]
        item = "/".join(parts[9:])
        k = (stat, cycle, item)
        if k in self.overrides:
            ov = self.overrides[k]
            if callable(ov):
                return ov(url)
            return FakeResponse(ov)
        rows = [r for r in self.data.get(k, []) if start <= r["TIME"] <= end]
        if not rows:
            return FakeResponse(load_fixture("ecos_info200.json"))
        return FakeResponse({"StatisticSearch": {
            "list_total_count": len(rows), "row": rows[s_row - 1:e_row]}})


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_root() -> Path:
    """현재 저장소의 기존 산출물과 무효 코드 레지스트리를 복사한 임시 루트."""
    tmp = Path(tempfile.mkdtemp(prefix="ecos_series_test_"))
    (tmp / "data").mkdir()
    for rel in EXISTING_OUTPUTS + ["data/ecos_invalid_codes.csv"]:
        shutil.copy2(ROOT / rel, tmp / rel)
    return tmp


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
