"""
ecos_fetch.py
한국은행 ECOS API에서 30개 거시경제 지표를 수집하고
data/ecos_latest.csv 및 data/ecos_latest.md 를 생성합니다.

소거된 시리즈 (API 데이터 부재 확인):
  BSI_ALL       (512Y014/99988)  — 최신 데이터 2023-05 (25개월 지연, ECOS 업데이트 중단)
  CSI           (511Y004/FMAA)   — 최신 데이터 2022-08 (33개월 지연, 서비스 구조 변경 추정)
  RETAIL_SALES_YOY (402Y015/*AA) — 최신 데이터 2024-10 (7개월 지연) + item_code 오류 이력
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
    ("CORE_CPI_YOY",        "901Y010", "M", "11",      "%",    "근원CPI 전년비",           "yoy_pct"),  # 근원물가지수 → YoY계산
    # 901Y009: 생산자물가지수(2020=100) → 지수에서 전년비 계산
    ("PPI_YOY",             "901Y009", "M", "0",       "%",    "생산자물가 전년비",        "yoy_pct"),  # YoY계산
    # 901Y013: 수입금액 지수 → 지수에서 전년비 계산
    ("IMPORT_PRICE_YOY",    "901Y013", "M", "A",       "%",    "수입금액 전년비",          "yoy_pct"),  # 수입금액지수 YoY

    # ── 04. GDP·경기 ───────────────────────────────────────────────────────
    # 200Y104: 실질GDP 계절조정(1118=합계) → QoQ/YoY 계산
    ("GDP_GROWTH_QOQ",      "200Y104", "Q", "1118",    "%",    "실질GDP 전기비",           "qoq_pct"),  # 10101 오류 → 1118+계산
    ("GDP_GROWTH_YOY",      "200Y104", "Q", "1118",    "%",    "실질GDP 전년비",           "yoy_pct"),  # 10111 오류 → 1118+계산
    # 901Y067: 경기지수 (I16D=동행순환변동치, I16E=선행순환변동치)
    ("CLI_COINCIDENT",      "901Y067", "M", "I16D",    "지수", "경기동행지수 순환변동치",  None),  # I16A(잘못된값) → I16D
    ("CLI_LEADING",         "901Y067", "M", "I16E",    "지수", "경기선행지수 순환변동치",  None),  # I16B → I16E
    # BSI_ALL (512Y014/99988) 소거: 최신 데이터 2023-05, 25개월 지연 → API 미업데이트

    # ── 05. 노동시장 ───────────────────────────────────────────────────────
    # 901Y027: 고용동향 (I38 계열 오류 → I61 계열 수정)
    ("UNEMPLOYMENT_RATE",   "901Y027", "M", "I61BC",   "%",    "실업률",                  None),  # I38A → I61BC
    ("EMPLOYMENT_CHANGE",   "901Y027", "M", "I61BA",   "천명", "취업자수 전년비",          "yoy_diff"),  # I38B → I61BA(수준→증감)
    ("LABOR_PARTICIPATION", "901Y027", "M", "I61D",    "%",    "경제활동참가율",           None),  # I38H → I61D
    ("EMPLOYMENT_RATE",     "901Y027", "M", "I61E",    "%",    "고용률",                  None),  # I38G → I61E

    # ── 06. 통화·유동성 ────────────────────────────────────────────────────
    # 102Y004: 본원통화 잔액 (ABA104=본원통화)
    ("BASE_MONEY",          "102Y004", "M", "ABA104",  "십억원","본원통화 잔액",           None),
    # 104Y014: 기업대출 (BCA8=합계)
    ("CORP_LOAN",           "104Y014", "M", "BCA8",    "십억원","기업대출 잔액",           None),

    # ── 07. 주택시장 ───────────────────────────────────────────────────────
    # 901Y092: 부동산거래 금액(매매/임대) — 가격지수 아님, 금액 데이터
    ("HOUSE_PRICE_BUY",     "901Y092", "M", "E100",    "백만원","주택매매금액 합계",       None),  # P63AA 오류 → E100(금액) / 단위: 백만원(십억원 아님)
    ("HOUSE_PRICE_RENT",    "901Y092", "M", "I100",    "백만원","주택임대금액 합계",       None),  # P63BA 오류 → I100(금액) / 단위: 백만원
    ("APT_PRICE_BUY",       "901Y092", "M", "E101",    "백만원","아파트매매금액",          None),  # P63AD 오류 → E101(금액) / 단위: 백만원
    # 901Y066: 건설경기지수 (I15A=주택착공지수)
    ("HOUSING_START",       "901Y066", "M", "I15A",    "지수", "주택착공지수",            None),  # I16Y 오류 → I15A

    # ── 08. 수출입·무역 ────────────────────────────────────────────────────
    # 403Y003: 수출물량지수(*AA=총지수) → YoY 계산
    ("EXPORT_YOY",          "403Y003", "M", "*AA",     "%",    "수출물량 전년비",          "yoy_pct"),
    # 403Y001: 수입물량지수(*AA=총지수) → YoY 계산
    # ※ 주의: 2025-2026년 관세 충격·기저효과로 YoY 50%+ 극단값 발생 가능.
    #   수치가 경제적으로 과도해 보이더라도 API 원본 그대로 표시 (실제 데이터 가능성).
    #   item_code *AA 오류 여부는 ECOS 통계표 403Y001 항목 코드 재확인 필요.
    ("IMPORT_YOY",          "403Y001", "M", "*AA",     "%",    "수입물량 전년비",          "yoy_pct"),

    # ── 09. 소비·산업 ── (카테고리 전체 소거)
    # RETAIL_SALES_YOY (402Y015/*AA): 최신 2024-10 (7개월 지연) + item_code 오류 이력 → 소거
    # CSI           (511Y004/FMAA) : 최신 2022-08 (33개월 지연) → ECOS 서비스 구조 변경 추정 → 소거

    # ── 10. 금융시장 ───────────────────────────────────────────────────────
    # 802Y001: 주가지수 일별 시리즈.
    # ECOS는 시장 데이터를 약 6-7개월 지연 게재하는 구조적 특성 있음.
    # 월별(M) 요청 시 802Y001 이 빈 결과를 반환하는 것이 확인되어 일별(D)로 복원.
    # staleness 검사는 _check_data_quality()의 STALENESS_EXEMPT 로 면제 처리.
    ("KOSPI",               "802Y001", "D", "0001000", "pt",   "KOSPI 지수",             None),
    ("KOSDAQ",              "802Y001", "D", "0089000", "pt",   "KOSDAQ 지수",            None),
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
        start = date(today.year - 2, 1, 1).strftime("%Y%m%d")
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
    "03_GDP·경기":  ["GDP_GROWTH_QOQ", "GDP_GROWTH_YOY", "CLI_COINCIDENT", "CLI_LEADING"],
    # BSI_ALL 소거 (512Y014/99988: 2023-05 이후 업데이트 없음)
    "04_노동시장":   ["UNEMPLOYMENT_RATE", "EMPLOYMENT_CHANGE", "LABOR_PARTICIPATION",
                     "EMPLOYMENT_RATE"],
    "05_통화·유동성": ["BASE_MONEY", "CORP_LOAN"],
    "06_주택시장":   ["HOUSE_PRICE_BUY", "HOUSE_PRICE_RENT", "APT_PRICE_BUY", "HOUSING_START"],
    "07_수출입·무역": ["EXPORT_YOY", "IMPORT_YOY"],
    # 08_소비·산업 카테고리 전체 소거 (RETAIL_SALES_YOY·CSI 모두 API 데이터 부재)
    "09_금융시장":   ["KOSPI", "KOSDAQ", "CD_BOK_SPREAD", "CREDIT_SPREAD"],
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
