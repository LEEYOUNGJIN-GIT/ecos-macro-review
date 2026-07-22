"""
scripts/ecos_signals.py
data/macro_latest.csv 를 읽어 10개 파생 신호와 종합 위험도를 계산하고
data/ecos_signals.md 를 생성합니다.

v3.4 (2026-07-22): SIG02·SIG03·SIG06·SIG08 KOSIS 차단 대응 ECOS 재배포 대체 확대
  - discover_ecos_codes.py 실측 조회로 CORE_CPI_YOY(901Y010/QB), CLI_COINCIDENT
    /CLI_LEADING(901Y067/I16D·I16E), SERVICE_PROD_YOY(901Y038/I51A) 확보
  - SIG02(실질금리갭)·SIG03(인플레이션 레짐)의 근원CPI, SIG06(내수·소비)의
    서비스업생산, SIG08(경기사이클)의 동행·선행지수가 전부 g_fallback 적용
  - "근원CPI/CLI/서비스업생산은 ECOS 대체 없음"이라던 v3.2까지의 문서화가
    틀렸음이 드러남 — StatisticItemList 실측 조회 결과로 정정

v3.2 (2026-07-22): SIG03·SIG09 KOSIS 차단 대응 ECOS 재배포 대체(g_fallback)
  - KOSIS_CPI_YOY/KOSIS_INDPRO_YOY 미수집 시 ECOS CPI_YOY/INDPRO_YOY 로 자동 대체
  - 근원CPI(SIG02)는 검증된 ECOS 대체 코드가 없어 KOSIS 단일 소스 유지 — 상세문에 명시

v3.1 (2026-05-27): 근원CPI·신호 산식 개선
  - SIG02 실질금리 갭 정규화 (-2,3)→(-4,4) — 깊은 음의 실질금리 클리핑 완화
  - SIG06 내수·소비: 소매+서비스 복합값·복합 전기비 표시
  - SIG12 KOSPI 정규화 상한 8000→10000 (2026년 지수 수준 반영)

v3.0 (2026-05-27): ECOS+KOSIS 통합 플랜 v1
  - INPUT_CSV: ecos_latest.csv → macro_latest.csv
  - SIG06 내수·소비 신규 구현 (KOSIS_RETAIL_YOY + KOSIS_SERVICE_PROD_YOY)
  - series_id 키 매핑: CPI/CORE_CPI/실업률/고용률/취업자/CLI/INDPRO/소매·서비스
  - 각 신호 함수 return dict에 date 키 추가
  - build_md() 요약표에 기준일 컬럼 추가
  - 신호별 상세 섹션에 **기준일** 항목 추가
  - build_md() 상단에 기준일 이질성 경고 블록 추가
  - 보고서 footer → ECOS + KOSIS 출처 반영

v2.5 (2026-05-27):
  load_data(): chg_prev / chg_yoy 컬럼 로딩 추가
  각 신호 함수: chg_prev(전기비) 필드 추가
  build_md(): 요약표에 전기비 컬럼 추가

v2.2 (2026-05-26):
  SIG02 실질금리 갭: CORE_CPI_YOY 데이터 정정으로 자동 개선
  SIG11 주택시장: KB주택가격지수(YoY) 기반으로 재설계

소거된 신호:
  SIG04 기대인플레 디앵커링 — ECOS 기대인플레 시리즈 미수록 (BOK 서베이 데이터 비공개)
  SIG10 수출 모멘텀 — KOSIS 관세청 수출입 Open API tblId 미확인 (v1.2 제거)
"""

import sys
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

_KST = ZoneInfo("Asia/Seoul")

DATA_DIR  = Path(__file__).parent.parent / "data"
INPUT_CSV = DATA_DIR / "macro_latest.csv"
OUTPUT_MD = DATA_DIR / "ecos_signals.md"


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def load_data() -> dict[str, float | None]:
    """CSV → {series_id: value, series_id+'__date': date_str,
              series_id+'__chg_prev': chg_prev, ...} 딕셔너리 반환."""
    if not INPUT_CSV.exists():
        sys.exit(
            f"[ERROR] {INPUT_CSV} 파일이 없습니다. "
            "ecos_fetch.py → kosis_fetch.py → merge_macro.py 순서로 실행하세요."
        )
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    values = dict(zip(df["series_id"], pd.to_numeric(df["value"], errors="coerce")))
    for _, row in df.iterrows():
        sid = row["series_id"]
        values[f"{sid}__date"] = str(row.get("date", "N/A"))
        for col in ("chg_prev", "chg_mid", "chg_yoy"):
            if col in df.columns:
                v = row.get(col)
                if pd.notna(v) and str(v) not in ("", "nan"):
                    try:
                        values[f"{sid}__{col}"] = float(v)
                    except (ValueError, TypeError):
                        pass
    return values


def g(data: dict, key: str) -> float | None:
    """None-safe 값 조회 (float 전용). 문자열 키(__date 등)는 data.get() 직접 사용."""
    v = data.get(key)
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else v


def gdate(data: dict, series_id: str) -> str:
    """series_id 에 대한 기준일 문자열 반환."""
    raw = str(data.get(f"{series_id}__date", "N/A"))
    if len(raw) == 6 and raw.isdigit():    # YYYYMM → YYYY-MM
        return f"{raw[:4]}-{raw[4:]}"
    if len(raw) == 8 and raw.isdigit():    # YYYYMMDD → YYYY-MM-DD
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def g_fallback(data: dict, primary: str, fallback: str) -> tuple[float | None, str]:
    """KOSIS(primary)가 GitHub Actions에서 간헐 차단되는 문제 대응.
    primary 값이 없으면 fallback(ECOS 재배포)을 사용한다. (value, 실제 사용된 series_id) 반환."""
    v = g(data, primary)
    if v is not None:
        return v, primary
    v = g(data, fallback)
    if v is not None:
        return v, fallback
    return None, primary


def score_0_10(value: float | None, low: float, high: float, invert: bool = False) -> float | None:
    """value를 [low, high] 구간에서 0-10 점수로 정규화."""
    if value is None:
        return None
    clipped = max(low, min(high, value))
    raw = (clipped - low) / (high - low) * 10.0
    return round(10.0 - raw if invert else raw, 2)


def fmt(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def base_effect_note(chg_prev: float | None, threshold: float = 5.0) -> str:
    """YoY 가속도 |chg_prev| > threshold 시 기저효과 경고."""
    if chg_prev is not None and abs(chg_prev) > threshold:
        return " ⚠️기저효과"
    return ""


# ---------------------------------------------------------------------------
# 5단계 위험 라벨
# ---------------------------------------------------------------------------
RISK_LEVELS = [
    (0,   2,   "🟢 안정",   "Stable"),
    (2,   4,   "🔵 주의",   "Caution"),
    (4,   6,   "🟡 경계",   "Warning"),
    (6,   8,   "🟠 위험",   "Risk"),
    (8,   10,  "🔴 심각",   "Critical"),
]


def risk_label(score: float | None) -> str:
    if score is None:
        return "⚪ N/A"
    for lo, hi, label, _ in RISK_LEVELS:
        if lo <= score < hi:
            return label
    return "🔴 심각"


def overall_risk(scores: list[float | None]) -> float | None:
    valid = [s for s in scores if s is not None]
    if not valid:
        return None
    avg = np.mean(valid)
    mx  = max(valid)
    return round(0.7 * avg + 0.3 * mx, 2)


def fmt_chg(chg: float | None) -> str:
    if chg is None:
        return "-"
    av = abs(chg)
    if av >= 10_000:
        return f"{chg:+,.0f}"
    elif av >= 1:
        return f"{chg:+.2f}"
    else:
        return f"{chg:+.4f}"


def trend_arrow(chg: float | None, threshold: float = 0.05) -> str:
    if chg is None:
        return ""
    return " 🔺" if chg > threshold else (" 🔻" if chg < -threshold else " ➡️")


# ---------------------------------------------------------------------------
# 신호 계산 함수 (10개: SIG01-03·05-09·11-12)
# ---------------------------------------------------------------------------
def sig_01_term_spread(d: dict) -> dict:
    """1. 장단기 금리 스프레드 (국고채 10Y - 기준금리)"""
    g10  = g(d, "GOV_BOND_10Y")
    base = g(d, "BOK_BASE_RATE")
    spread = round(g10 - base, 4) if (g10 is not None and base is not None) else None
    if spread is None:
        score = None
    elif spread < 0:
        score = round(min(10.0, 6.0 + abs(spread) * 2), 2)
    else:
        score = round(max(0.0, 4.0 - spread), 2)
    g10_chg  = g(d, "GOV_BOND_10Y__chg_prev")
    base_chg = g(d, "BOK_BASE_RATE__chg_prev")
    chg_prev = round(g10_chg - base_chg, 4) if (g10_chg is not None and base_chg is not None) else None
    return {
        "id": "SIG01", "name": "장단기 금리 스프레드",
        "value": spread, "unit": "%p",
        "date": gdate(d, "GOV_BOND_10Y"),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": f"국고채10Y({fmt(g10)}) - 기준금리({fmt(base)}) = {fmt(spread)}%p",
        "threshold": "역전(<0) → 침체 경고",
        "score": score,
    }


def sig_02_real_rate_gap(d: dict) -> dict:
    """2. 실질금리 갭 (기준금리 - 근원CPI YoY, 농산물·석유류제외)

    근원CPI는 KOSIS_CORE_CPI_YOY 우선, 차단 시 ECOS 재배포(CORE_CPI_YOY, 901Y010/QB)로 대체.
    """
    base = g(d, "BOK_BASE_RATE")
    core, core_src = g_fallback(d, "KOSIS_CORE_CPI_YOY", "CORE_CPI_YOY")
    gap  = round(base - core, 4) if (base is not None and core is not None) else None
    score = score_0_10(gap, -4.0, 4.0)
    base_chg = g(d, "BOK_BASE_RATE__chg_prev")
    core_chg = g(d, f"{core_src}__chg_prev")
    chg_prev = round(base_chg - core_chg, 4) if (base_chg is not None and core_chg is not None) else None
    core_note = " [ECOS 재배포 대체]" if core_src == "CORE_CPI_YOY" else ""
    detail = f"기준금리({fmt(base)}) - 근원CPI({fmt(core)}{core_note}) = {fmt(gap)}%p"
    if core is None:
        detail += " — 근원CPI 미수집(KOSIS·ECOS 모두 실패)"
    return {
        "id": "SIG02", "name": "실질금리 갭",
        "value": gap, "unit": "%p",
        "date": gdate(d, core_src),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": detail,
        "threshold": "≥2.0 강한 긴축 / ≤-1.0 완화",
        "score": score,
    }


def sig_03_inflation_regime(d: dict) -> dict:
    """3. 인플레이션 레짐 (CPI, 근원CPI, PPI 복합)

    CPI는 KOSIS_CPI_YOY 우선, 차단 시 ECOS 재배포(CPI_YOY, 901Y009/0)로 대체.
    근원CPI는 KOSIS_CORE_CPI_YOY 우선, 차단 시 ECOS 재배포(CORE_CPI_YOY, 901Y010/QB)로 대체.
    """
    cpi, cpi_src   = g_fallback(d, "KOSIS_CPI_YOY", "CPI_YOY")
    core, core_src = g_fallback(d, "KOSIS_CORE_CPI_YOY", "CORE_CPI_YOY")
    ppi  = g(d, "PPI_YOY")
    vals = [v for v in [cpi, core, ppi] if v is not None]
    composite = round(float(np.mean(vals)), 4) if vals else None
    score = score_0_10(composite, -1.0, 6.0)
    chg_vals = [v for v in [g(d, f"{cpi_src}__chg_prev"),
                             g(d, f"{core_src}__chg_prev"),
                             g(d, "PPI_YOY__chg_prev")] if v is not None]
    chg_prev = round(float(np.mean(chg_vals)), 4) if chg_vals else None
    cpi_note  = " [ECOS 재배포 대체]" if cpi_src == "CPI_YOY" else ""
    core_note = " [ECOS 재배포 대체]" if core_src == "CORE_CPI_YOY" else ""
    return {
        "id": "SIG03", "name": "인플레이션 레짐",
        "value": composite, "unit": "% (복합평균)",
        "date": gdate(d, cpi_src),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": (f"CPI({fmt(cpi)}{cpi_note}) / 근원CPI({fmt(core)}{core_note}) / PPI({fmt(ppi)}) "
                   f"→ 복합 {fmt(composite)}%"),
        "threshold": "≥3.5 고인플레 / ≤1.0 디플레 경계",
        "score": score,
    }


def sig_05_labor_market(d: dict) -> dict:
    """5. 노동시장 종합"""
    unemp    = g(d, "KOSIS_UNEMP_RATE")
    emp_chg  = g(d, "KOSIS_EMP_CHANGE")
    emp_rate = g(d, "KOSIS_EMP_RATE")
    s_unemp  = score_0_10(unemp, 2.0, 5.0)
    s_emp    = score_0_10(emp_chg, -100.0, 300.0, invert=True) if emp_chg is not None else None
    s_erate  = score_0_10(emp_rate, 58.0, 63.0, invert=True) if emp_rate is not None else None
    vals     = [v for v in [s_unemp, s_emp, s_erate] if v is not None]
    score    = round(float(np.mean(vals)), 2) if vals else None
    chg_prev = g(d, "KOSIS_UNEMP_RATE__chg_prev")
    return {
        "id": "SIG05", "name": "노동시장 종합",
        "value": unemp, "unit": "% (실업률)",
        "date": gdate(d, "KOSIS_UNEMP_RATE"),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": (f"실업률({fmt(unemp)}%) / 취업자증감({fmt(emp_chg, 0)}천명) / "
                   f"고용률({fmt(emp_rate)}%)"),
        "threshold": "실업률 ≥4.5 위험 / 고용률 ≤59 경보",
        "score": score,
    }


def sig_06_domestic_demand(d: dict) -> dict:
    """6. 내수·소비 (소매판매 YoY + 서비스업생산 YoY)

    서비스업생산은 KOSIS_SERVICE_PROD_YOY 우선, 차단 시 ECOS 재배포
    (SERVICE_PROD_YOY, 901Y038/I51A)로 대체. 소매판매는 ECOS 대체 없음(KOSIS 단일 소스).
    """
    retail = g(d, "KOSIS_RETAIL_YOY")
    svc, svc_src = g_fallback(d, "KOSIS_SERVICE_PROD_YOY", "SERVICE_PROD_YOY")
    vals   = [v for v in [retail, svc] if v is not None]
    composite = round(float(np.mean(vals)), 2) if vals else None
    # 점수: 높은 성장(호조)이 낮은 점수 → invert=True (위험 점수 체계)
    s_ret = score_0_10(retail, -5.0, 15.0, invert=True) if retail is not None else None
    s_svc = score_0_10(svc,    -5.0, 15.0, invert=True) if svc    is not None else None
    svals = [v for v in [s_ret, s_svc] if v is not None]
    score = round(float(np.mean(svals)), 2) if svals else None
    chg_vals = [v for v in [g(d, "KOSIS_RETAIL_YOY__chg_prev"),
                             g(d, f"{svc_src}__chg_prev")] if v is not None]
    chg_prev = round(float(np.mean(chg_vals)), 4) if chg_vals else None
    svc_chg  = g(d, f"{svc_src}__chg_prev")
    svc_note = " [ECOS 재배포 대체]" if svc_src == "SERVICE_PROD_YOY" else ""
    return {
        "id": "SIG06", "name": "내수·소비",
        "value": composite, "unit": "% YoY (소매·서비스 복합)",
        "date": gdate(d, "KOSIS_RETAIL_YOY"),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": (f"소매판매YoY({fmt(retail)}%) / 서비스업생산YoY({fmt(svc)}{svc_note}%)"
                   f"{base_effect_note(svc_chg)} "
                   f"→ 복합 {fmt(composite)}% [익월 말 발표]"),
        "threshold": "복합 YoY <-2% 경계 / <-5% 위험 / 서비스 동반 부진 시 복합 신호",
        "score": score,
    }


def sig_07_credit_stress(d: dict) -> dict:
    """7. 신용 스트레스 (회사채-국채 스프레드, CD-기준금리 스프레드)"""
    credit_sp = g(d, "CREDIT_SPREAD")
    cd_sp     = g(d, "CD_BOK_SPREAD")
    s_credit  = score_0_10(credit_sp, 0.3, 4.0) if credit_sp is not None else None
    s_cd      = score_0_10(cd_sp, 0.0, 1.5)     if cd_sp     is not None else None
    vals  = [v for v in [s_credit, s_cd] if v is not None]
    score = round(float(np.mean(vals)), 2) if vals else None
    bbb_chg    = g(d, "CORP_BOND_BBB_MINUS__chg_prev")
    bond3y_chg = g(d, "GOV_BOND_3Y__chg_prev")
    chg_prev   = round(bbb_chg - bond3y_chg, 4) if (bbb_chg is not None and bond3y_chg is not None) else None
    return {
        "id": "SIG07", "name": "신용 스트레스",
        "value": credit_sp, "unit": "%p (크레딧 스프레드)",
        "date": gdate(d, "CREDIT_SPREAD"),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": f"회사채BBB-국채3Y({fmt(credit_sp)}%p) / CD-기준금리({fmt(cd_sp)}%p)",
        "threshold": "크레딧 스프레드 ≥2.0 경계 / ≥3.0 위험",
        "score": score,
    }


def sig_08_business_cycle(d: dict) -> dict:
    """8. 경기 사이클 (동행·선행지수 순환변동치)

    KOSIS_CLI_COINCIDENT/LEADING 우선, 차단 시 ECOS 재배포(CLI_COINCIDENT,
    CLI_LEADING — 901Y067/I16D·I16E)로 대체.
    """
    coin, coin_src = g_fallback(d, "KOSIS_CLI_COINCIDENT", "CLI_COINCIDENT")
    lead, lead_src = g_fallback(d, "KOSIS_CLI_LEADING", "CLI_LEADING")
    s_coin = score_0_10(coin, 94.0, 102.0, invert=True) if coin is not None else None
    s_lead = score_0_10(lead, 94.0, 102.0, invert=True) if lead is not None else None
    vals  = [v for v in [s_coin, s_lead] if v is not None]
    score = round(float(np.mean(vals)), 2) if vals else None
    chg_prev = g(d, f"{coin_src}__chg_prev")
    coin_note = " [ECOS 재배포 대체]" if coin_src == "CLI_COINCIDENT" else ""
    lead_note = " [ECOS 재배포 대체]" if lead_src == "CLI_LEADING" else ""
    return {
        "id": "SIG08", "name": "경기 사이클",
        "value": coin, "unit": "지수 (동행순환변동치)",
        "date": gdate(d, coin_src),
        "chg_prev": chg_prev, "chg_unit": "pt",
        "detail": (f"동행지수순환변동({fmt(coin)}{coin_note}) / 선행지수순환변동({fmt(lead)}{lead_note}) "
                   "[약 2개월 발표 지연]"),
        "threshold": "<98 경기 하강 / <96 침체 신호",
        "score": score,
    }


def sig_09_industrial_production(d: dict) -> dict:
    """9. 산업생산 모멘텀 (광공업생산지수 전년비)

    KOSIS_INDPRO_YOY 우선, 차단 시 ECOS 재배포(INDPRO_YOY, 401Y015/*AA/C)로 대체.
    """
    indpro, indpro_src = g_fallback(d, "KOSIS_INDPRO_YOY", "INDPRO_YOY")
    score    = score_0_10(indpro, -10.0, 15.0, invert=True) if indpro is not None else None
    chg_prev = g(d, f"{indpro_src}__chg_prev")
    src_note = " [ECOS 재배포 대체]" if indpro_src == "INDPRO_YOY" else " [통계청 KOSIS, 익월 말 발표]"
    return {
        "id": "SIG09", "name": "산업생산 모멘텀",
        "value": indpro, "unit": "% YoY (광공업생산)",
        "date": gdate(d, indpro_src),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": f"광공업생산지수 전년비({fmt(indpro)}%){base_effect_note(chg_prev)}{src_note}",
        "threshold": "YoY <-5% 경계 / <-10% 위험 / >10% 호조",
        "score": score,
    }


def sig_11_housing_market(d: dict) -> dict:
    """11. 주택시장 (KB주택매매가격지수 YoY, KB전세가격지수 YoY, 착공지수 복합)"""
    kb_buy    = g(d, "KB_HOUSE_YOY")
    kb_jeonse = g(d, "KB_JEONSE_YOY")
    start     = g(d, "HOUSING_START")
    s_buy     = score_0_10(kb_buy, -5.0, 15.0)         if kb_buy    is not None else None
    s_jeonse  = score_0_10(kb_jeonse, -5.0, 15.0)      if kb_jeonse is not None else None
    s_start   = score_0_10(start, 60.0, 140.0, invert=True) if start is not None else None
    vals      = [v for v in [s_buy, s_jeonse, s_start] if v is not None]
    score     = round(float(np.mean(vals)), 2) if vals else None
    chg_prev  = g(d, "KB_HOUSE_YOY__chg_prev")
    return {
        "id": "SIG11", "name": "주택시장",
        "value": kb_buy, "unit": "% YoY (KB매매가격)",
        "date": gdate(d, "KB_HOUSE_YOY"),
        "chg_prev": chg_prev, "chg_unit": "%p",
        "detail": (f"KB매매가격YoY({fmt(kb_buy)}%) / KB전세가격YoY({fmt(kb_jeonse)}%) / "
                   f"착공지수({fmt(start)})"),
        "threshold": "매매가격 YoY >10% 과열 / 착공지수 <80 공급 급감·가격 압박",
        "score": score,
    }


def sig_12_kospi_regime(d: dict) -> dict:
    """12. KOSPI 레짐 (SIG12 전용 — 레짐 성장 점수 제외)"""
    kospi  = g(d, "KOSPI")
    score  = score_0_10(kospi, 5000.0, 12000.0, invert=True) if kospi is not None else None
    chg_prev = g(d, "KOSPI__chg_prev")
    return {
        "id": "SIG12", "name": "KOSPI 레짐",
        "value": kospi, "unit": "pt",
        "date": gdate(d, "KOSPI"),
        "chg_prev": chg_prev, "chg_unit": "pt",
        "detail": f"KOSPI({fmt(kospi, 0)}pt) [ECOS 802Y001 일별, SIG12 전용]",
        "threshold": "KOSPI <6000 하락 경계 / <5000 약세장 / <4000 심각 (2026년 ~8000pt 기준)",
        "score": score,
    }


# ---------------------------------------------------------------------------
# 전체 신호 실행
# ---------------------------------------------------------------------------
SIGNAL_FUNCS = [
    sig_01_term_spread, sig_02_real_rate_gap, sig_03_inflation_regime,
    # SIG04 기대인플레 미구현: ECOS 기대인플레 시리즈 비공개 (BOK 서베이 데이터)
    sig_05_labor_market,
    sig_06_domestic_demand,     # v3.0 신규: KOSIS 소매판매+서비스업생산
    sig_07_credit_stress, sig_08_business_cycle,
    sig_09_industrial_production,
    sig_11_housing_market, sig_12_kospi_regime,
]


def run_all_signals(data: dict) -> list[dict]:
    results = []
    for func in SIGNAL_FUNCS:
        sig = func(data)
        sig["risk_label"] = risk_label(sig.get("score"))
        results.append(sig)
    return results


# ---------------------------------------------------------------------------
# 기준일 이질성 경고 블록
# ---------------------------------------------------------------------------
def _build_staleness_block(data: dict, generated_at: str, signals: list[dict]) -> str:
    """지연 지표 및 수집 실패(N/A) 신호를 점검해 경고 블록 생성."""
    today = date.today()

    # 2개월 이상 지연 여부 확인 대상
    CHECK_MAP = [
        ("SIG08", "KOSIS_CLI_COINCIDENT"),
        ("SIG09", "KOSIS_INDPRO_YOY"),
        ("SIG06", "KOSIS_RETAIL_YOY"),
    ]
    stale_items: list[str] = []
    for sig_id, sid in CHECK_MAP:
        raw = str(data.get(f"{sid}__date", "N/A"))
        if len(raw) == 6 and raw.isdigit():
            try:
                obs = date(int(raw[:4]), int(raw[4:6]), 1)
                months_lag = (today.year - obs.year) * 12 + (today.month - obs.month)
                if months_lag >= 2:
                    stale_items.append(f"{sig_id}({months_lag}개월 지연)")
            except Exception:
                pass

    # 수집 실패(score=None)인 신호 감지
    na_sigs = [s["id"] for s in signals if s.get("score") is None]

    lines = [f"> **데이터 기준일 현황** (생성: {generated_at})"]
    lines.append("> - 최신(익월 초~중): CPI·고용(SIG03·SIG05) / 생산·소비(SIG06·SIG09) 익월 말")
    if na_sigs:
        lines.append(f"> - ⚠️ **수집 실패로 N/A**: {', '.join(na_sigs)}"
                     " — 데이터 미수집. 해당 신호는 분석 제외.")
    if stale_items:
        lines.append("> - ⚠️ 2개월+ 지연: " + ", ".join(stale_items)
                     + " — 통계청 발표 특성, 분석 시 유의")
    if not na_sigs and not stale_items:
        lines.append("> - 지연·미수집 지표 없음 (모든 지표 정상)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 마크다운 보고서 생성
# ---------------------------------------------------------------------------
def build_md(signals: list[dict], generated_at: str, data: dict) -> str:
    scores      = [s.get("score") for s in signals]
    total       = overall_risk(scores)
    total_label = risk_label(total)

    staleness_block = _build_staleness_block(data, generated_at, signals)

    lines = [
        "# ECOS + KOSIS 거시경제 신호 대시보드",
        "",
        f"**생성일시**: {generated_at} (KST)",
        "",
        staleness_block,
        "",
        "---",
        "",
        "## 종합 위험도",
        "",
        f"| 구분 | 점수 (0-10) | 등급 |",
        f"|-----|-----------|-----|",
        f"| **종합 위험도** (70%×평균 + 30%×최대) | **{fmt(total)}** | **{total_label}** |",
        "",
        "---",
        "",
        f"## {len(signals)}개 신호 요약",
        "",
        "| ID | 신호명 | 현재값 | 기준일 | 전기비 | 점수 | 등급 |",
        "|----|------|------|------|------|-----|-----|",
    ]

    for s in signals:
        val_str   = f"{fmt(s['value'])} {s['unit']}" if s["value"] is not None else "N/A"
        date_str  = s.get("date", "N/A")
        chg       = s.get("chg_prev")
        chg_u     = s.get("chg_unit", "")
        chg_str   = f"{fmt_chg(chg)}{(' ' + chg_u) if chg_u and chg is not None else ''}{trend_arrow(chg)}"
        score_str = fmt(s.get("score"))
        lines.append(
            f"| {s['id']} | {s['name']} | {val_str} | {date_str}"
            f" | {chg_str} | {score_str} | {s['risk_label']} |"
        )

    lines += ["", "---", "", "## 신호별 상세"]

    for s in signals:
        chg   = s.get("chg_prev")
        chg_u = s.get("chg_unit", "")
        chg_line = f"{fmt_chg(chg)}{(' ' + chg_u) if chg_u and chg is not None else ''}{trend_arrow(chg)}"
        lines += [
            "",
            f"### {s['id']} {s['name']}",
            "",
            f"- **현재값**: {fmt(s['value'])} {s['unit']}",
            f"- **기준일**: {s.get('date', 'N/A')}",
            f"- **전기비**: {chg_line}",
            f"- **신호 점수**: {fmt(s.get('score'))} / 10.0",
            f"- **등급**: {s['risk_label']}",
            f"- **세부 내역**: {s['detail']}",
            f"- **임계 기준**: {s['threshold']}",
        ]

    lines += [
        "",
        "---",
        "",
        "## 등급 기준표",
        "",
        "| 등급 | 점수 범위 | 시사점 |",
        "|-----|---------|------|",
        "| 🟢 안정 | 0 - 2 | 현재 리스크 낮음, 정상 범위 |",
        "| 🔵 주의 | 2 - 4 | 모니터링 강화 필요 |",
        "| 🟡 경계 | 4 - 6 | 정책 대응 또는 포지션 점검 |",
        "| 🟠 위험 | 6 - 8 | 방어적 포지셔닝 권고 |",
        "| 🔴 심각 | 8 - 10 | 즉각적 리스크 관리 필요 |",
        "",
        "> 출처: 한국은행 ECOS API + 통계청 KOSIS API | "
        "본 보고서는 자동 생성되며 투자 권고가 아닙니다.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("거시경제 신호 대시보드 생성 시작 (ECOS + KOSIS)")
    print("=" * 60)

    data = load_data()
    print(f"  로드된 지표 수: {sum(1 for k in data if '__' not in k)}")

    signals = run_all_signals(data)

    scores = [s.get("score") for s in signals]
    total  = overall_risk(scores)
    print(f"\n  종합 위험도: {fmt(total)} / 10.0  {risk_label(total)}")
    print()
    for s in signals:
        print(f"  {s['id']} {s['name']:<20} 점수: {fmt(s.get('score')):<6} "
              f"{s['risk_label']}  기준일: {s.get('date', 'N/A')}")

    generated_at = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")
    md = build_md(signals, generated_at, data)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    print(f"\n  Saved: {OUTPUT_MD}")
    print("=" * 60)


if __name__ == "__main__":
    main()
