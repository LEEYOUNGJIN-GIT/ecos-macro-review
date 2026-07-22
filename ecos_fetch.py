"""
ecos_fetch.py
한국은행 ECOS API에서 23개 거시경제 지표를 수집하고
data/ecos_latest.csv 및 data/ecos_latest.md 를 생성합니다.

KOSIS 재배포 대체 소스로 복원 (v3.2 - GH Actions에서 KOSIS(통계청) 접속이 날짜별로
간헐 차단되는 문제 대응. kosis_fetch.py는 그대로 유지, ECOS는 병행 수집 후
ecos_signals.py/ecos_regime.py 에서 KOSIS 우선·ECOS 대체 순으로 사용):
  CPI_YOY       -> 901Y009/0 (근원CPI는 ECOS 재배포 코드 미검증 — KOSIS_CORE_CPI_YOY 전용 유지)
  INDPRO_YOY    -> 401Y015/*AA/C

KOSIS 이관 완료 시리즈 (v3.0 - kosis_fetch.py 로 이전, 위 2종은 v3.2에서 ECOS 측 재수집 재개):
  CPI_YOY, CORE_CPI_YOY         -> KOSIS_CPI_YOY, KOSIS_CORE_CPI_YOY
  CLI_COINCIDENT, CLI_LEADING   -> KOSIS_CLI_COINCIDENT, KOSIS_CLI_LEADING
  INDPRO_YOY                    -> KOSIS_INDPRO_YOY (DT_1F02011)
  UNEMPLOYMENT_RATE, EMPLOYMENT_CHANGE,
  LABOR_PARTICIPATION, EMPLOYMENT_RATE -> KOSIS_UNEMP_RATE, KOSIS_EMP_CHANGE,
                                          KOSIS_LABOR_PART, KOSIS_EMP_RATE
  EXPORT_YOY, IMPORT_YOY        -> KOSIS 이관 시도 후 v1.2 제거 (관세청 API tblId 미확인)

소거된 시리즈 (API 데이터 부재 확인):
  BSI_ALL       (512Y014/99988)  - 최신 데이터 2023-05 (25개월 지연, ECOS 업데이트 중단)
  CSI           (511Y004/FMAA)   - 최신 데이터 2022-08 (33개월 지연, 서비스 구조 변경 추정)
  RETAIL_SALES_YOY (402Y015/*AA) - 최신 데이터 2024-10 (7개월 지연) + item_code 오류 이력

수정 이력:
  v2.2 (2026-05-26):
  - CORE_CPI_YOY 항목코드 수정: "11"(신선어개, 완전 오류) -> "QB"(농산물및석유류제외지수)
    ("11"은 신선어개 가격지수임. 한국 근원CPI 공식 기준(농산물·석유류 제외)으로 정정)
  - 잘못된 주택 시리즈 3개 제거 (901Y092: 성질별 수출입 무역 데이터였음, 주택과 무관)
      HOUSE_PRICE_BUY  (901Y092/E100) -> 실제 수출금액합계(천달러), 주택 아님
      HOUSE_PRICE_RENT (901Y092/I100) -> 실제 수입금액합계(천달러), 주택 아님
      APT_PRICE_BUY    (901Y092/E101) -> 실제 수출세부항목(천달러), 주택 아님
  - KB주택가격지수 추가: 901Y062/P63A (KB주택매매가격지수 총지수 2022.01=100 -> YoY)
  - KB전세가격지수 추가: 901Y063/P64A (KB주택전세가격지수 총지수 2022.01=100 -> YoY)
  - M2_YOY 추가: 161Y006/BBHA00 (M2 광의통화 평잔 원계열 -> YoY)
  - USD_KRW 추가: 731Y004/0000001/0000100 (원/달러 월평균 환율)
  - CORP_LOAN(104Y014/BCA8=수신합계, 완전 오류) -> BANK_LOANS(104Y016/BDCA1=총대출금)으로 교체
    (BCA8는 예금은행 수신합계(예금)였음. 대출금 총계(BDCA1)로 정정)
  - IMPORT_YOY ≥30% 시 팩트테이블에 "기저효과" 경고 플래그 자동 표시
  - GDP 성장 점수 정규화 범위 조정: (-3.0, 6.0) -> (-2.0, 8.0) in ecos_regime.py
    (2026Q1 실질GDP YoY 6.42%가 상한 6.0 초과로 매번 클리핑되던 문제 해소)

  v3.2 (2026-07-22): CPI_YOY·INDPRO_YOY ECOS 재배포 대체 소스 복원
  - GitHub Actions 실행 환경에서 KOSIS(통계청) API가 날짜별로 간헐 차단되어
    kosis_latest.md 관련 항목이 종종 공백으로 나오는 문제 확인
    (같은 워크플로가 어떤 날은 성공, 어떤 날은 연결 실패 — 지리적/네트워크 차단 추정)
  - CPI_YOY(901Y009/0), INDPRO_YOY(401Y015/*AA/C) 재추가: 둘 다 KOSIS 이관(v3.0) 이전에
    실측 검증됐던 코드를 그대로 복원한 것으로, 신규 추측 코드 아님
  - 근원CPI는 ECOS 재배포 후보를 아직 실측 검증하지 못해(StatisticItemList 조회 필요)
    KOSIS_CORE_CPI_YOY 단일 소스로 유지 — SIG02/SIG03 상세에 그 한계를 명시

  v3.1 (2026-05-27): PPI 통계표 코드 수정 (API 실측 검증)
  - PPI_YOY: 901Y009/0 → 404Y014/*AA
    · 901Y009는 ECOS 명칭상 '소비자물가지수'(CPI) — KOSIS CPI와 index 119.37·YoY 2.57% 동일
    · 404Y014/*AA = '생산자물가지수(기본분류) 총지수' (YoY≈6.9%)

  v3.0 (2026-05-27):
  - KOSIS 이관: 물가(CPI, CORE_CPI), 경기지수(CLI), 생산(INDPRO),
    고용(4개), 수출입(2개) -> 총 11개 SERIES 제거, 21개 유지
  - CATEGORY_MAP 정리: 02_물가(CPI제거), 03_GDP(CLI/INDPRO제거),
    04_노동시장 제거, 07_수출입 제거 -> 06개 카테고리 재편

  v2.5 (2026-05-27):
  - 전기비/중기비/YoY비 비교 컬럼 추가 (fred_fetch.py 패턴 이식)
      · COMPARE_PERIODS: 주기별 비교 인덱스 정의 (D/M/Q/A)
      · get_ecos_comparisons(): 단일 함수로 cur/prev/mid/yoy 값 통합 추출
      · collect_all(): prev_val/mid_val/yoy_val -> chg_prev/chg_mid/chg_yoy 컬럼 추가
      · save_md(): 팩트 테이블에 전기비·중기비·YoY비 컬럼 추가
      · save_csv(): chg_prev/chg_mid/chg_yoy/note 컬럼 추가
  - 기준일 포맷 개선: YYYYMM -> YYYY-MM, YYYYMMDD -> YYYY-MM-DD (MD 출력 전용)
  - 지표별 해석 노트(SERIES_NOTES) 추가 (Claude 분석 컨텍스트 강화)

  v2.1 (2026-05-26):
  - KOSPI/KOSDAQ 일별 조회 시작일을 today-2년에서 today-280일로 변경
  - IMPORT_PRICE_YOY 시리즈 교체: 901Y013/A -> 403Y005/B(수입물가지수 2020=100)
  - 403Y001/403Y003 레이블 수정: "물량 전년비" -> "금액 전년비"
  - INDPRO_YOY 추가: 401Y015/*AA/C (광공업생산지수 원계열 2020=100 -> YoY)
  - 카테고리 번호 정비: 09_금융시장 -> 08_금융시장
"""

import os
import sys
import time
import requests
import pandas as pd
from datetime import datetime, date, timedelta
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
    # 722Y001: 한국은행 기준금리 및 여수신금리 (060Y001 오류 -> 722Y001 수정)
    ("BOK_BASE_RATE",       "722Y001", "M", "0101000", "%",    "한국은행 기준금리",         None),
    # 721Y001: 시장금리 (5020000=국고3Y, 5050000=국고10Y, 2010000=CD91일)
    ("GOV_BOND_3Y",         "721Y001", "M", "5020000", "%",    "국고채 3년",               None),
    ("GOV_BOND_10Y",        "721Y001", "M", "5050000", "%",    "국고채 10년",              None),  # 5030000(1년) -> 5050000(10년)
    ("CD_91D",              "721Y001", "M", "2010000", "%",    "CD 91일",                  None),  # 0020000 -> 2010000
    ("CORP_BOND_AA_MINUS",  "721Y001", "M", "7020000", "%",    "회사채 AA-",               None),  # 4020000(CP) -> 7020000(회사채AA-)
    ("CORP_BOND_BBB_MINUS", "721Y001", "M", "7030000", "%",    "회사채 BBB-",              None),  # 4050000 -> 7030000

    # ── 02. 물가·인플레 ────────────────────────────────────────────────────
    # CORE_CPI_YOY(근원CPI)는 KOSIS 전용 유지 (ECOS 재배포 코드 미검증 — StatisticItemList
    # 조회로 확인 후에만 추가할 것. 근거 없이 하드코딩 금지)
    # 901Y009/0: ECOS '소비자물가지수' 총지수 — v3.1에서 KOSIS CPI(index 119.37·YoY 2.57%)와
    # 동일값 실측 검증됨. KOSIS_CPI_YOY가 GitHub Actions에서 간헐 차단되므로 CPI_YOY(ECOS)를
    # 재배포 대체 소스로 복원 (v3.2). ecos_signals.py/ecos_regime.py는 KOSIS 우선, 실패 시 이 값 사용.
    ("CPI_YOY",              "901Y009", "M", "0",       "%",    "소비자물가지수 전년비(ECOS 재배포)", "yoy_pct"),
    # 404Y014/*AA: 생산자물가지수(기본분류) 총지수 (2020=100) — API 검증 ✅
    ("PPI_YOY",             "404Y014", "M", "*AA",     "%",    "생산자물가 전년비",        "yoy_pct"),
    # 403Y005: 수출입물가지수(2020=100), B=수입품물가지수 -> 지수에서 전년비 계산
    # (구 901Y013/A는 수입금액 절대값으로 물가지수 아님 -> 403Y005/B로 교체)
    ("IMPORT_PRICE_YOY",    "403Y005", "M", "B",       "%",    "수입물가 전년비",          "yoy_pct"),

    # ── 03. GDP ───────────────────────────────────────────────────────────
    # CLI_COINCIDENT, CLI_LEADING -> KOSIS 전용 유지 (ECOS 직접 대체 없음)
    # BSI_ALL (512Y014/99988) 소거: 최신 데이터 2023-05, 25개월 지연 -> API 미업데이트
    # 200Y104: 실질GDP 계절조정(1118=합계) -> QoQ/YoY 계산
    ("GDP_GROWTH_QOQ",      "200Y104", "Q", "1118",    "%",    "실질GDP 전기비",           "qoq_pct"),  # 10101 오류 -> 1118+계산
    ("GDP_GROWTH_YOY",      "200Y104", "Q", "1118",    "%",    "실질GDP 전년비",           "yoy_pct"),  # 10111 오류 -> 1118+계산
    # 401Y015/*AA/C: 광공업생산지수 원계열(2020=100) -> YoY. v2.1에서 API 실측 검증 후
    # v3.0에서 KOSIS_INDPRO_YOY로 이관됐던 시리즈. KOSIS 간헐 차단 대응으로 재배포 대체 소스 복원(v3.2).
    ("INDPRO_YOY",          "401Y015", "M", "*AA/C",   "%",    "광공업생산지수 전년비(ECOS 재배포)", "yoy_pct"),

    # 04_노동시장 -> KOSIS 이관 (UNEMPLOYMENT_RATE, EMPLOYMENT_CHANGE,
    #   LABOR_PARTICIPATION, EMPLOYMENT_RATE -> kosis_fetch.py 참조)

    # ── 04. 통화·유동성 ────────────────────────────────────────────────────
    # 161Y006: M2 광의통화(평잔, 원계열) BBHA00=M2 합계 -> YoY 계산
    ("M2_YOY",              "161Y006", "M", "BBHA00",  "%",    "M2 광의통화 전년비",       "yoy_pct"),
    # 102Y004: 본원통화 잔액 (ABA104=본원통화)
    ("BASE_MONEY",          "102Y004", "M", "ABA104",  "십억원","본원통화 잔액",           None),
    # 104Y016: 예금은행 대출금(말잔), BDCA1=총대출금(가계+기업 합산)
    # ※ 구 104Y014/BCA8은 "예금은행 총수신(수신합계)"로 기업대출이 아니었음 -> 교체
    ("BANK_LOANS",          "104Y016", "M", "BDCA1",   "십억원","예금은행 총대출금",       None),

    # ── 05. 주택시장 ───────────────────────────────────────────────────────
    # 901Y062: KB주택매매가격지수(2022.01=100), P63A=총지수 -> YoY 계산
    # (구 901Y092/E100-E101-I100은 성질별수출입 무역데이터로 주택과 무관 -> 제거)
    ("KB_HOUSE_YOY",        "901Y062", "M", "P63A",    "%",    "KB주택매매가격 전년비",    "yoy_pct"),
    # 901Y063: KB주택전세가격지수(2022.01=100), P64A=총지수 -> YoY 계산
    ("KB_JEONSE_YOY",       "901Y063", "M", "P64A",    "%",    "KB주택전세가격 전년비",    "yoy_pct"),
    # 901Y066: 건설경기지수 (I15A=주택착공지수)
    ("HOUSING_START",       "901Y066", "M", "I15A",    "지수", "주택착공지수",            None),  # I16Y 오류 -> I15A

    # 07_수출입·무역 -> KOSIS 이관 (EXPORT_YOY, IMPORT_YOY -> kosis_fetch.py 참조)
    # ── 소비·산업 (카테고리 전체 소거, 번호 미부여)
    # RETAIL_SALES_YOY (402Y015/*AA): 최신 2024-10 (7개월 지연) + item_code 오류 이력 -> 소거
    # CSI           (511Y004/FMAA) : 최신 2022-08 (33개월 지연) -> ECOS 서비스 구조 변경 추정 -> 소거

    # ── 06. 금융시장 ───────────────────────────────────────────────────────
    # 802Y001: 주가지수 일별 시리즈. 월별(M) 요청 시 빈 결과 → 일별(D) 사용.
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
    """ECOS StatisticSearch 호출 -> row 리스트 반환. future-date 오류 시 재시도."""
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
            if "RESULT" in body:
                code = body["RESULT"].get("CODE", "")
                msg  = body["RESULT"].get("MESSAGE", "")
                if "미래" in msg or "future" in msg.lower():
                    return None  # 재시도 신호
                # API 키 오류·권한 오류·쿼터 초과 등 명시적 실패
                if code and not str(code).startswith("200"):
                    print(f"  [WARN] {stat_code}/{item_code}: ECOS 오류 [{code}] {msg}")
                    return []
            if "StatisticSearch" not in body:
                print(f"  [WARN] {stat_code}/{item_code}: 응답에 StatisticSearch 키 없음")
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

    def _copy_comparisons(target_key: str, a_key: str, b_key: str, date_key: str) -> None:
        """파생 스프레드의 전기/중기/YoY 비교값을 구성요소 차이로 계산."""
        if target_key not in records:
            return
        meta = records[target_key]
        for field in ("prev_val", "mid_val", "yoy_val"):
            meta[field] = safe_diff_field(records, a_key, b_key, field)
        meta["date"] = records.get(date_key, {}).get("date", "N/A")

    def safe_diff_field(recs: dict, a_key: str, b_key: str, field: str) -> float | None:
        av = recs.get(a_key, {}).get(field)
        bv = recs.get(b_key, {}).get(field)
        if av is None or bv is None:
            return None
        return round(av - bv, 4)

    # CD-기준금리 스프레드
    cd_bok = safe_diff("CD_91D", "BOK_BASE_RATE")
    if "CD_BOK_SPREAD" in records:
        records["CD_BOK_SPREAD"]["value"] = cd_bok
        _copy_comparisons("CD_BOK_SPREAD", "CD_91D", "BOK_BASE_RATE", "CD_91D")

    # 회사채 BBB- vs 국고채 3Y 스프레드
    cspread = safe_diff("CORP_BOND_BBB_MINUS", "GOV_BOND_3Y")
    if "CREDIT_SPREAD" in records:
        records["CREDIT_SPREAD"]["value"] = cspread
        _copy_comparisons("CREDIT_SPREAD", "CORP_BOND_BBB_MINUS", "GOV_BOND_3Y", "CORP_BOND_BBB_MINUS")

    return records


# ---------------------------------------------------------------------------
# 데이터 품질 검증
# ---------------------------------------------------------------------------
def _check_data_quality(records: dict) -> dict:
    """수집 후 데이터 품질 - 신선도 이상치 탐지.

    검증 항목
    ─────────
    신선도 (Staleness): 월별 6개월·일별 180일 이상 지연 시 None
    - RETAIL_SALES_YOY 이상치: 해당 시리즈 자체가 소거됨
    - CSI 신선도: 해당 시리즈 자체가 소거됨
    - BSI_ALL 신선도: 해당 시리즈 자체가 소거됨
    """
    from datetime import date as _date
    today = _date.today()

    for key, meta in records.items():
        if meta.get("value") is None:
            continue
        period = meta.get("period", "M")
        obs_date = meta.get("date", "N/A")
        try:
            if period == "M" and len(obs_date) == 6 and obs_date.isdigit():
                obs = _date(int(obs_date[:4]), int(obs_date[4:6]), 1)
                months_lag = (today.year - obs.year) * 12 + (today.month - obs.month)
                if months_lag > 6:
                    print(f"  [STALE] {key}: {obs_date} ({months_lag}개월 지연) -> None")
                    records[key]["value"] = None
            elif period == "D" and len(obs_date) == 8 and obs_date.isdigit():
                obs = _date(int(obs_date[:4]), int(obs_date[4:6]), int(obs_date[6:8]))
                if (today - obs).days > 180:
                    print(f"  [STALE] {key}: {obs_date} ({(today - obs).days}일 지연) -> None")
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

# ---------------------------------------------------------------------------
# 비교 기간 설정 (전기비 / 중기비 / YoY비)
# ---------------------------------------------------------------------------
COMPARE_PERIODS = {
    "D": {"prev": 1,  "mid": 20, "yoy": 252},  # 전일 / 4주(20영업일) / 1년
    "M": {"prev": 1,  "mid": 3,  "yoy": 12},   # 전월 / 3개월 / 1년
    "Q": {"prev": 1,  "mid": 2,  "yoy": 4},    # 전분기 / 2분기 / 1년
    "A": {"prev": 1,  "mid": 2,  "yoy": 3},    # 전년 / 2년전 / 3년전
}

MID_LABELS = {"D": "4W전비", "M": "3M전비", "Q": "2Q전비", "A": "2Y전비"}

# ---------------------------------------------------------------------------
# 지표별 해석 노트 (Claude 분석 컨텍스트 강화)
# ---------------------------------------------------------------------------
SERIES_NOTES = {
    # ── 금리·채권 ──
    "BOK_BASE_RATE":       "중립금리 2.5% 추정. 인하/인상 기조 전환 핵심 지표",
    "GOV_BOND_3Y":         "단기 정책금리 기대 반영. 기준금리와 스프레드 확대 시 유동성 위험",
    "GOV_BOND_10Y":        "글로벌 장기 기준금리. 5% 이상 시 재정·기업 부담 가중",
    "CD_91D":              "단기 자금시장 유동성 지표. 기준금리 괴리 확대 시 경계",
    "CORP_BOND_AA_MINUS":  "[참조전용] 우량 기업 조달비용. 국채 대비 스프레드 확대 시 신용 위험 상승",
    "CORP_BOND_BBB_MINUS": "투기등급 기업 조달비용. CREDIT_SPREAD와 함께 신용 리스크 점검",
    # ── 물가 (ECOS 잔류분) ──
    "CPI_YOY":             "[재배포 대체] KOSIS_CPI_YOY 실패 시 대체 소스. 근원CPI는 KOSIS 전용(ECOS 미검증)",
    "PPI_YOY":             "기업 비용 압박 선행지표. CPI 3~6개월 선행 가능성",
    "IMPORT_PRICE_YOY":    "수입 비용 충격. 환율·원자재 복합 영향. 급등 시 소비자물가 전가 경계",
    # ── GDP ──
    "GDP_GROWTH_QOQ":      "[참조전용] 전분기비 성장률. 2분기 연속 음수 시 기술적 침체",
    "GDP_GROWTH_YOY":      "전년비 성장률. 잠재성장률(약 2%) 대비 위치 파악",
    "INDPRO_YOY":          "[재배포 대체] KOSIS_INDPRO_YOY 실패 시 대체 소스. 광공업생산 모멘텀(SIG09)",
    # ── 통화·유동성 ──
    "M2_YOY":              "[참조전용] 광의통화 전년비. 음수 시 디플레 우려, 10% 이상 시 과잉 유동성",
    "BASE_MONEY":          "[참조전용] 본원통화 잔액. 통화 공급 기초. YoY 감소 시 긴축 기조",
    "BANK_LOANS":          "[참조전용] 예금은행 총대출금. 증가=신용 확장, 감소=긴축 압력",
    # ── 주택시장 ──
    "KB_HOUSE_YOY":        "KB주택매매가격 전년비. 부동산 경기·자산효과 소비 연동",
    "KB_JEONSE_YOY":       "전세가격 전년비. 주거비 부담 및 전세-매매 갭 모니터링",
    "HOUSING_START":       "주택착공지수. 건설경기 선행. 금리 인상 후 6~12개월 후행",
    # ── 금융시장 ──
    "KOSPI":               "KOSPI 지수(ECOS 802Y001 일별). SIG12 전용 - 레짐 성장 제외",
    "KOSDAQ":              "[참조전용] KOSDAQ 지수(ECOS 802Y001 일별). 추세·방향성 참고",
    "USD_KRW":             "[참조전용] 원/달러 환율 월평균. 상승=원화 약세. 수입물가·외화부채 압박",
    "CD_BOK_SPREAD":       "CD-기준금리 스프레드(파생). 단기 유동성 프리미엄 확대 시 경계",
    "CREDIT_SPREAD":       "회사채BBB-국채3Y 스프레드(파생). 기업 신용 리스크 핵심 지표",
}


# ---------------------------------------------------------------------------
# 포맷 헬퍼
# ---------------------------------------------------------------------------
def fmt_val(v: float | None) -> str:
    """숫자를 가독성 있게 포맷."""
    if v is None:
        return "N/A"
    av = abs(v)
    if av >= 1_000_000:
        return f"{v / 1_000_000:,.2f}M"
    elif av >= 10_000:
        return f"{v:,.0f}"
    else:
        return f"{v:,.4f}".rstrip("0").rstrip(".")


def fmt_chg(chg: float | None) -> str:
    """변화량을 부호 포함 문자열로 포맷."""
    if chg is None:
        return "-"
    av = abs(chg)
    if av >= 10_000:
        return f"{chg:+,.0f}"
    elif av >= 1:
        return f"{chg:+.2f}"
    else:
        return f"{chg:+.4f}"


def calc_chg(cur: float | None, comp: float | None) -> float | None:
    """현재값과 비교값의 차이 계산."""
    if cur is None or comp is None:
        return None
    return round(cur - comp, 4)


def fmt_date(d: str) -> str:
    """ECOS 날짜 형식 -> 가독성 있는 형식 변환 (MD 출력 전용)."""
    if not d or d == "N/A":
        return "N/A"
    d = str(d)
    if len(d) == 6 and d.isdigit():    # YYYYMM -> YYYY-MM
        return f"{d[:4]}-{d[4:]}"
    if len(d) == 8 and d.isdigit():    # YYYYMMDD -> YYYY-MM-DD
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d                           # YYYYQN 등은 그대로


# ---------------------------------------------------------------------------
# 통합 비교값 추출 (전기 / 중기 / YoY)
# ---------------------------------------------------------------------------
def get_ecos_comparisons(
    rows: list[dict], period: str, calc_type: str | None
) -> tuple[float | None, str, float | None, float | None, float | None]:
    """rows에서 최신값 및 전기/중기/YoY 비교 대상값을 반환한다.

    Returns:
        (cur_val, obs_date, prev_val, mid_val, yoy_val)
        · calc_type 변환 후 각 시점의 값을 반환
        · 비교점 데이터 부족 시 해당 항목 None
    """
    valid: dict[str, float] = {}
    for r in rows:
        v = r.get("DATA_VALUE")
        if v not in (None, "", " ", "-"):
            valid[r["TIME"]] = float(v)

    if not valid:
        return None, "N/A", None, None, None

    times = sorted(valid.keys())
    n = len(times)
    cp = COMPARE_PERIODS.get(period, COMPARE_PERIODS["M"])

    def prev_year_key(t: str) -> str | None:
        if len(t) == 6 and t.isdigit():    # YYYYMM
            return f"{int(t[:4]) - 1}{t[4:]}"
        if "Q" in t:                       # YYYYQN (ECOS: 2026Q1, 6자)
            return f"{int(t[:4]) - 1}{t[4:]}"
        if len(t) == 8 and t.isdigit():    # YYYYMMDD
            from datetime import datetime as dt
            d = dt.strptime(t, "%Y%m%d") - timedelta(days=365)
            return d.strftime("%Y%m%d")
        return None

    def derived(idx: int) -> float | None:
        """idx 위치 TIME에서 calc_type 변환 후 값 반환."""
        if idx < 0 or idx >= n:
            return None
        t   = times[idx]
        raw = valid[t]

        if calc_type is None:
            return raw
        if calc_type == "yoy_pct":
            pk = prev_year_key(t)
            pv = valid.get(pk) if pk else None
            if pv and pv != 0:
                return round((raw / pv - 1) * 100, 2)
            return None
        if calc_type == "yoy_diff":
            pk = prev_year_key(t)
            pv = valid.get(pk) if pk else None
            if pv is not None:
                return round(raw - pv, 1)
            return None
        if calc_type == "qoq_pct":
            if idx > 0:
                prev_raw = valid[times[idx - 1]]
                if prev_raw and prev_raw != 0:
                    return round((raw / prev_raw - 1) * 100, 2)
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
# 메인 수집 루프
# ---------------------------------------------------------------------------
def collect_all() -> pd.DataFrame:
    records: dict[str, dict] = {}
    total = len(SERIES)

    for i, entry in enumerate(SERIES, 1):
        key, stat_code, period, item_code, unit, label = entry[:6]
        calc_type = entry[6] if len(entry) > 6 else None

        is_derived = item_code in ("SPREAD", "CSPREAD")
        if is_derived:
            records[key] = {
                "label": label, "value": None, "date": "N/A",
                "unit": unit, "stat_code": stat_code, "period": period,
                "prev_val": None, "mid_val": None, "yoy_val": None,
            }
            continue

        print(f"  [{i:02d}/{total}] {key:<25} {stat_code}/{item_code}"
              + (f" [{calc_type}]" if calc_type else ""))
        rows = fetch_series(stat_code, period, item_code)

        value, obs_date, prev_val, mid_val, yoy_val = get_ecos_comparisons(
            rows, period, calc_type
        )

        records[key] = {
            "label":    label,
            "value":    value,
            "date":     obs_date,
            "unit":     unit,
            "stat_code": stat_code,
            "period":   period,
            "prev_val": prev_val,
            "mid_val":  mid_val,
            "yoy_val":  yoy_val,
        }
        time.sleep(CALL_INTERVAL)

    records = _compute_derived(records)
    records = _check_data_quality(records)

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
            "chg_prev":  calc_chg(val, prev_val),
            "chg_mid":   calc_chg(val, mid_val),
            "chg_yoy":   calc_chg(val, yoy_val),
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
# 출력 파일 생성
# ---------------------------------------------------------------------------
CATEGORY_MAP = {
    # 23개 ECOS 잔류 지표 - 물가/경기/고용/수출입 -> kosis_fetch.py 이관
    "01_금리·채권":   ["BOK_BASE_RATE", "GOV_BOND_3Y", "GOV_BOND_10Y", "CD_91D",
                      "CORP_BOND_AA_MINUS", "CORP_BOND_BBB_MINUS"],
    "02_물가":        ["CPI_YOY", "PPI_YOY", "IMPORT_PRICE_YOY"],
    # CORE_CPI_YOY -> KOSIS 전용 (ECOS 재배포 코드 미검증)
    # CLI_COINCIDENT, CLI_LEADING -> KOSIS 전용 (ECOS 직접 대체 없음)
    # BSI_ALL 소거 (2023-05 이후 업데이트 없음)
    "03_GDP":         ["GDP_GROWTH_QOQ", "GDP_GROWTH_YOY", "INDPRO_YOY"],
    # 04_노동시장 -> KOSIS 이관 (UNEMPLOYMENT_RATE 등 4개)
    # 05_수출입 -> KOSIS 이관 (EXPORT_YOY, IMPORT_YOY)
    # CSI/RETAIL_SALES_YOY 소거 (API 데이터 부재)
    "04_통화·유동성":  ["M2_YOY", "BASE_MONEY", "BANK_LOANS"],
    "05_주택시장":    ["KB_HOUSE_YOY", "KB_JEONSE_YOY", "HOUSING_START"],
    "06_금융시장":    ["KOSPI", "KOSDAQ", "USD_KRW", "CD_BOK_SPREAD", "CREDIT_SPREAD"],
}


def save_csv(df: pd.DataFrame, ts: str) -> None:
    path = DATA_DIR / "ecos_latest.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    hist = HISTORY_DIR / f"ecos_{ts}.csv"
    df.to_csv(hist, index=False, encoding="utf-8-sig")
    print(f"  Saved: {path}  (history: {hist})")


def save_md(df: pd.DataFrame, fetched_at: str) -> None:
    import math as _math

    def _nn(v: object) -> float | None:
        """pandas NaN -> None 변환."""
        return None if (v is None or (isinstance(v, float) and _math.isnan(v))) else v  # type: ignore[return-value]

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
        # 카테고리 내 대표 주기로 중기비 레이블 결정
        cat_periods = [lookup[k]["period"] for k in keys if k in lookup]
        dom_period  = max(set(cat_periods), key=cat_periods.count) if cat_periods else "M"
        mid_label   = MID_LABELS.get(dom_period, "중기비")

        lines.append(f"## {cat}")
        lines.append("")
        lines.append(f"| 시리즈 ID | 지표명 | 최신값 | 단위 | 기준일 | 전기비 | {mid_label} | YoY비 |")
        lines.append("|---------|------|------|-----|------|------|------|------|")
        for k in keys:
            if k not in lookup:
                continue
            m        = lookup[k]
            val      = _nn(m["value"])
            chg_prev = _nn(m.get("chg_prev"))
            chg_mid  = _nn(m.get("chg_mid"))
            chg_yoy  = _nn(m.get("chg_yoy"))

            val_str  = fmt_val(val)
            # 값이 None(품질검사 탈락 등)이면 기준일·비교값도 N/A·"-" 로 표시
            raw_date = m["date"] if val is not None else "N/A"
            date_str = fmt_date(raw_date)
            prev_str = fmt_chg(chg_prev) if val is not None else "-"
            mid_str  = fmt_chg(chg_mid)  if val is not None else "-"
            yoy_str  = fmt_chg(chg_yoy)  if val is not None else "-"

            # 수입물가 YoY 극단값(25%+) 경고 플래그
            if k == "IMPORT_PRICE_YOY" and val is not None and abs(val) >= 25:
                val_str += " ⚠️기저효과"

            lines.append(
                f"| {k} | {m['label']} | {val_str} | {m['unit']} | {date_str}"
                f" | {prev_str} | {mid_str} | {yoy_str} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "> **플래그 범례**",
        "> - ⚠️기저효과: 수입물가 YoY ≥25%, 관세충격·기저효과로 과대값 가능",
        "",
        "> **비교 컬럼 범례**",
        "> - 전기비: M=전월차, D=전일차, Q=전분기차 (원계열 수준->절대차, YoY/QoQ->%p 차이)",
        "> - 중기비: M=3개월전비, D=4주전비, Q=2분기전비",
        "> - YoY비: M=전년동월비, D=전년동일비, Q=전년동분기비",
        "",
    ]

    path = DATA_DIR / "ecos_latest.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("ECOS 거시경제 지표 수집 시작 (21개 - KOSIS 이관 후)")
    print(f"API KEY: {'*' * 6}{API_KEY[-4:] if len(API_KEY) > 4 else '(sample)'}")
    print("=" * 60)

    if API_KEY == "sample":
        print("[ERROR] ECOS_API_KEY 환경변수가 설정되지 않았습니다.")
        print("        .env 파일에 ECOS_API_KEY=<your_key> 를 추가하거나")
        print("        환경변수로 설정해주세요.")
        sys.exit(1)

    df = collect_all()
    df = drop_failed(df)

    ts = datetime.now(_KST).strftime("%Y%m%d_%H%M%S")
    fetched_at = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")

    save_csv(df, ts)
    save_md(df, fetched_at)

    valid_count = df["value"].notna().sum()
    print(f"\n완료: {valid_count}/{len(df)} 지표 수집 성공")
    print("=" * 60)


if __name__ == "__main__":
    main()
