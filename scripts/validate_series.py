"""
scripts/validate_series.py
data/series/ 스키마 계약 검증 (docs/SERIES_SCHEMA.md). 위반 시 종료코드 1.

검사 항목:
  1. 이력 파일 헤더가 정확히 date,value
  2. date 는 ISO(YYYY-MM-DD)·오름차순·중복 없음, 주기 규약(월=1일, 분기=분기 첫날, 연=1월 1일)
  3. value 는 숫자 또는 빈 값(결측)
  4. ecos_meta.csv 컬럼이 규약과 정확히 일치, 이력 파일과 메타가 1:1
  5. source_kind 는 ECOS | KOSIS_COPY, 디렉터리와 일치
  6. seasonal_adj 는 SA | NSA | UNKNOWN
  7. 무효 코드 레지스트리 키가 이력에 존재하지 않음
  8. 저장 파일·로그에 API 키 형태 문자열(StatisticSearch/<key>/)이 없음
"""

from __future__ import annotations

import csv
import os
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

META_COLUMNS = [
    "series_id", "stat_code", "item_code1", "cycle", "unit", "series_type",
    "seasonal_adj", "observation_start", "observation_end", "publication_lag_days",
    "source_kind", "probed_at",
]
SOURCE_DIR = {"ECOS": "ecos", "KOSIS_COPY": "kosis"}
_KEY_LEAK = re.compile(r"Statistic(?:Search|ItemList|TableList)/(?!\*\*\*/)[^/\s]+/")


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def _cycle_ok(d: date, cycle: str) -> bool:
    if cycle == "M":
        return d.day == 1
    if cycle == "Q":
        return d.day == 1 and d.month in (1, 4, 7, 10)
    if cycle == "A":
        return d.day == 1 and d.month == 1
    return True


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    series = root / "data" / "series"
    meta_path = series / "ecos_meta.csv"
    if not series.exists():
        return errors  # 아직 수집 전 — 검사할 것이 없음

    meta: dict[str, dict] = {}
    if meta_path.exists():
        cols, rows = _read(meta_path)
        if cols != META_COLUMNS:
            errors.append(f"ecos_meta.csv 컬럼 불일치: {cols}")
        for r in rows:
            sid = r.get("series_id", "")
            if sid in meta:
                errors.append(f"ecos_meta.csv series_id 중복: {sid}")
            meta[sid] = r
            if r.get("source_kind") not in SOURCE_DIR:
                errors.append(f"{sid}: source_kind={r.get('source_kind')!r}")
            if r.get("seasonal_adj") not in ("SA", "NSA", "UNKNOWN"):
                errors.append(f"{sid}: seasonal_adj={r.get('seasonal_adj')!r}")

    files: dict[str, tuple[str, Path]] = {}
    for kind, sub in SOURCE_DIR.items():
        for p in sorted((series / sub).glob("*.csv")):
            files[p.stem] = (kind, p)

    for sid, (kind, p) in files.items():
        m = meta.get(sid)
        if m is None:
            errors.append(f"{p.relative_to(root)}: ecos_meta.csv 에 메타 없음")
            cycle = None
        else:
            cycle = m.get("cycle")
            if m.get("source_kind") != kind:
                errors.append(f"{sid}: 메타 source_kind={m.get('source_kind')} 인데 {SOURCE_DIR[kind]}/ 에 저장됨")
        cols, rows = _read(p)
        if cols != ["date", "value"]:
            errors.append(f"{p.name}: 헤더 {cols} != ['date', 'value']")
            continue
        prev = None
        for i, r in enumerate(rows, 2):
            try:
                d = date.fromisoformat(r["date"])
            except ValueError:
                errors.append(f"{p.name}:{i} ISO 날짜 아님 {r['date']!r}")
                continue
            if prev is not None and r["date"] <= prev:
                errors.append(f"{p.name}:{i} 날짜 정렬/중복 위반 {r['date']}")
            prev = r["date"]
            if cycle and not _cycle_ok(d, cycle):
                errors.append(f"{p.name}:{i} 주기 {cycle} 날짜 규약 위반 {r['date']}")
            v = r["value"]
            if v != "":
                try:
                    Decimal(v)
                except InvalidOperation:
                    errors.append(f"{p.name}:{i} 숫자 아님 {v!r}")

    for sid, m in meta.items():
        if sid not in files:
            errors.append(f"ecos_meta.csv 의 {sid}: 이력 파일 없음")

    invalid = root / "data" / "ecos_invalid_codes.csv"
    if invalid.exists():
        _, inv = _read(invalid)
        for r in inv:
            if r.get("key") in files:
                errors.append(f"무효 코드 {r['key']} 가 이력에 존재")

    key = os.environ.get("ECOS_API_KEY", "")
    for p in series.rglob("*.csv"):
        text = p.read_text(encoding="utf-8")
        if _KEY_LEAK.search(text) or (len(key) >= 8 and key in text):
            errors.append(f"{p.relative_to(root)}: API 키 노출 의심")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for e in errors[:200]:
            print(f"  [FAIL] {e}")
        print(f"[FAIL] data/series 스키마 위반 {len(errors)}건")
        return 1
    print("[OK] data/series 스키마 계약 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
