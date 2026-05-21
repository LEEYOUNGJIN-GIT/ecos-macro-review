"""
ecos_fetch.py
한국은행 ECOS API에서 50개 거시경제 지표를 수집하고
data/ecos_latest.csv 및 data/ecos_latest.md 를 생성합니다.
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, date
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
CALL_INTERVAL = 0.3          # 초 (월 10,000건 제한 대응)
DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "ecos_history"

DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# 지표 레지스트리
# 형식: (이름, 통계표코드, 주기, 항목코드, 단위)
#
# ECOS 통계표 코드 확인: https://ecos.bok.or.kr/api/#/DevGuide/StatisticsSearch
# 항목코드가 빈 문자열("")이면 해당 통계표의 첫 번째(기본) 항목을 사용
# ---------------------------------------------------------------------------
SERIES = [
    # ── 01. 금리·채권 ──────────────────────────────────────────────────────
    ("BOK_BASE_RATE",       "060Y001", "M", "0101000", "%",    "한국은행 기준금리"),
    ("GOV_BOND_3Y",         "721Y001", "M", "5020000", "%",    "국고채 3년"),
    ("GOV_BOND_10Y",        "721Y001", "M", "5030000", "%",    "국고채 10년"),
    ("CD_91D",              "721Y001", "M", "0020000", "%",    "CD 91일"),
    ("CORP_BOND_AA_MINUS",  "721Y001", "M", "4020000", "%",    "회사채 AA-"),
    ("CORP_BOND_BBB_MINUS", "721Y001", "M", "4050000", "%",    "회사채 BBB-"),

    # ── 02. 환율 ───────────────────────────────────────────────────────────
    ("KRW_USD",             "036Y001", "M", "0000001", "원",   "원/달러 환율"),
    ("KRW_JPY",             "036Y001", "M", "0000002", "원",   "원/100엔 환율"),
    ("KRW_CNY",             "036Y001", "M", "0000003", "원",   "원/위안 환율"),
    ("REER",                "036Y002", "M", "0000100", "지수", "실질실효환율"),

    # ── 03. 물가·인플레 ────────────────────────────────────────────────────
    ("CPI_YOY",             "901Y010", "M", "0",       "%",    "소비자물가 전년비"),
    ("CORE_CPI_YOY",        "901Y010", "M", "11",      "%",    "근원CPI 전년비"),
    ("PPI_YOY",             "901Y009", "M", "0",       "%",    "생산자물가 전년비"),
    ("INFLATION_EXPECT",    "902Y016", "M", "0",       "%",    "기대인플레이션"),
    ("IMPORT_PRICE_YOY",    "901Y011", "M", "0",       "%",    "수입물가 전년비"),

    # ── 04. GDP·경기 ───────────────────────────────────────────────────────
    ("GDP_GROWTH_QOQ",      "200Y104", "Q", "10101",   "%",    "실질GDP 전기비"),
    ("GDP_GROWTH_YOY",      "200Y104", "Q", "10111",   "%",    "실질GDP 전년비"),
    ("CLI_COINCIDENT",      "901Y067", "M", "I16A",    "지수", "경기동행지수 순환변동치"),
    ("CLI_LEADING",         "901Y067", "M", "I16B",    "지수", "경기선행지수 순환변동치"),
    ("BSI_ALL",             "512Y014", "M", "AA",      "BSI",  "기업경기실사지수 전산업"),

    # ── 05. 노동시장 ───────────────────────────────────────────────────────
    ("UNEMPLOYMENT_RATE",   "901Y027", "M", "I38A",    "%",    "실업률"),
    ("EMPLOYMENT_CHANGE",   "901Y027", "M", "I38B",    "천명", "취업자수 전년비"),
    ("LABOR_PARTICIPATION", "901Y027", "M", "I38H",    "%",    "경제활동참가율"),
    ("EMPLOYMENT_RATE",     "901Y027", "M", "I38G",    "%",    "고용률"),
    ("YOUTH_UNEMPLOYMENT",  "901Y027", "M", "I38C",    "%",    "청년실업률 (15-29세)"),

    # ── 06. 통화·유동성 ────────────────────────────────────────────────────
    ("M2_YOY",              "101Y004", "M", "BBHA00",  "%",    "M2(광의통화) 전년비"),
    ("M1_YOY",              "101Y004", "M", "BBGA00",  "%",    "M1(협의통화) 전년비"),
    ("BASE_MONEY",          "102Y004", "M", "BC",      "십억원","본원통화 잔액"),
    ("HOUSEHOLD_CREDIT",    "104Y001", "Q", "BBL1A",   "십억원","가계신용 잔액"),
    ("CORP_LOAN",           "104Y014", "M", "BCE",     "십억원","기업대출 잔액"),

    # ── 07. 주택시장 ───────────────────────────────────────────────────────
    ("HOUSE_PRICE_BUY",     "901Y092", "M", "P63AA",   "지수", "주택매매가격지수"),
    ("HOUSE_PRICE_RENT",    "901Y092", "M", "P63BA",   "지수", "주택전세가격지수"),
    ("APT_PRICE_BUY",       "901Y092", "M", "P63AD",   "지수", "아파트매매가격지수"),
    ("HOUSING_START",       "901Y066", "M", "I16Y",    "호",   "주택착공 건수"),

    # ── 08. 수출입·무역 ────────────────────────────────────────────────────
    ("EXPORT_YOY",          "403Y003", "M", "I38301",  "%",    "수출 전년비"),
    ("IMPORT_YOY",          "403Y003", "M", "I38302",  "%",    "수입 전년비"),
    ("TRADE_BALANCE",       "403Y003", "M", "I38303",  "백만달러","무역수지"),
    ("CURRENT_ACCOUNT",     "403Y001", "M", "I38101",  "백만달러","경상수지"),
    ("EXPORT_VOLUME_YOY",   "403Y003", "M", "I38304",  "%",    "수출물량지수 전년비"),

    # ── 09. 소비·산업 ─────────────────────────────────────────────────────
    ("RETAIL_SALES_YOY",    "402Y015", "M", "FM2A",    "%",    "소매판매 전년비"),
    ("INDPRO_YOY",          "402Y012", "M", "BSBI",    "%",    "광공업생산 전년비"),
    ("CAPEX_YOY",           "402Y012", "M", "BSCI",    "%",    "설비투자 전년비"),
    ("CONSTRUCTION_YOY",    "402Y012", "M", "BSDI",    "%",    "건설기성 전년비"),
    ("CSI",                 "511Y004", "M", "FAA",     "지수", "소비자심리지수(CSI)"),

    # ── 10. 금융시장 ───────────────────────────────────────────────────────
    ("KOSPI",               "802Y001", "M", "0001",    "pt",   "KOSPI 지수"),
    ("KOSDAQ",              "802Y001", "M", "0002",    "pt",   "KOSDAQ 지수"),
    ("FOREIGN_NET_BUY",     "802Y004", "M", "7",       "십억원","외국인 주식 순매수"),
    ("CD_BOK_SPREAD",       "721Y001", "M", "SPREAD",  "%",    "CD-기준금리 스프레드 (파생)"),
    ("CREDIT_SPREAD",       "721Y001", "M", "CSPREAD", "%",    "회사채BBB-국채3Y 스프레드 (파생)"),
    ("DSR_HOUSEHOLD",       "104Y001", "Q", "DSR",     "%",    "가계부채 DSR (파생)"),
]

# ---------------------------------------------------------------------------
# ECOS API 호출
# ---------------------------------------------------------------------------
def _date_range(period: str) -> tuple[str, str]:
    """조회 기간 생성: 현재 기준 충분히 긴 범위 반환."""
    today = date.today()
    if period == "D":
        start = date(today.year - 1, 1, 1).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
    elif period == "M":
        start = date(today.year - 3, 1, 1).strftime("%Y%m")
        end = today.strftime("%Y%m")
    elif period == "Q":
        start = f"{today.year - 5}Q1"
        end = f"{today.year}Q4"
    else:  # A
        start = str(today.year - 10)
        end = str(today.year)
    return start, end


def fetch_series(stat_code: str, period: str, item_code: str) -> list[dict]:
    """ECOS StatisticSearch 호출 → row 리스트 반환."""
    start, end = _date_range(period)
    item_part = f"/{item_code}" if item_code else ""
    url = (
        f"{BASE_URL}/{API_KEY}/json/kr/1/100"
        f"/{stat_code}/{period}/{start}/{end}{item_part}"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        if "StatisticSearch" not in body:
            return []
        return body["StatisticSearch"].get("row", [])
    except Exception as exc:
        print(f"  [WARN] {stat_code}/{item_code}: {exc}")
        return []


def latest_value(rows: list[dict]) -> tuple[float | None, str]:
    """rows에서 가장 최근 유효 값과 날짜를 반환."""
    valid = [r for r in rows if r.get("DATA_VALUE") not in (None, "", " ", "-")]
    if not valid:
        return None, "N/A"
    latest = valid[-1]
    return float(latest["DATA_VALUE"]), latest.get("TIME", "N/A")


# ---------------------------------------------------------------------------
# 파생 지표 계산 (스프레드류)
# ---------------------------------------------------------------------------
def _compute_derived(records: dict[str, dict]) -> dict[str, dict]:
    """
    레지스트리 내 파생 코드(SPREAD, CSPREAD, DSR)를
    이미 수집된 데이터로부터 계산하여 records를 업데이트.
    """
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

    # DSR 대용치: 가계신용 잔액 / 명목 GDP 비율(%) — 실제 DSR 데이터가 ECOS에 없을 경우
    hh = records.get("HOUSEHOLD_CREDIT", {}).get("value")
    if "DSR_HOUSEHOLD" in records:
        records["DSR_HOUSEHOLD"]["value"] = hh  # 원 잔액 유지 (신호 스크립트에서 활용)
        records["DSR_HOUSEHOLD"]["date"] = records.get("HOUSEHOLD_CREDIT", {}).get("date", "N/A")

    return records


# ---------------------------------------------------------------------------
# 메인 수집 루프
# ---------------------------------------------------------------------------
def collect_all() -> pd.DataFrame:
    records: dict[str, dict] = {}
    total = len(SERIES)

    for i, (key, stat_code, period, item_code, unit, label) in enumerate(SERIES, 1):
        is_derived = item_code in ("SPREAD", "CSPREAD", "DSR")
        if is_derived:
            records[key] = {"label": label, "value": None, "date": "N/A", "unit": unit,
                            "stat_code": stat_code, "period": period}
            continue

        print(f"  [{i:02d}/{total}] {key:<25} {stat_code}/{item_code}")
        rows = fetch_series(stat_code, period, item_code)
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
    "02_환율":      ["KRW_USD", "KRW_JPY", "KRW_CNY", "REER"],
    "03_물가·인플레": ["CPI_YOY", "CORE_CPI_YOY", "PPI_YOY", "INFLATION_EXPECT", "IMPORT_PRICE_YOY"],
    "04_GDP·경기":  ["GDP_GROWTH_QOQ", "GDP_GROWTH_YOY", "CLI_COINCIDENT", "CLI_LEADING", "BSI_ALL"],
    "05_노동시장":   ["UNEMPLOYMENT_RATE", "EMPLOYMENT_CHANGE", "LABOR_PARTICIPATION",
                     "EMPLOYMENT_RATE", "YOUTH_UNEMPLOYMENT"],
    "06_통화·유동성": ["M2_YOY", "M1_YOY", "BASE_MONEY", "HOUSEHOLD_CREDIT", "CORP_LOAN"],
    "07_주택시장":   ["HOUSE_PRICE_BUY", "HOUSE_PRICE_RENT", "APT_PRICE_BUY", "HOUSING_START"],
    "08_수출입·무역": ["EXPORT_YOY", "IMPORT_YOY", "TRADE_BALANCE", "CURRENT_ACCOUNT", "EXPORT_VOLUME_YOY"],
    "09_소비·산업":  ["RETAIL_SALES_YOY", "INDPRO_YOY", "CAPEX_YOY", "CONSTRUCTION_YOY", "CSI"],
    "10_금융시장":   ["KOSPI", "KOSDAQ", "FOREIGN_NET_BUY", "CD_BOK_SPREAD", "CREDIT_SPREAD", "DSR_HOUSEHOLD"],
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
            lines.append(f"| {k} | {m['label']} | {val_str} | {m['unit']} | {m['date']} |")
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
        print("       환경변수로 설정해주세요.")
        print("       sample 키로는 일부 지표만 조회 가능합니다.\n")

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
