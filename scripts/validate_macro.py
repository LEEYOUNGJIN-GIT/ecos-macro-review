"""
scripts/validate_macro.py
macro_latest.csv 품질 검증 — CI 및 로컬 파이프라인 후 실행.

검증 항목:
  1. N/A 값 없음, 최소 30개 지표
  2. CPI vs 근원CPI YoY 괴리 ≤ 1.5%p
  3. IMPORT_PRICE_YOY 극단값 경고 (≥25%, fail 아님)
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR   = Path(__file__).parent.parent / "data"
MACRO_CSV  = DATA_DIR / "macro_latest.csv"

MIN_SERIES       = 30
CORE_CPI_MAX_GAP = 1.5
IMPORT_WARN      = 25.0


def validate() -> list[str]:
    errors: list[str] = []
    warns:  list[str] = []

    if not MACRO_CSV.exists():
        errors.append(f"{MACRO_CSV} 없음")
        return errors

    df = pd.read_csv(MACRO_CSV, encoding="utf-8-sig")
    n  = len(df)
    na = int(df["value"].isna().sum())

    if na > 0:
        errors.append(f"N/A 값 {na}개 잔존")
    if n < MIN_SERIES:
        errors.append(f"지표 {n}개 — 최소 {MIN_SERIES}개 미달")

    cpi  = df.loc[df["series_id"] == "KOSIS_CPI_YOY", "value"]
    core = df.loc[df["series_id"] == "KOSIS_CORE_CPI_YOY", "value"]
    if not cpi.empty and not core.empty:
        gap = abs(float(cpi.iloc[0]) - float(core.iloc[0]))
        if gap > CORE_CPI_MAX_GAP:
            errors.append(
                f"CPI·근원CPI gap {gap:.2f}%p > {CORE_CPI_MAX_GAP} "
                f"(CPI={cpi.iloc[0]}, Core={core.iloc[0]})"
            )

    imp = df.loc[df["series_id"] == "IMPORT_PRICE_YOY", "value"]
    if not imp.empty and abs(float(imp.iloc[0])) >= IMPORT_WARN:
        warns.append(f"IMPORT_PRICE_YOY={imp.iloc[0]}% - 기저효과·관세충격 가능")

    for w in warns:
        print(f"  [WARN] {w}")
    return errors


def main() -> None:
    print("=" * 60)
    print("macro_latest.csv 품질 검증")
    print("=" * 60)
    errors = validate()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        sys.exit(1)
    print("  [OK] macro 품질 검증 통과")
    print("=" * 60)


if __name__ == "__main__":
    main()
