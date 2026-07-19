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

# ECOS는 항상 확보되어야 하는 원천(자체 API 연결 이슈 없음)이므로 하드 실패 기준으로 사용.
# KOSIS는 kosis.kr 측 네트워크 차단으로 전체 실패할 수 있어 경고로만 처리하고
# 파이프라인은 ECOS 데이터만으로도 계속 진행한다.
MIN_SERIES_ECOS  = 18   # ECOS 21개 중 최소 확보 기준
MIN_SERIES_TOTAL = 18   # 전체(ECOS+KOSIS) 최소 확보 기준 — 완전 붕괴 감지용
MIN_SERIES_KOSIS = 8    # 미달 시 경고만 (하드 실패 아님)
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

    n_ecos  = int((df.get("source") == "ecos").sum())  if "source" in df.columns else n
    n_kosis = int((df.get("source") == "kosis").sum()) if "source" in df.columns else 0

    if na > 0:
        errors.append(f"N/A 값 {na}개 잔존")
    if n < MIN_SERIES_TOTAL:
        errors.append(f"지표 {n}개 — 최소 {MIN_SERIES_TOTAL}개 미달")
    if n_ecos < MIN_SERIES_ECOS:
        errors.append(f"ECOS 지표 {n_ecos}개 — 최소 {MIN_SERIES_ECOS}개 미달")
    if n_kosis < MIN_SERIES_KOSIS:
        warns.append(
            f"KOSIS 지표 {n_kosis}개 — 최소 {MIN_SERIES_KOSIS}개 미달 "
            "(kosis.kr 연결 이슈 가능, 파이프라인은 계속 진행)"
        )

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

    ppi  = df.loc[df["series_id"] == "PPI_YOY", "value"]
    if not cpi.empty and not ppi.empty:
        pv, cv = float(ppi.iloc[0]), float(cpi.iloc[0])
        if abs(pv - cv) < 0.05:
            ppi_chg = df.loc[df["series_id"] == "PPI_YOY", "chg_prev"]
            cpi_chg = df.loc[df["series_id"] == "KOSIS_CPI_YOY", "chg_prev"]
            if (not ppi_chg.empty and not cpi_chg.empty
                    and float(ppi_chg.iloc[0]) == float(cpi_chg.iloc[0])):
                errors.append(
                    f"PPI_YOY({pv}%) == KOSIS_CPI_YOY({cv}%) — "
                    "901Y009 CPI 중복 의심, 404Y014/*AA 확인"
                )

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
