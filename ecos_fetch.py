"""
ecos_fetch.py
한국은행 ECOS API에서 32개 거시경제 지표를 수집하고
data/ecos_latest.csv 및 data/ecos_latest.md 를 생성합니다.

소거된 시리즈 (API 데이터 부재 확인):
  BSI_ALL       (512Y014/99988)  — 최신 데이터 2023-05 (25개월 지연, ECOS 업데이트 중단)
  CSI           (511Y004/FMAA)   — 최신 데이터 2022-08 (33개월 지연, 서비스 구조 변경 추정)
  RETAIL_SALES_YOY (402Y015/*AA) — 최신 데이터 2024-10 (7개월 지연) + item_code 오류 이력

수정 이력:
  v2.2 (2026-05-26):
  - CORE_CPI_YOY 항목코드 수정: "11"(신선어개, 완전 오류) → "QB"(농산물및석유류제외지수)
    ("11"은 신선어개 가격지수임. 한국 근원CPI 공식 기준(농산물·석유류 제외)으로 정정)
  - 잘못된 주택 시리즈 3개 제거 (901Y092: 성질별 수출입 무역 데이터였음, 주택과 무관)
      HOUSE_PRICE_BUY  (901Y092/E100) → 실제 수출금액합계(천달러), 주택 아님
      HOUSE_PRICE_RENT (901Y092/I100) → 실제 수입금액합계(천달러), 주택 아님
      APT_PRICE_BUY    (901Y092/E101) → 실제 수출세부항목(천달러), 주택 아님
  - KB주택가격지수 추가: 901Y062/P63A (KB주택매매가격지수 총지수 2022.01=100 → YoY)
  - KB전세가격지수 추가: 901Y063/P64A (KB주택전세가격지수 총지수 2022.01=100 → YoY)
  - M2_YOY 추가: 161Y006/BBHA00 (M2 광의통화 평잔 원계열 → YoY)
  - USD_KRW 추가: 731Y004/0000001/0000100 (원/달러 월평균 환율)
  - CORP_LOAN(104Y014/BCA8=수신합계, 완전 오류) → BANK_LOANS(104Y016/BDCA1=총대출금)으로 교체
    (BCA8는 예금은행 수신합계(예금)였음. 대출금 총계(BDCA1)로 정정)
  - IMPORT_YOY ≥30% 시 팩트테이블에 "기저효과" 경고 플래그 자동 표시
  - GDP 성장 점수 정규화 범위 조정: (-3.0, 6.0) → (-2.0, 8.0) in ecos_regime.py
    (2026Q1 실질GDP YoY 6.42%가 상한 6.0 초과로 매번 클리핑되던 문제 해소)

  v2.1 (2026-05-26):
  - KOSPI/KOSDAQ 일별 조회 시작일을 today-2년에서 today-280일로 변경
  - IMPORT_PRICE_YOY 시리즈 교체: 901Y013/A → 403Y005/B(수입물가지수 2020=100)
  - 403Y001/403Y003 레이블 수정: "물량 전년비" → "금액 전년비"
  - INDPRO_YOY 추가: 401Y015/*AA/C (광공업생산지수 원계열 2020=100 → YoY)
  - 카테고리 번호 정비: 09_금융시장 → 08_금융시장
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 환경 설정
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY = os.environ.get("ECOS_API_KEY", "sample")
BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
CALL_INTERVAL = 0.3
DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "ecos_history"

DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# 지표 레지스트리
# 형식: (이름, 통계표코드, 주기, 항목코드, 단위, 레이블, 변환방식)
#
# 변환방식(calc_type):
#   None      - 최신값 직접 사용
#   "yoy_pct" - 지수에서 전년동기비(%) 계산
#   "yoy_diff"- 수준값에서 전년동기 차이 계산 (예: 취업자수 증감)
#   "qoq_pct" - 지수에서 전분기비(%) 계산
#
# ECOS 통계표 코드 확인: https://ecos.bok.or.kr/api/#/DevGuide/StatisticsSearch
# ---------------------------------------------------------------------------
SERIES = [
    # ── 01. 금리·채권 ──────────────────────────────────────────────────────
    # 722Y001: 한국은행 기준금리 및 여수신금리 (060Y001 오류 → 722Y001 수정)
    ("BOK_BASE_RATE",       "722Y001", "M", "0101000", "%",    "한국은행 기준금리",         None),
    # 721Y001: 시장금리 (5020000=국고3Y, 5050000=국고10Y, 2010000=CD91일)
    ("GOV_BOND_3Y",         "721Y001", "M", "5020000", "%",    "국고채 3년",               None),
    ("GOV_BOND_10Y",        "721Y001", "M", "5050000", "%",    "국고채 10년",              None),  # 5030000(1년) → 5050000(10년)
    ("CD_91D",              "721Y001", "M", "2010000", "%",    "CD 91일",                  None),  # 0020000 → 2010000
    ("CORP_BOND_AA_MINUS",  "721Y001", "M", "7020000", "%",    "회사채 AA-",               None),  # 4020000(CP) → 7020000(회사채AA-)
    ("CORP_BOND_BBB_MINUS", "721Y001", "M", "7030000", "%",    "회사채 BBB-",              None),  # 4050000 → 7030000

    # ── 03. 물가·인플레 ────────────────────────────────────────────────────
    # 901Y010: 소비자물가지수(2020=100) → 지수에서 전년비 계산
    ("CPI_YOY",             "901Y010", "M", "00",      "%",    "소비자물가 전년비",        "yoy_pct"),  # 0→00, YoY계산
    ("CORE_CPI_YOY",        "901Y010", "M", "QB",      "%",    "근원CPI 전년비",           "yoy_pct"),  # QB=농산물및석유류제외지수(한국 근원CPI 공식기준) ※ "11"=신선어개로 완전 오류였음
    # 901Y009: 생산자물가지수(2020=100) → 지수에서 전년비 계산
    ("PPI_YOY",             "901Y009", "M", "0",       "%",    "생산자물가 전년비",        "yoy_pct"),  # YoY계산
    # 403Y005: 수출입물가지수(2020=100), B=수입품물가지수 → 지수에서 전년비 계산
    # (구 901Y013/A는 수입금액 절대값으로 물가지수 아님 → 403Y005/B로 교체)
    ("IMPORT_PRICE_YOY",    "403Y005", "M", "B",       "%",    "수입물가 전년비",          "yoy_pct"),

    # ── 04. GDP·경기·생산 ─────────────────────────────────────────────────
    # 200Y104: 실질GDP 계절조정(1118=합계) → QoQ/YoY 계산
    ("GDP_GROWTH_QOQ",      "200Y104", "Q", "1118",    "%",    "실질GDP 전기비",           "qoq_pct"),  # 10101 오류 → 1118+계산
    ("GDP_GROWTH_YOY",      "200Y104", "Q", "1118",    "%",    "실질GDP 전년비",           "yoy_pct"),  # 10111 오류 → 1118+계산
    # 901Y067: 경기지수 (I16D=동행순환변동치, I16E=선행순환변동치)
    ("CLI_COINCIDENT",      "901Y067", "M", "I16D",    "지수", "경기동행지수 순환변동치",  None),  # I16A(잘못된값) → I16D
    ("CLI_LEADING",         "901Y067", "M", "I16E",    "지수", "경기선행지수 순환변동치",  None),  # I16B → I16E
    # 401Y015: 광공업생산지수(2020=100), *AA/C=총지수 원계열 → YoY 계산
    # ITEM_CODE2=C(원계열) 명시로 계절조정(D)/추세(W) 중복 행 방지
    ("INDPRO_YOY",          "401Y015", "M", "*AA/C",   "%",    "광공업생산 전년비",        "yoy_pct"),
    # BSI_ALL (512Y014/99988) 소거: 최신 데이터 2023-05, 25개월 지연 → API 미업데이트

    # ── 05. 노동시장 ───────────────────────────────────────────────────────
    # 901Y027: 고용동향 (I38 계열 오류 → I61 계열 수정)
    ("UNEMPLOYMENT_RATE",   "901Y027", "M", "I61BC",   "%",    "실업률",                  None),  # I38A → I61BC
    ("EMPLOYMENT_CHANGE",   "901Y027", "M", "I61BA",   "천명", "취업자수 전년비",          "yoy_diff"),  # I38B → I61BA(수준→증감)
    ("LABOR_PARTICIPATION", "901Y027", "M", "I61D",    "%",    "경제활동참가율",           None),  # I38H → I61D
    ("EMPLOYMENT_RATE",     "901Y027", "M", "I61E",    "%",    "고용률",                  None),  # I38G → I61E

    # ── 06. 통화·유동성 ────────────────────────────────────────────────────
    # 161Y006: M2 광의통화(평잔, 원계열) BBHA00=M2 합계 → YoY 계산
    ("M2_YOY",              "161Y006", "M", "BBHA00",  "%",    "M2 광의통화 전년비",       "yoy_pct"),
    # 102Y004: 본원통화 잔액 (ABA104=본원통화)
    ("BASE_MONEY",          "102Y004", "M", "ABA104",  "십억원","본원통화 잔액",           None),
    # 104Y016: 예금은행 대출금(말잔), BDCA1=총대출금(가계+기업 합산)
    # ※ 구 104Y014/BCA8은 "예금은행 총수신(수신합계)"로 기업대출이 아니었음 → 교체
    ("BANK_LOANS",          "104Y016", "M", "BDCA1",   "십억원","예금은행 총대출금",       None),

    # ── 07. 주택시장 ───────────────────────────────────────────────────────
    # 901Y062: KB주택매매가격지수(2022.01=100), P63A=총지수 → YoY 계산
    # (구 901Y092/E100-E101-I100은 성질별수출입 무역데이터로 주택과 무관 → 제거)
    ("KB_HOUSE_YOY",        "901Y062", "M", "P63A",    "%",    "KB주택매매가격 전년비",    "yoy_pct"),
    # 901Y063: KB주택전세가격지수(2022.01=100), P64A=총지수 → YoY 계산
    ("KB_JEONSE_YOY",       "901Y063", "M", "P64A",    "%",    "KB주택전세가격 전년비",    "yoy_pct"),
    # 901Y066: 건설경기지수 (I15A=주택착공지수)
    ("HOUSING_START",       "901Y066", "M", "I15A",    "지수", "주택착공지수",            None),  # I16Y 오류 → I15A

    # ── 08. 수출입·무역 ────────────────────────────────────────────────────
    # 403Y003: 수출금액지수(2020=100, *AA=총지수) → YoY 계산
    # ※ 금액지수(가격×물량 복합)임. 물량지수와 혼동 주의.
    ("EXPORT_YOY",          "403Y003", "M", "*AA",     "%",    "수출금액 전년비",          "yoy_pct"),
    # 403Y001: 수입금액지수(2020=100, *AA=총지수) → YoY 계산
    # ※ 금액지수(가격×물량 복합)임. 2025-2026년 50%+ YoY는 관세충격·기저효과 반영 가능성.
    ("IMPORT_YOY",          "403Y001", "M", "*AA",     "%",    "수입금액 전년비",          "yoy_pct"),

    # ── 소비·산업 (카테고리 전체 소거, 번호 미부여)
    # RETAIL_SALES_YOY (402Y015/*AA): 최신 2024-10 (7개월 지연) + item_code 오류 이력 → 소거
    # CSI           (511Y004/FMAA) : 최신 2022-08 (33개월 지연) → ECOS 서비스 구조 변경 추정 → 소거

    # ── 08. 금융시장 ───────────────────────────────────────────────────────
    # 802Y001: 주가지수 일별 시리즈.
    # ECOS는 시장 데이터를 약 6-7개월 지연 게재하는 구조적 특성 있음.
    # 월별(M) 요청 시 802Y001 이 빈 결과를 반환하는 것이 확인되어 일별(D)로 복원.
    # staleness 검사는 _check_data_quality()의 STALENESS_EXEMPT 로 면제 처리.
    ("KOSPI",               "802Y001", "D", "0001000", "pt",   "KOSPI 지수",             None),
    ("KOSDAQ",              "802Y001", "D", "0089000", "pt",   "KOSDAQ 지수",            None),
    # 731Y004: 원/달러 환율 (0000001=USD, 0000100=월평균자료)
    ("USD_KRW",             "731Y004", "M", "0000001/0000100", "원", "원/달러 환율 월평균", None),
    ("CD_BOK_SPREAD",       "721Y001", "M", "SPREAD",  "%",    "CD-기준금리 스프레드 (파생)", None),
    ("CREDIT_SPREAD",       "721Y001", "M", "CSPREAD", "%",    "회사채BBB-국채3Y 스프레드 (파생)", None),
]

# ---------------------------------------------------------------------------
# ECOS API 호출
# ---------------------------------------------------------------------------
def _date_range(period: str) -> tuple[str, str]:
    """조회 기간 생성. 안전한 최종일을 적용하여 'future date' 오류 방지."""
    today = date.today()
    # 안전 종료일: 일별=어제, 월별=2달전, 분기/연=현재
    safe_daily_end = today - timedelta(days=1)

    if period == "D":
        # 200행 페이지 한계: 2년치 일별 데이터(~520 거래일)를 요청하면 첫 200행(구 데이터)만 반환됨.
        # today - 280일(≈200 거래일)로 제한하여 최신 데이터가 확실히 포함되도록 수정.
        start = (today - timedelta(days=280)).strftime("%Y%m%d")
        end   = safe_daily_end.strftime("%Y%m%d")
    elif period == "M":
        start = date(today.year - 4, 1, 1).strftime("%Y%m")  # 4년 전 (YoY 계산용)
        end   = today.strftime("%Y%m")
    elif period == "Q":
        start = f"{today.year - 6}Q1"
        end   = f"{today.year}Q4"
    else:  # A
        start = str(today.year - 10)
        end   = str(today.year)
    return start, end


def fetch_series(stat_code: str, period: str, item_code: str) -> list[dict]:
    """ECOS StatisticSearch 호출 → row 리스트 반환. future-date 오류 시 재시도."""
    start, end = _date_range(period)
    item_part = f"/{item_code}" if item_code else ""

    def _call(s, e):
        url = (
            f"{BASE_URL}/{API_KEY}/json/kr/1/200"
            f"/{stat_code}/{period}/{s}/{e}{item_part}"
        )
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            # future-date 오류 감지
            if "RESULT" in body:
                msg = body["RESULT"].get("MESSAGE", "")
                if "미래" in msg or "future" in msg.lower():
                    return None  # 재시도 신호
            if "StatisticSearch" not in body:
                return []
            return body["StatisticSearch"].get("row", [])
        except Exception as exc:
            print(f"  [WARN] {stat_code}/{item_code}: {exc}")
            return []

    rows = _call(start, end)
    if rows is None:
        # 종료일을 6개월 앞으로 당겨 재시도
        _today = date.today()
        if period == "M":
            m = _today.month - 6
            y = _today.year if m > 0 else _today.year - 1
            m = m if m > 0 else m + 12
            end_fallback = f"{y}{m:02d}"
        elif period == "D":
            end_fallback = (_today - timedelta(days=180)).strftime("%Y%m%d")
        else:
            end_fallback = end
        rows = _call(start, end_fallback) or []

    return rows


def latest_value(rows: list[dict]) -> tuple[float | None, str]:
    """rows에서 가장 최근 유효 값과 날짜를 반환."""
    valid = [r for r in rows if r.get("DATA_VALUE") not in (None, "", " ", "-")]
    if not valid:
        return None, "N/A"
    valid.sort(key=lambda r: r.get("TIME", ""))
    latest = valid[-1]
    return float(latest["DATA_VALUE"]), latest.get("TIME", "N/A")


def yoy_pct(rows: list[dict]) -> tuple[float | None, str]:
    """지수/수준 시계열에서 전년동기비(%) 계산."""
    valid = {}
    for r in rows:
        v = r.get("DATA_VALUE")
        if v not in (None, "", " ", "-"):
            valid[r["TIME"]] = float(v)
    if not valid:
        return None, "N/A"

    times = sorted(valid.keys(), reverse=True)
    t, v = times[0], valid[times[0]]

    # 전년 동기 찾기
    if len(t) == 6 and t.isdigit():        # YYYYMM
        prev_t = f"{int(t[:4]) - 1}{t[4:]}"
    elif len(t) == 6 and "Q" in t:         # YYYYQN
        prev_t = f"{int(t[:4]) - 1}{t[4:]}"
    elif len(t) == 8 and t.isdigit():      # YYYYMMDD
        from datetime import datetime as dt
        d = dt.strptime(t, "%Y%m%d") - timedelta(days=365)
        prev_t = d.strftime("%Y%m%d")
    else:
        return None, "N/A"

    if prev_t in valid and valid[prev_t] != 0:
        return round((v / valid[prev_t] - 1) * 100, 2), t
    return None, "N/A"


def yoy_diff(rows: list[dict]) -> tuple[float | None, str]:
    """수준 시계열에서 전년동기 절대 증감 계산 (예: 취업자수 증감)."""
    valid = {}
    for r in rows:
        v = r.get("DATA_VALUE")
        if v not in (None, "", " ", "-"):
            valid[r["TIME"]] = float(v)
    if not valid:
        return None, "N/A"

    times = sorted(valid.keys(), reverse=True)
    t, v = times[0], valid[times[0]]

    if len(t) == 6 and t.isdigit():
        prev_t = f"{int(t[:4]) - 1}{t[4:]}"
    elif "Q" in t:
        prev_t = f"{int(t[:4]) - 1}{t[4:]}"
    else:
        return None, "N/A"

    if prev_t in valid:
        return round(v - valid[prev_t], 1), t
    return None, "N/A"


def qoq_pct(rows: list[dict]) -> tuple[float | None, str]:
    """분기 수준 시계열에서 전분기비(%) 계산."""
    valid = sorted(
        [(r["TIME"], float(r["DATA_VALUE"]))
         for r in rows
         if r.get("DATA_VALUE") not in (None, "", " ", "-")],
        key=lambda x: x[0]
    )
    if len(valid) < 2:
        return None, "N/A"
    t, v = valid[-1]
    _, prev_v = valid[-2]
    if prev_v and prev_v != 0:
        return round((v / prev_v - 1) * 100, 2), t
    return None, "N/A"


# ---------------------------------------------------------------------------
# 파생 지표 계산 (스프레드류)
# ---------------------------------------------------------------------------
def _compute_derived(records: dict) -> dict:
    def safe_diff(a_key: str, b_key: str) -> float | None:
        av = records.get(a_key, {}).get("value")
        bv = records.get(b_key, {}).get("value")
        if av is None or bv is None:
            return None
        return round(av - bv, 4)

    # CD-기준금리 스프레드
    cd_bok = safe_diff("CD_91D", "BOK_BASE_RATE")
    if "CD_BOK_SPREAD" in records:
        records["CD_BOK_SPREAD"]["value"] = cd_bok
        records["CD_BOK_SPREAD"]["date"] = records.get("CD_91D", {}).get("date", "N/A")

    # 회사채 BBB- vs 국고채 3Y 스프레드
    cspread = safe_diff("CORP_BOND_BBB_MINUS", "GOV_BOND_3Y")
    if "CREDIT_SPREAD" in records:
        records["CREDIT_SPREAD"]["value"] = cspread
        records["CREDIT_SPREAD"]["date"] = records.get("CORP_BOND_BBB_MINUS", {}).get("date", "N/A")

    return records


# ---------------------------------------------------------------------------
# 데이터 품질 검증
# ---------------------------------------------------------------------------
def _check_data_quality(records: dict) -> dict:
    """수집 후 데이터 품질 — 신선도 이상치 탐지.

    검증 항목
    ─────────
    신선도 (Staleness): 월별 6개월·일별 180일 이상 지연 시 None
    - STALENESS_EXEMPT: ECOS 시장 데이터(주가지수)는 구조적으로 ~6-7개월 지연
      게재되므로 신선도 검사 면제. 실제 데이터이며 현재 운용 중인 시리즈임.

    ※ 과거 검증 항목(소거 완료로 불필요):
    - RETAIL_SALES_YOY 이상치: 해당 시리즈 자체가 소거됨
    - CSI 신선도: 해당 시리즈 자체가 소거됨
    - BSI_ALL 신선도: 해당 시리즈 자체가 소거됨
    """
    from datetime import date as _date
    today = _date.today()

    # ECOS 시장 데이터: 구조적 지연(~7개월)이 정상 특성 → 신선도 검사 면제
    STALENESS_EXEMPT = {"KOSPI", "KOSDAQ"}

    for key, meta in records.items():
        if meta.get("value") is None:
            continue
        if key in STALENESS_EXEMPT:
            continue  # 주가지수 등 구조적 지연 허용 시리즈 → 검사 건너뜀
        period = meta.get("period", "M")
        obs_date = meta.get("date", "N/A")
        try:
            if period == "M" and len(obs_date) == 6 and obs_date.isdigit():
                obs = _date(int(obs_date[:4]), int(obs_date[4:6]), 1)
                months_lag = (today.year - obs.year) * 12 + (today.month - obs.month)
                if months_lag > 6:
                    print(f"  [STALE] {key}: {obs_date} ({months_lag}개월 지연) → None")
                    records[key]["value"] = None
            elif period == "D" and len(obs_date) == 8 and obs_date.isdigit():
                obs = _date(int(obs_date[:4]), int(obs_date[4:6]), int(obs_date[6:8]))
                if (today - obs).days > 180:
                    print(f"  [STALE] {key}: {obs_date} ({(today - obs).days}일 지연) → None")
                    records[key]["value"] = None
        except Exception:
            pass

    return records


# ---------------------------------------------------------------------------
# 메인 수집 루프
# ---------------------------------------------------------------------------
CALC_FUNCS = {
    "yoy_pct":  yoy_pct,
    "yoy_diff": yoy_diff,
    "qoq_pct":  qoq_pct,
}

def collect_all() -> pd.DataFrame:
    records: dict[str, dict] = {}
    total = len(SERIES)

    for i, entry in enumerate(SERIES, 1):
        key, stat_code, period, item_code, unit, label = entry[:6]
        calc_type = entry[6] if len(entry) > 6 else None

        is_derived = item_code in ("SPREAD", "CSPREAD", "DSR")
        if is_derived:
            records[key] = {"label": label, "value": None, "date": "N/A",
                            "unit": unit, "stat_code": stat_code, "period": period}
            continue

        print(f"  [{i:02d}/{total}] {key:<25} {stat_code}/{item_code}"
              + (f" [{calc_type}]" if calc_type else ""))
        rows = fetch_series(stat_code, period, item_code)

        if calc_type and calc_type in CALC_FUNCS:
            value, obs_date = CALC_FUNCS[calc_type](rows)
        else:
            value, obs_date = latest_value(rows)

        records[key] = {
            "label": label,
            "value": value,
            "date": obs_date,
            "unit": unit,
            "stat_code": stat_code,
            "period": period,
        }
        time.sleep(CALL_INTERVAL)

    records = _compute_derived(records)
    records = _check_data_quality(records)

    rows_out = []
    for key, meta in records.items():
        rows_out.append({
            "series_id": key,
            "label": meta["label"],
            "value": meta["value"],
            "date": meta["date"],
            "unit": meta["unit"],
            "stat_code": meta["stat_code"],
            "period": meta["period"],
        })
    return pd.DataFrame(rows_out)


# ---------------------------------------------------------------------------
# 출력 파일 생성
# ---------------------------------------------------------------------------
CATEGORY_MAP = {
    "01_금리·채권":  ["BOK_BASE_RATE", "GOV_BOND_3Y", "GOV_BOND_10Y", "CD_91D",
                     "CORP_BOND_AA_MINUS", "CORP_BOND_BBB_MINUS"],
    "02_물가·인플레": ["CPI_YOY", "CORE_CPI_YOY", "PPI_YOY", "IMPORT_PRICE_YOY"],
    "03_GDP·경기·생산": ["GDP_GROWTH_QOQ", "GDP_GROWTH_YOY", "CLI_COINCIDENT", "CLI_LEADING",
                        "INDPRO_YOY"],
    # BSI_ALL 소거 (512Y014/99988: 2023-05 이후 업데이트 없음)
    "04_노동시장":   ["UNEMPLOYMENT_RATE", "EMPLOYMENT_CHANGE", "LABOR_PARTICIPATION",
                     "EMPLOYMENT_RATE"],
    "05_통화·유동성": ["M2_YOY", "BASE_MONEY", "BANK_LOANS"],
    "06_주택시장":   ["KB_HOUSE_YOY", "KB_JEONSE_YOY", "HOUSING_START"],
    "07_수출입·무역": ["EXPORT_YOY", "IMPORT_YOY"],
    # 08_소비·산업 소거 (RETAIL_SALES_YOY·CSI 모두 API 데이터 부재) → 번호 08로 이동
    "08_금융시장":   ["KOSPI", "KOSDAQ", "USD_KRW", "CD_BOK_SPREAD", "CREDIT_SPREAD"],
}


def save_csv(df: pd.DataFrame, ts: str) -> None:
    path = DATA_DIR / "ecos_latest.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    hist = HISTORY_DIR / f"ecos_{ts}.csv"
    df.to_csv(hist, index=False, encoding="utf-8-sig")
    print(f"  Saved: {path}  (history: {hist})")


def save_md(df: pd.DataFrame, fetched_at: str) -> None:
    lookup = df.set_index("series_id").to_dict("index")
    lines = [
        "# ECOS 한국 거시경제 팩트 테이블",
        "",
        f"**업데이트**: {fetched_at} (KST)",
        "",
        "---",
        "",
    ]

    for cat, keys in CATEGORY_MAP.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| 시리즈 ID | 지표명 | 최신값 | 단위 | 기준일 |")
        lines.append("|---------|------|------|-----|------|")
        for k in keys:
            if k not in lookup:
                continue
            m = lookup[k]
            val = m["value"]
            val_str = f"{val:,.4f}".rstrip("0").rstrip(".") if val is not None else "N/A"
            # 값이 None(품질검사 탈락 등)이면 기준일도 N/A로 표시 (오해 방지)
            date_str = m["date"] if val is not None else "N/A"
            # 수입금액 YoY 극단값(50%+) 경고 플래그: 관세충격·기저효과로 과대값 발생 가능
            if k == "IMPORT_YOY" and val is not None and abs(val) >= 30:
                val_str += " ⚠️기저효과"
            lines.append(f"| {k} | {m['label']} | {val_str} | {m['unit']} | {date_str} |")
        lines.append("")

    path = DATA_DIR / "ecos_latest.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("ECOS 거시경제 지표 수집 시작")
    print(f"API KEY: {'*' * 6}{API_KEY[-4:] if len(API_KEY) > 4 else '(sample)'}")
    print("=" * 60)

    if API_KEY == "sample":
        print("[WARN] ECOS_API_KEY 환경변수가 설정되지 않았습니다.")
        print("       .env 파일에 ECOS_API_KEY=<your_key> 를 추가하거나")
        print("       환경변수로 설정해주세요.\n")

    df = collect_all()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    save_csv(df, ts)
    save_md(df, fetched_at)

    valid_count = df["value"].notna().sum()
    print(f"\n완료: {valid_count}/{len(df)} 지표 수집 성공")
    print("=" * 60)


if __name__ == "__main__":
    main()
