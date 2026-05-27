"""
scripts/merge_macro.py
ecos_latest.csv + kosis_latest.csv 를 병합하여 data/macro_latest.csv 를 생성합니다.

병합 규칙:
  1. 동일 series_id 충돌 시 KOSIS 데이터 우선 (ECOS 행 제거)
  2. source 컬럼 추가 ('ecos' / 'kosis')
  3. 기준일 이질성 경고: 2개월 이상 지연 지표에 [WARN] 로그 출력

v1.1 (2026-05-27): CPI·근원CPI 교차검증, 수입물가 극단값 경고
  - _validate_cpi_cross(): |근원CPI−CPI| > 1.5%p 시 [WARN]
  - _flag_extreme_import(): IMPORT_PRICE_YOY ≥25% 경고

v1.0 (2026-05-27): ECOS+KOSIS 통합 플랜 v1 구현
"""

import sys
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

_KST = ZoneInfo("Asia/Seoul")

DATA_DIR   = Path(__file__).parent.parent / "data"
ECOS_CSV   = DATA_DIR / "ecos_latest.csv"
KOSIS_CSV  = DATA_DIR / "kosis_latest.csv"
OUTPUT_CSV = DATA_DIR / "macro_latest.csv"

CORE_CPI_MAX_GAP   = 1.5   # %p
IMPORT_PRICE_WARN  = 25.0  # % YoY


# ---------------------------------------------------------------------------
# 기준일 이질성 검사
# ---------------------------------------------------------------------------
def _check_staleness(df: pd.DataFrame) -> None:
    """2개월 이상 지연 지표에 [WARN] 로그 출력."""
    today = date.today()
    warned: list[str] = []

    for _, row in df.iterrows():
        sid      = str(row.get("series_id", ""))
        period   = str(row.get("period", "M"))
        obs_date = str(row.get("date", "N/A"))
        try:
            if period == "M" and len(obs_date) == 6 and obs_date.isdigit():
                obs = date(int(obs_date[:4]), int(obs_date[4:6]), 1)
                months_lag = (today.year - obs.year) * 12 + (today.month - obs.month)
                if months_lag >= 2:
                    warned.append(f"{sid}({obs_date}, {months_lag}개월)")
        except Exception:
            pass

    if warned:
        print(f"  [WARN] 2개월+ 지연 지표 ({len(warned)}개): {', '.join(warned)}")
    else:
        print("  [INFO] 모든 지표 기준일 2개월 이내 — 정상")


def _validate_cpi_cross(df: pd.DataFrame) -> None:
    """헤드라인 CPI vs 근원CPI YoY 괴리 검사."""
    cpi_rows  = df.loc[df["series_id"] == "KOSIS_CPI_YOY", "value"]
    core_rows = df.loc[df["series_id"] == "KOSIS_CORE_CPI_YOY", "value"]
    if cpi_rows.empty or core_rows.empty:
        return
    cpi  = float(cpi_rows.iloc[0])
    core = float(core_rows.iloc[0])
    gap  = abs(core - cpi)
    if gap > CORE_CPI_MAX_GAP:
        print(
            f"  [WARN] CPI({cpi}%) vs 근원CPI({core}%) gap {gap:.2f}%p "
            f"> {CORE_CPI_MAX_GAP} - KOSIS_CORE_CPI_YOY 파라미터 확인"
        )
    else:
        print(f"  [INFO] CPI·근원CPI gap {gap:.2f}%p - 정상")


def _flag_extreme_import(df: pd.DataFrame) -> None:
    """수입물가 YoY 극단값 경고."""
    rows = df.loc[df["series_id"] == "IMPORT_PRICE_YOY", "value"]
    if rows.empty:
        return
    val = float(rows.iloc[0])
    if abs(val) >= IMPORT_PRICE_WARN:
        print(f"  [WARN] IMPORT_PRICE_YOY={val}% - 기저효과·관세충격 가능")


# ---------------------------------------------------------------------------
# 병합 실행
# ---------------------------------------------------------------------------
def merge() -> pd.DataFrame:
    if not ECOS_CSV.exists():
        sys.exit(f"[ERROR] {ECOS_CSV} 없음. ecos_fetch.py 를 먼저 실행하세요.")
    if not KOSIS_CSV.exists():
        sys.exit(f"[ERROR] {KOSIS_CSV} 없음. kosis_fetch.py 를 먼저 실행하세요.")

    ecos_df  = pd.read_csv(ECOS_CSV,  encoding="utf-8-sig")
    kosis_df = pd.read_csv(KOSIS_CSV, encoding="utf-8-sig")

    ecos_df["source"]  = "ecos"
    kosis_df["source"] = "kosis"

    # KOSIS 에 있는 series_id 는 ECOS 행 제거 (KOSIS 우선)
    kosis_ids = set(kosis_df["series_id"])
    overlap   = kosis_ids & set(ecos_df["series_id"])
    if overlap:
        print(f"  [INFO] KOSIS 우선 처리된 series_id: {sorted(overlap)}")
        ecos_df = ecos_df[~ecos_df["series_id"].isin(kosis_ids)]

    combined = pd.concat([ecos_df, kosis_df], ignore_index=True)

    # 수집 실패(N/A) 행 제거
    before = len(combined)
    combined = combined.dropna(subset=["value"]).reset_index(drop=True)
    dropped = before - len(combined)
    if dropped:
        print(f"  [DROP] N/A 지표 {dropped}개 제외 (통합 {before} → {len(combined)}개)")

    print(f"  ECOS: {len(ecos_df)}개, KOSIS: {len(kosis_df)}개, 통합: {len(combined)}개")

    _check_staleness(combined)
    _validate_cpi_cross(combined)
    _flag_extreme_import(combined)

    return combined


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("macro_latest.csv 병합 시작")
    print("=" * 60)

    df = merge()
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    generated_at = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n  Saved: {OUTPUT_CSV}  ({generated_at} KST)")
    print("=" * 60)


if __name__ == "__main__":
    main()
