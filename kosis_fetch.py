"""
kosis_fetch.py
통계청 KOSIS API에서 11개 거시경제 지표를 수집하고
data/kosis_latest.csv 및 data/kosis_latest.md 를 생성합니다.

KOSIS API 키 발급: https://kosis.kr/openapi/
통계자료 조회 API: statisticsParameterData.do

⚠ 주의사항:
  - KOSIS_SERIES 의 tbl_id, itm_id, obj_l1 은 초안값입니다.
  - 최초 실행 전 반드시 validate_tblids() 로 각 시리즈 검증 필요.
    python kosis_fetch.py --validate
  - 검증 실패(WARN) 항목은 KOSIS 통합검색(https://kosis.kr)에서
    tblId·itmId·objL1 확인 후 수정하세요.
  - 검증 실패 시 해당 지표는 None 처리, 파이프라인 계속 진행.

수정 이력:
  v1.1 (2026-05-27): API 파라미터 수정 및 JSON 파싱 수정
  - KOSIS 응답이 비표준 JS 표기({key:"val"})이므로 resp.json() 대신 regex fix 후 json.loads 사용
  - KOSIS_SERIES 튜플에 c1_filter(11번째) 추가: 동일 tblId 내 C1 코드로 지표 구분 시 사용
  - CPI/근원CPI/고용/경기지수 tblId·itmId·objL1 검증값으로 교체
    · CPI: DT_1J22003 / objL1=T10 / itmId=T (지수→yoy_pct)
    · 근원CPI: DT_1J22007(농산물석유류제외) / objL1=T10 / itmId=T (지수→yoy_pct)
    · 고용: DT_1DA7002S / objL1=00 / itmId T80/T90/T60/T30 검증
    · 경기지수 순환변동치: DT_1C8016→DT_1C8015 교체, c1_filter B03/A03 추가
  v1.3 (2026-05-27): 근원CPI objL1 수정 및 교차검증
  - KOSIS_CORE_CPI_YOY: objL1 QC→T10 (DT_1J22007 전국 총지수, CPI와 동일 지역코드)
    · QC는 DT_1J22003 내 분류코드로 DT_1J22007 전용 테이블에 부적합 → YoY 6.31% 오류 원인
  - _validate_core_cpi(): |근원CPI−CPI| > 1.5%p 시 None 처리
  - validate_tblids(): CPI·근원CPI YoY 교차검증 추가
  v1.2 (2026-05-27): 생산·소비 tblId 확정, 수출입 3종 제거
  - 광공업: DT_1F02011 / itmId=T10 / c1_filter=10 (yoy_pct)
  - 소매: DT_1K41012 / itmId=T2 / c1_filter=G0 (yoy_pct)
  - 서비스업: DT_1KC2020 / itmId=T2 / c1_filter=E (yoy_pct)
  - KOSIS_EXPORT/IMPORT/TRADE_BALANCE: 관세청 Open API tblId 미확인 → 프로젝트 전체 제거
  v1.0 (2026-05-27): 최초 작성 - ECOS+KOSIS 통합 플랜 v1 구현
"""

import json
import os
import re
import sys
import time
import argparse
import requests
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")

# ---------------------------------------------------------------------------
# 환경 설정
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY      = os.environ.get("KOSIS_API_KEY", "")
BASE_URL     = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
CALL_INTERVAL = 0.5

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# KOSIS_SERIES 레지스트리
# 형식: (series_id, org_id, tbl_id, itm_id, obj_l1, prd_se,
#        unit, label, calc_type, release_lag)
#
# calc_type:
#   None       - 최신값 직접 사용 (이미 YoY율 또는 지수값으로 제공)
#   "yoy_pct"  - 지수에서 전년동기비(%) 계산
#   "yoy_diff" - 수준값에서 전년동기 절대 증감 계산
#
# ⚠ tbl_id / itm_id / obj_l1 는 초안값 - validate_tblids() 로 검증 필수
#
# 주요 orgId:
#   101 = 통계청(국가통계포털)
# ---------------------------------------------------------------------------
KOSIS_SERIES = [
    # 형식: (series_id, org_id, tbl_id, itm_id, obj_l1, prd_se,
    #        unit, label, calc_type, release_lag, c1_filter)
    # c1_filter: 동일 tblId 내 C1 코드로 지표를 구분할 때 사용. None이면 필터 없음.

    # ── 01. 물가 ─────────────────────────────────────────────────────────
    # DT_1J22003: 소비자물가지수(2020=100) - 통계청(101)
    # objL1=T10(전국), itmId=T(총지수) → yoy_pct 계산으로 전년비 도출 ✅ v1.1 검증완료
    ("KOSIS_CPI_YOY",        "101", "DT_1J22003", "T",   "T10", "M",
     "%",     "소비자물가 전년동월비",              "yoy_pct",  "익월 7일",  None),

    # DT_1J22007: 농산물및석유류제외지수(2020=100) - 통계청(101)
    # objL1=T10(전국) — CPI(DT_1J22003)와 동일 지역코드. QC는 구 DT_1J22003 분류코드로 오류 유발
    # ※ 한국 공식 근원CPI(농산물·석유류제외) 기준 — OECD방식(식품·에너지제외)과 상이
    ("KOSIS_CORE_CPI_YOY",   "101", "DT_1J22007", "T",   "T10", "M",
     "%",     "근원물가 전년동월비(농산물·석유류제외)", "yoy_pct",  "익월 7일",  None),

    # ── 02. 고용 ─────────────────────────────────────────────────────────
    # DT_1DA7002S: 경제활동인구조사 - 통계청(101)
    # objL1=00(전국), itmId: T80=실업률, T90=고용률, T60=경활참가율, T30=취업자(천명)
    # ✅ v1.1 검증완료
    ("KOSIS_UNEMP_RATE",     "101", "DT_1DA7002S", "T80", "00",  "M",
     "%",     "실업률",                           None,       "익월 15일", None),
    ("KOSIS_EMP_RATE",       "101", "DT_1DA7002S", "T90", "00",  "M",
     "%",     "고용률(15세이상)",                   None,       "익월 15일", None),
    ("KOSIS_LABOR_PART",     "101", "DT_1DA7002S", "T60", "00",  "M",
     "%",     "경제활동참가율",                    None,       "익월 15일", None),
    # 취업자수(천명) → 전년동기 증감으로 변환 (yoy_diff)
    ("KOSIS_EMP_CHANGE",     "101", "DT_1DA7002S", "T30", "00",  "M",
     "천명",   "취업자수 전년동기 증감",              "yoy_diff", "익월 15일", None),

    # ── 03. 경기지수 ──────────────────────────────────────────────────────
    # DT_1C8015: 경기종합지수(10차)(2020=100) - 통계청(101)
    # objL1=ALL, itmId=T1, c1_filter로 동행/선행 순환변동치 구분 ✅ v1.1 검증완료
    # 동행지수 순환변동치: C1=B03 (최신값 약 100.1), 선행지수 순환변동치: C1=A03 (103.5)
    ("KOSIS_CLI_COINCIDENT", "101", "DT_1C8015",   "T1",  "ALL", "M",
     "지수",   "동행지수 순환변동치",               None,       "약 2개월",  "B03"),
    ("KOSIS_CLI_LEADING",    "101", "DT_1C8015",   "T1",  "ALL", "M",
     "지수",   "선행지수 순환변동치",               None,       "약 2개월",  "A03"),

    # ── 04. 생산 ─────────────────────────────────────────────────────────
    # DT_1F02011: 기본분류 일부항목 제외 광공업생산지수(2020=100) ✅ v1.2 검증
    ("KOSIS_INDPRO_YOY",     "101", "DT_1F02011",  "T10", "ALL", "M",
     "%",     "광공업생산지수 전년비",              "yoy_pct",  "익월 말",   "10"),

    # ── 05. 소비·내수 ─────────────────────────────────────────────────────
    # DT_1K41012: 재별 및 상품군별 소매판매액지수, C1=G0 총지수 불변지수 ✅ v1.2
    ("KOSIS_RETAIL_YOY",       "101", "DT_1K41012", "T2",  "ALL", "M",
     "%",     "소매판매 전년동월비",               "yoy_pct",  "익월 말",   "G0"),
    # DT_1KC2020: 산업별 서비스업생산지수, C1=E 전체 불변지수 ✅ v1.2
    ("KOSIS_SERVICE_PROD_YOY", "101", "DT_1KC2020", "T2",  "ALL", "M",
     "%",     "서비스업생산지수 전년비",            "yoy_pct",  "익월 말",   "E"),
]

# ---------------------------------------------------------------------------
# 지표별 해석 노트 (Claude 분석 컨텍스트 강화)
# ---------------------------------------------------------------------------
_FACT_ONLY   = "[참조전용] 신호/레짐 점수 미사용"
_CORE_NOTE   = "통계청 농산물·석유류제외(구 ECOS QB와 동일 계열). OECD 식품·에너지제외와 정의 상이"
SERIES_NOTES: dict[str, str] = {
    "KOSIS_CPI_YOY":          "소비자물가 기준지표. 통계청 익월 초 발표. BOK 목표 2%",
    "KOSIS_CORE_CPI_YOY":     _CORE_NOTE,
    "KOSIS_UNEMP_RATE":       "실업률. 상승 지속 시 고용 둔화 경계",
    "KOSIS_EMP_RATE":         "고용률(15세이상). 실업률과 교차 확인으로 고용 질 파악",
    "KOSIS_LABOR_PART":       _FACT_ONLY + ". 경제활동참가율",
    "KOSIS_EMP_CHANGE":       "취업자수 전년동기 증감(천명). 0 이하 지속 시 고용 악화",
    "KOSIS_CLI_COINCIDENT":   "동행지수 순환변동치(100기준). 통계청 원천, 약 2개월 지연",
    "KOSIS_CLI_LEADING":      "선행지수 순환변동치(100기준). 6개월 선행 경기 방향 포착",
    "KOSIS_INDPRO_YOY":       "광공업생산지수 전년비(DT_1F02011). 통계청 원천, 익월 말 발표",
    "KOSIS_RETAIL_YOY":       "소매판매 전년동월비(DT_1K41012). 내수 소비 핵심 지표",
    "KOSIS_SERVICE_PROD_YOY": "서비스업생산지수 전년비. 내수 서비스 경기 반영",
}

# 팩트 전용(신호/레짐 미사용) 지표
FACT_ONLY_IDS = {"KOSIS_LABOR_PART"}

# ---------------------------------------------------------------------------
# 비교 기간 설정
# ---------------------------------------------------------------------------
COMPARE_PERIODS = {
    "M": {"prev": 1, "mid": 3,  "yoy": 12},
    "Q": {"prev": 1, "mid": 2,  "yoy": 4},
    "A": {"prev": 1, "mid": 2,  "yoy": 3},
}
MID_LABELS = {"M": "3M전비", "Q": "2Q전비", "A": "2Y전비"}

# 카테고리 정의
CATEGORY_MAP = {
    "01_물가":     ["KOSIS_CPI_YOY", "KOSIS_CORE_CPI_YOY"],
    "02_고용":     ["KOSIS_UNEMP_RATE", "KOSIS_EMP_RATE",
                   "KOSIS_LABOR_PART", "KOSIS_EMP_CHANGE"],
    "03_경기지수": ["KOSIS_CLI_COINCIDENT", "KOSIS_CLI_LEADING"],
    "04_생산":     ["KOSIS_INDPRO_YOY"],
    "05_소비·내수": ["KOSIS_RETAIL_YOY", "KOSIS_SERVICE_PROD_YOY"],
}

RELEASE_LAG_MAP: dict[str, str] = {s[0]: s[9] for s in KOSIS_SERIES}

# 헤드라인 CPI 대비 근원CPI YoY 허용 괴리 (%p)
CORE_CPI_MAX_GAP = 1.5


# ---------------------------------------------------------------------------
# 조회 기간 생성
# ---------------------------------------------------------------------------
def _date_range(prd_se: str) -> tuple[str, str]:
    """YoY 계산에 필요한 최소 13개월+ 확보."""
    today = date.today()
    if prd_se == "M":
        start = date(today.year - 4, 1, 1).strftime("%Y%m")
        end   = today.strftime("%Y%m")
    elif prd_se == "Q":
        start = f"{today.year - 6}01"
        end   = today.strftime("%Y%m")
    else:
        start = str(today.year - 10)
        end   = str(today.year)
    return start, end


# ---------------------------------------------------------------------------
# KOSIS API 호출
# ---------------------------------------------------------------------------
def _kosis_parse_json(text: str) -> object:
    """KOSIS 응답은 키에 따옴표가 없는 비표준 JSON({key:"val"})을 반환.
    정규식으로 표준 JSON 변환 후 파싱한다."""
    fixed = re.sub(r'(?<=[{,\[])\s*(\w+)\s*:', r'"\1":', text)
    return json.loads(fixed)


def fetch_kosis_series(
    org_id: str, tbl_id: str, itm_id: str, obj_l1: str, prd_se: str
) -> list[dict]:
    """KOSIS statisticsParameterData.do 호출 -> 데이터 row 리스트 반환.

    오류 발생 시 [] 반환 (파이프라인 중단 없음).
    """
    if not API_KEY:
        print("  [WARN] KOSIS_API_KEY 환경변수가 설정되지 않았습니다.")
        return []

    start, end = _date_range(prd_se)
    params = {
        "method":     "getList",
        "apiKey":     API_KEY,
        "orgId":      org_id,
        "tblId":      tbl_id,
        "objL1":      obj_l1,
        "itmId":      itm_id,
        "prdSe":      prd_se,
        "startPrdDe": start,
        "endPrdDe":   end,
        "format":     "json",
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=20)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        body = _kosis_parse_json(resp.text)

        # KOSIS 에러 응답: {err:"30", errMsg:"..."}
        if isinstance(body, dict):
            err = body.get("err", "")
            if err:
                print(f"  [WARN] {tbl_id}/{itm_id}: KOSIS 오류 [{err}] {body.get('errMsg', '')}")
                return []
        if isinstance(body, list):
            return body
        return []
    except Exception as exc:
        print(f"  [WARN] {tbl_id}/{itm_id}: {exc}")
        return []


# ---------------------------------------------------------------------------
# 비교값 추출 (전기비 / 중기비 / YoY비)
# ---------------------------------------------------------------------------
def _prev_year_key(t: str) -> str | None:
    """월 형식(YYYYMM) 또는 분기(YYYYQN) 전년 키 반환."""
    if len(t) == 6 and t.isdigit():     # YYYYMM
        return f"{int(t[:4]) - 1}{t[4:]}"
    if len(t) == 7 and "Q" in t:        # YYYYQN (예: 2026Q1)
        return f"{int(t[:4]) - 1}{t[4:]}"
    return None


def get_kosis_comparisons(
    rows: list[dict], prd_se: str, calc_type: str | None,
    c1_filter: str | None = None,
) -> tuple[float | None, str, float | None, float | None, float | None]:
    """rows에서 최신값 및 전기/중기/YoY 비교 대상값을 반환한다.

    c1_filter: 지정 시 C1 필드가 해당 값인 row만 사용 (동일 tblId 내 C1 구분용).
    Returns:
        (cur_val, obs_date, prev_val, mid_val, yoy_val)
    """
    # c1_filter 적용
    if c1_filter:
        rows = [r for r in rows if r.get("C1") == c1_filter]

    # PRD_DE(기간) -> DT(값) 딕셔너리 구성
    valid: dict[str, float] = {}
    for r in rows:
        v = r.get("DT", "")
        t = r.get("PRD_DE", "")
        if v and str(v).strip() not in ("-", " ", "", ".."):
            try:
                valid[t] = float(v)
            except (ValueError, TypeError):
                pass

    if not valid:
        return None, "N/A", None, None, None

    times = sorted(valid.keys())
    n     = len(times)
    cp    = COMPARE_PERIODS.get(prd_se, COMPARE_PERIODS["M"])

    def derived(idx: int) -> float | None:
        """idx 위치 TIME에서 calc_type 변환 후 값 반환."""
        if idx < 0 or idx >= n:
            return None
        t   = times[idx]
        raw = valid[t]

        if calc_type is None:
            return raw
        if calc_type == "yoy_pct":
            pk = _prev_year_key(t)
            pv = valid.get(pk) if pk else None
            if pv and pv != 0:
                return round((raw / pv - 1) * 100, 2)
            return None
        if calc_type == "yoy_diff":
            pk = _prev_year_key(t)
            pv = valid.get(pk) if pk else None
            if pv is not None:
                return round(raw - pv, 1)
            return None
        return None

    latest_idx = n - 1
    cur_val  = derived(latest_idx)
    obs_date = times[latest_idx]
    prev_val = derived(latest_idx - cp["prev"])
    mid_val  = derived(latest_idx - cp["mid"])
    yoy_val  = derived(latest_idx - cp["yoy"])

    return cur_val, obs_date, prev_val, mid_val, yoy_val


# ---------------------------------------------------------------------------
# 데이터 품질 검증
# ---------------------------------------------------------------------------
def _check_data_quality(records: dict) -> dict:
    """6개월 초과 지연 시 None 처리 (경기지수 제외 - 구조적 2개월 지연 정상)."""
    today = date.today()
    # 통계청 경기지수는 구조적으로 약 2개월 지연이 정상 -> 면제
    STALENESS_EXEMPT = {"KOSIS_CLI_COINCIDENT", "KOSIS_CLI_LEADING"}

    for key, meta in records.items():
        if meta.get("value") is None:
            continue
        if key in STALENESS_EXEMPT:
            continue
        period   = str(meta.get("period", "M"))
        obs_date = str(meta.get("date", "N/A"))
        try:
            if period == "M" and len(obs_date) == 6 and obs_date.isdigit():
                obs = date(int(obs_date[:4]), int(obs_date[4:6]), 1)
                months_lag = (today.year - obs.year) * 12 + (today.month - obs.month)
                if months_lag > 6:
                    print(f"  [STALE] {key}: {obs_date} ({months_lag}개월 지연) -> None")
                    records[key]["value"] = None
        except Exception:
            pass

    return records


def _validate_core_cpi(records: dict) -> dict:
    """근원CPI YoY가 헤드라인 CPI와 비정상 괴리 시 None 처리."""
    cpi_meta  = records.get("KOSIS_CPI_YOY")
    core_meta = records.get("KOSIS_CORE_CPI_YOY")
    if not cpi_meta or not core_meta:
        return records
    cpi  = cpi_meta.get("value")
    core = core_meta.get("value")
    if cpi is None or core is None:
        return records
    gap = abs(core - cpi)
    if gap > CORE_CPI_MAX_GAP:
        print(
            f"  [WARN] KOSIS_CORE_CPI_YOY={core}% vs CPI={cpi}% "
            f"(gap {gap:.2f}%p > {CORE_CPI_MAX_GAP}) -> None"
        )
        core_meta["value"] = None
    return records


# ---------------------------------------------------------------------------
# tblId 검증 (최초 실행 시 권장)
# ---------------------------------------------------------------------------
def validate_tblids() -> None:
    """각 KOSIS 시리즈의 tblId/itmId 검증 - 최근 3개월 데이터 반환 여부 확인."""
    if not API_KEY:
        print("[ERROR] KOSIS_API_KEY 환경변수가 설정되지 않았습니다.")
        return

    print("=" * 70)
    print("KOSIS tblId / itmId 검증")
    print("=" * 70)

    today   = date.today()
    end     = today.strftime("%Y%m")
    m       = today.month - 3
    y       = today.year if m > 0 else today.year - 1
    m       = m if m > 0 else m + 12
    start   = f"{y}{m:02d}"

    ok_count, warn_count = 0, 0

    for entry in KOSIS_SERIES:
        sid, org_id, tbl_id, itm_id, obj_l1, prd_se = entry[:6]
        params = {
            "method":     "getList",
            "apiKey":     API_KEY,
            "orgId":      org_id,
            "tblId":      tbl_id,
            "objL1":      obj_l1,
            "itmId":      itm_id,
            "prdSe":      prd_se,
            "startPrdDe": start,
            "endPrdDe":   end,
            "format":     "json",
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=15)
            resp.encoding = "utf-8"
            body = _kosis_parse_json(resp.text)
            c1_filter = entry[10] if len(entry) > 10 else None
            rows = [r for r in body if r.get("C1") == c1_filter] if (c1_filter and isinstance(body, list)) else body
            if isinstance(rows, list) and len(rows) > 0:
                sample = rows[-1].get("DT", "?")
                c1_info = f" c1={c1_filter}" if c1_filter else ""
                print(f"  [OK]   {sid:<30} {tbl_id}/{itm_id}{c1_info} - {len(rows)}행, 최신값={sample}")
                ok_count += 1
            else:
                err_info = (body.get("errMsg", str(body)) if isinstance(body, dict)
                            else "데이터 없음(빈 배열)")
                print(f"  [WARN] {sid:<30} {tbl_id}/{itm_id} - {err_info}")
                warn_count += 1
        except Exception as exc:
            print(f"  [ERROR] {sid:<30} {exc}")
            warn_count += 1
        time.sleep(0.3)

    # CPI vs 근원CPI YoY 교차검증
    print()
    print("─" * 70)
    print("CPI · 근원CPI YoY 교차검증")
    cpi_entry  = next(e for e in KOSIS_SERIES if e[0] == "KOSIS_CPI_YOY")
    core_entry = next(e for e in KOSIS_SERIES if e[0] == "KOSIS_CORE_CPI_YOY")
    cpi_rows   = fetch_kosis_series(*cpi_entry[1:6])
    core_rows  = fetch_kosis_series(*core_entry[1:6])
    cpi_val,  _, _, _, _ = get_kosis_comparisons(cpi_rows,  "M", "yoy_pct", None)
    core_val, _, _, _, _ = get_kosis_comparisons(core_rows, "M", "yoy_pct", None)
    if cpi_val is not None and core_val is not None:
        gap = abs(core_val - cpi_val)
        if gap <= CORE_CPI_MAX_GAP:
            print(f"  [OK]   CPI={cpi_val}% / Core={core_val}% (gap {gap:.2f}%p)")
        else:
            print(
                f"  [WARN] CPI={cpi_val}% / Core={core_val}% (gap {gap:.2f}%p) "
                f"— objL1·itmId 재확인 필요"
            )
            warn_count += 1
    else:
        print(f"  [WARN] CPI/Core YoY 계산 실패 (CPI={cpi_val}, Core={core_val})")
        warn_count += 1

    print()
    print(f"검증 완료: {ok_count}개 OK / {warn_count}개 WARN/ERROR")
    if warn_count > 0:
        print("⚠ WARN 항목은 KOSIS 통합검색(https://kosis.kr)에서")
        print("  올바른 tblId·itmId·objL1 확인 후 KOSIS_SERIES 수정 필요.")
    print("=" * 70)


# ---------------------------------------------------------------------------
# 메인 수집 루프
# ---------------------------------------------------------------------------
def collect_all() -> pd.DataFrame:
    records: dict[str, dict] = {}
    total = len(KOSIS_SERIES)

    for i, entry in enumerate(KOSIS_SERIES, 1):
        sid, org_id, tbl_id, itm_id, obj_l1, prd_se, unit, label, calc_type, release_lag, c1_filter = entry

        c1_info = f" c1={c1_filter}" if c1_filter else ""
        print(f"  [{i:02d}/{total}] {sid:<32} {tbl_id}/{itm_id}{c1_info}"
              + (f" [{calc_type}]" if calc_type else ""))

        rows = fetch_kosis_series(org_id, tbl_id, itm_id, obj_l1, prd_se)
        cur_val, obs_date, prev_val, mid_val, yoy_val = get_kosis_comparisons(
            rows, prd_se, calc_type, c1_filter
        )

        records[sid] = {
            "label":        label,
            "value":        cur_val,
            "date":         obs_date,
            "unit":         unit,
            "stat_code":    f"{tbl_id}_{itm_id}",
            "period":       prd_se,
            "prev_val":     prev_val,
            "mid_val":      mid_val,
            "yoy_val":      yoy_val,
            "release_lag":  release_lag,
        }
        time.sleep(CALL_INTERVAL)

    records = _check_data_quality(records)
    records = _validate_core_cpi(records)

    def _calc_chg(cur: float | None, comp: float | None) -> float | None:
        if cur is None or comp is None:
            return None
        return round(cur - comp, 4)

    rows_out = []
    for key, meta in records.items():
        val      = meta["value"]
        prev_val = meta.get("prev_val")
        mid_val  = meta.get("mid_val")
        yoy_val  = meta.get("yoy_val")
        rows_out.append({
            "series_id": key,
            "label":     meta["label"],
            "value":     val,
            "date":      meta["date"],
            "unit":      meta["unit"],
            "stat_code": meta["stat_code"],
            "period":    meta["period"],
            "chg_prev":  _calc_chg(val, prev_val),
            "chg_mid":   _calc_chg(val, mid_val),
            "chg_yoy":   _calc_chg(val, yoy_val),
            "note":      SERIES_NOTES.get(key, ""),
        })

    return pd.DataFrame(rows_out)


def drop_failed(df: pd.DataFrame) -> pd.DataFrame:
    """수집 실패(value=None/NaN) 지표는 CSV·MD에서 제외."""
    failed = df.loc[df["value"].isna(), "series_id"].tolist()
    if failed:
        print(f"  [DROP] 수집 실패 지표 제외 ({len(failed)}개): {', '.join(failed)}")
    return df.dropna(subset=["value"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 포맷 헬퍼
# ---------------------------------------------------------------------------
def _fmt_val(v: float | None) -> str:
    if v is None:
        return "N/A"
    av = abs(v)
    if av >= 1_000_000:
        return f"{v / 1_000_000:,.2f}M"
    elif av >= 10_000:
        return f"{v:,.0f}"
    else:
        return f"{v:,.4f}".rstrip("0").rstrip(".")


def _fmt_chg(chg: float | None) -> str:
    if chg is None:
        return "-"
    av = abs(chg)
    if av >= 10_000:
        return f"{chg:+,.0f}"
    elif av >= 1:
        return f"{chg:+.2f}"
    else:
        return f"{chg:+.4f}"


def _fmt_date(d: str) -> str:
    if not d or d == "N/A":
        return "N/A"
    d = str(d)
    if len(d) == 6 and d.isdigit():   # YYYYMM -> YYYY-MM
        return f"{d[:4]}-{d[4:]}"
    if len(d) == 8 and d.isdigit():   # YYYYMMDD -> YYYY-MM-DD
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


# ---------------------------------------------------------------------------
# 출력 파일 생성
# ---------------------------------------------------------------------------
def save_csv(df: pd.DataFrame) -> None:
    path = DATA_DIR / "kosis_latest.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  Saved: {path}")


def save_md(df: pd.DataFrame, fetched_at: str) -> None:
    import math as _math

    def _nn(v: object) -> float | None:
        return None if (v is None or (isinstance(v, float) and _math.isnan(v))) else v  # type: ignore[return-value]

    lookup = df.set_index("series_id").to_dict("index")

    lines = [
        "# KOSIS 거시경제 팩트 테이블 (통계청)",
        "",
        f"**업데이트**: {fetched_at} (KST)",
        "",
        "> **출처**: 통계청(orgId=101) - KOSIS Open API",
        "> **[참조전용]**: 신호/레짐 점수 산정에 미사용, 분석 참고 전용",
        "> **KOSIS_CORE_CPI_YOY**: 통계청 농산물·석유류제외(DT_1J22007). "
        "OECD 식품·에너지제외와 정의 상이 — 수치 직접 비교 불가",
        "",
        "---",
        "",
    ]

    for cat, keys in CATEGORY_MAP.items():
        cat_periods = [lookup[k]["period"] for k in keys if k in lookup]
        dom_period  = max(set(cat_periods), key=cat_periods.count) if cat_periods else "M"
        mid_label   = MID_LABELS.get(dom_period, "중기비")

        lines.append(f"## {cat}")
        lines.append("")
        lines.append(
            f"| 시리즈 ID | 지표명 | 최신값 | 단위 | 기준일 | 발표지연 | "
            f"전기비 | {mid_label} | YoY비 |"
        )
        lines.append("|---------|------|------|-----|------|---------|------|------|------|")

        for k in keys:
            if k not in lookup:
                continue
            m        = lookup[k]
            val      = _nn(m["value"])
            chg_prev = _nn(m.get("chg_prev"))
            chg_mid  = _nn(m.get("chg_mid"))
            chg_yoy  = _nn(m.get("chg_yoy"))

            val_str  = _fmt_val(val)
            raw_date = m["date"] if val is not None else "N/A"
            date_str = _fmt_date(raw_date)
            prev_str = _fmt_chg(chg_prev) if val is not None else "-"
            mid_str  = _fmt_chg(chg_mid)  if val is not None else "-"
            yoy_str  = _fmt_chg(chg_yoy)  if val is not None else "-"
            lag      = RELEASE_LAG_MAP.get(k, "-")

            # 2개월 지연 지표에 경고 아이콘 추가
            if "2개월" in lag and val is not None:
                date_str = f"⚠️{date_str}"

            # 팩트 전용 지표 표시
            label_str = m["label"]
            if k in FACT_ONLY_IDS:
                label_str = f"{label_str} [참조전용]"

            lines.append(
                f"| {k} | {label_str} | {val_str} | {m['unit']} | {date_str}"
                f" | {lag} | {prev_str} | {mid_str} | {yoy_str} |"
            )

        lines.append("")

    lines += [
        "---",
        "",
        "> **비교 컬럼 범례**",
        "> - 전기비: 전월차 (% 지표는 %p, 천명은 절대차)",
        "> - 중기비: 3개월전비",
        "> - YoY비: 전년동월비 (calc_type=yoy_pct/yoy_diff 적용 후 변화)",
        "",
        "> **출처**: 통계청 KOSIS Open API",
        "",
    ]

    path = DATA_DIR / "kosis_latest.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="KOSIS 거시경제 지표 수집")
    parser.add_argument(
        "--validate", action="store_true",
        help="tblId/itmId 검증만 실행 (데이터 수집 없음)"
    )
    args = parser.parse_args()

    if args.validate:
        validate_tblids()
        return

    print("=" * 60)
    print("KOSIS 거시경제 지표 수집 시작")
    print(f"API KEY: {'*' * 6}{API_KEY[-4:] if len(API_KEY) > 4 else '(미설정)'}")
    print("=" * 60)

    if not API_KEY:
        print("[ERROR] KOSIS_API_KEY 환경변수가 설정되지 않았습니다.")
        print("        .env 파일에 KOSIS_API_KEY=<your_key> 를 추가하거나")
        print("        환경변수로 설정해주세요.")
        sys.exit(1)

    df = collect_all()
    df = drop_failed(df)

    fetched_at = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")
    save_csv(df)
    save_md(df, fetched_at)

    valid_count = df["value"].notna().sum()
    print(f"\n완료: {valid_count}/{len(df)} 지표 수집 성공")
    print("=" * 60)


if __name__ == "__main__":
    main()
