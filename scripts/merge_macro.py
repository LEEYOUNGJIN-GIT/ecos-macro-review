"""
scripts/merge_macro.py
ecos_latest.csv + kosis_latest.csv 를 병합하여 data/macro_latest.csv 를 생성합니다.

병합 규칙:
  1. 동일 series_id 충돌 시 KOSIS 데이터 우선 (ECOS 행 제거)
  2. source 컬럼 추가 ('ecos' / 'kosis')
  3. 기준일 이질성 경고: 2개월 이상 지연 지표에 [WARN] 로그 출력

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

    print(f"  ECOS: {len(ecos_df)}개, KOSIS: {len(kosis_df)}개, 통합: {len(combined)}개")

    _check_staleness(combined)

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
