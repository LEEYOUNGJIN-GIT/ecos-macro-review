"""
scripts/ecos_signals.py
data/ecos_latest.csv 를 읽어 9개 파생 신호와 종합 위험도를 계산하고
data/ecos_signals.md 를 생성합니다.

소거된 신호:
  SIG06 소비자심리 — CSI(511Y004), RETAIL_SALES_YOY(402Y015) 모두 API 데이터 부재
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_CSV = DATA_DIR / "ecos_latest.csv"
OUTPUT_MD = DATA_DIR / "ecos_signals.md"


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def load_data() -> dict[str, float | None]:
    """CSV → {series_id: value, series_id+'__date': date_str} 딕셔너리 반환."""
    if not INPUT_CSV.exists():
        sys.exit(f"[ERROR] {INPUT_CSV} 파일이 없습니다. ecos_fetch.py를 먼저 실행하세요.")
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    values = dict(zip(df["series_id"], pd.to_numeric(df["value"], errors="coerce")))
    for _, row in df.iterrows():
        values[f"{row['series_id']}__date"] = str(row.get("date", "N/A"))
    return values


def g(data: dict, key: str) -> float | None:
    """None-safe 값 조회."""
    v = data.get(key)
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else v


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
    mx = max(valid)
    return round(0.7 * avg + 0.3 * mx, 2)


# ---------------------------------------------------------------------------
# 신호 계산 함수 (10개: SIG01-03·05-08·10-12)
# ---------------------------------------------------------------------------
def sig_01_term_spread(d: dict) -> dict:
    """1. 장단기 금리 스프레드 (국고채 10Y - 기준금리)"""
    spread = None
    g10 = g(d, "GOV_BOND_10Y")
    base = g(d, "BOK_BASE_RATE")
    if g10 is not None and base is not None:
        spread = round(g10 - base, 4)
    # 역전(-) → 위험, 정상(+) → 안전
    if spread is None:
        score = None
    elif spread < 0:
        score = round(min(10.0, 6.0 + abs(spread) * 2), 2)
    else:
        score = round(max(0.0, 4.0 - spread), 2)
    return {
        "id": "SIG01", "name": "장단기 금리 스프레드",
        "value": spread, "unit": "%p",
        "detail": f"국고채10Y({fmt(g10)}) - 기준금리({fmt(base)}) = {fmt(spread)}%p",
        "threshold": "역전(<0) → 침체 경고",
        "score": score,
    }


def sig_02_real_rate_gap(d: dict) -> dict:
    """2. 실질금리 갭 (기준금리 - 근원CPI YoY)"""
    base = g(d, "BOK_BASE_RATE")
    core = g(d, "CORE_CPI_YOY")
    gap = None
    if base is not None and core is not None:
        gap = round(base - core, 4)
    # 갭 ≥ 2.0 → 강한 긴축(위험), ≤ -1.0 → 완화(안전)
    score = score_0_10(gap, -2.0, 3.0)
    return {
        "id": "SIG02", "name": "실질금리 갭",
        "value": gap, "unit": "%p",
        "detail": f"기준금리({fmt(base)}) - 근원CPI({fmt(core)}) = {fmt(gap)}%p",
        "threshold": "≥2.0 강한 긴축 / ≤-1.0 완화",
        "score": score,
    }


def sig_03_inflation_regime(d: dict) -> dict:
    """3. 인플레이션 레짐 (CPI, 근원CPI, PPI 복합)"""
    cpi = g(d, "CPI_YOY")
    core = g(d, "CORE_CPI_YOY")
    ppi = g(d, "PPI_YOY")
    vals = [v for v in [cpi, core, ppi] if v is not None]
    composite = round(float(np.mean(vals)), 4) if vals else None
    score = score_0_10(composite, -1.0, 6.0)
    return {
        "id": "SIG03", "name": "인플레이션 레짐",
        "value": composite, "unit": "% (복합평균)",
        "detail": f"CPI({fmt(cpi)}) / 근원CPI({fmt(core)}) / PPI({fmt(ppi)}) → 복합 {fmt(composite)}%",
        "threshold": "≥3.5 고인플레 / ≤1.0 디플레 경계",
        "score": score,
    }


def sig_05_labor_market(d: dict) -> dict:
    """6. 노동시장 종합"""
    unemp = g(d, "UNEMPLOYMENT_RATE")
    emp_chg = g(d, "EMPLOYMENT_CHANGE")
    emp_rate = g(d, "EMPLOYMENT_RATE")
    # 실업률: 2% → 0점, 5% → 10점
    s_unemp = score_0_10(unemp, 2.0, 5.0)
    # 취업자 증가: 30만 이상 → 0점, -10만 이하 → 10점
    s_emp = score_0_10(emp_chg, -100.0, 300.0, invert=True) if emp_chg is not None else None
    # 고용률: 63% 이상 → 0점, 58% 이하 → 10점
    s_erate = score_0_10(emp_rate, 58.0, 63.0, invert=True) if emp_rate is not None else None
    vals = [v for v in [s_unemp, s_emp, s_erate] if v is not None]
    score = round(float(np.mean(vals)), 2) if vals else None
    return {
        "id": "SIG05", "name": "노동시장 종합",
        "value": unemp, "unit": "% (실업률)",
        "detail": (f"실업률({fmt(unemp)}%) / 취업자증감({fmt(emp_chg, 0)}천명) / "
                   f"고용률({fmt(emp_rate)}%)"),
        "threshold": "실업률 ≥4.5 위험 / 고용률 ≤59 경보",
        "score": score,
    }


def sig_07_credit_stress(d: dict) -> dict:
    """7. 신용 스트레스 (회사채-국채 스프레드, CD-기준금리 스프레드)"""
    credit_sp = g(d, "CREDIT_SPREAD")
    cd_sp = g(d, "CD_BOK_SPREAD")
    # 크레딧 스프레드: 0.5 → 안전, 3.0 이상 → 위험
    s_credit = score_0_10(credit_sp, 0.3, 4.0) if credit_sp is not None else None
    # CD-기준금리: 0.1 → 안전, 1.0 이상 → 위험
    s_cd = score_0_10(cd_sp, 0.0, 1.5) if cd_sp is not None else None
    vals = [v for v in [s_credit, s_cd] if v is not None]
    score = round(float(np.mean(vals)), 2) if vals else None
    return {
        "id": "SIG07", "name": "신용 스트레스",
        "value": credit_sp, "unit": "%p (크레딧 스프레드)",
        "detail": f"회사채BBB-국채3Y({fmt(credit_sp)}%p) / CD-기준금리({fmt(cd_sp)}%p)",
        "threshold": "크레딧 스프레드 ≥2.0 경계 / ≥3.0 위험",
        "score": score,
    }


def sig_08_business_cycle(d: dict) -> dict:
    """8. 경기 사이클 (동행·선행지수 순환변동치)"""
    coin = g(d, "CLI_COINCIDENT")
    lead = g(d, "CLI_LEADING")
    # 순환변동치 100 기준: <98 → 하강, <96 → 심각
    s_coin = score_0_10(coin, 94.0, 102.0, invert=True) if coin is not None else None
    s_lead = score_0_10(lead, 94.0, 102.0, invert=True) if lead is not None else None
    vals = [v for v in [s_coin, s_lead] if v is not None]
    score = round(float(np.mean(vals)), 2) if vals else None
    return {
        "id": "SIG08", "name": "경기 사이클",
        "value": coin, "unit": "지수 (동행순환변동치)",
        "detail": f"동행지수순환변동({fmt(coin)}) / 선행지수순환변동({fmt(lead)})",
        "threshold": "<98 경기 하강 / <96 침체 신호",
        "score": score,
    }


def sig_10_trade(d: dict) -> dict:
    """10. 수출 모멘텀 (수출물량 YoY)"""
    exp_yoy = g(d, "EXPORT_YOY")
    imp_yoy = g(d, "IMPORT_YOY")
    # 수출 YoY: -15% → 위험, +10% → 안전
    s_exp = score_0_10(exp_yoy, -15.0, 10.0, invert=True) if exp_yoy is not None else None
    score = s_exp
    return {
        "id": "SIG10", "name": "수출 모멘텀",
        "value": exp_yoy, "unit": "% YoY (수출물량)",
        "detail": f"수출물량YoY({fmt(exp_yoy)}%) / 수입물량YoY({fmt(imp_yoy)}%)",
        "threshold": "수출 YoY <-10% 위험 / 연속 감소 경보",
        "score": score,
    }


def sig_11_housing_market(d: dict) -> dict:
    """11. 주택시장 — 착공지수(HOUSING_START) 기반 점수.

    HOUSE_PRICE_BUY/RENT/APT는 거래금액(백만원, 누계 여부 미확인)으로
    가격지수 임계값(85~120) 적용 불가 → 점수 산정에서 제외하고 참고값으로만 표시.
    착공지수 100=기준: 값이 높을수록 공급 활발 → 가격 압력 낮음 → 낮은 점수.
    """
    buy = g(d, "HOUSE_PRICE_BUY")
    rent = g(d, "HOUSE_PRICE_RENT")
    apt = g(d, "APT_PRICE_BUY")
    start = g(d, "HOUSING_START")
    # 착공지수만 점수에 사용: 60→위험(공급부족), 140→안전(공급 충분)
    s_start = score_0_10(start, 60.0, 140.0, invert=True) if start is not None else None
    score = s_start
    buy_disp  = f"{fmt(buy, 0)}백만원"  if buy  is not None else "N/A"
    rent_disp = f"{fmt(rent, 0)}백만원" if rent is not None else "N/A"
    apt_disp  = f"{fmt(apt, 0)}백만원"  if apt  is not None else "N/A"
    return {
        "id": "SIG11", "name": "주택시장",
        "value": start, "unit": "지수 (착공지수)",
        "detail": (f"착공지수({fmt(start)}) | "
                   f"매매거래금액({buy_disp}) / 임대({rent_disp}) / 아파트({apt_disp})"
                   f" [거래금액=참고값, 점수 제외]"),
        "threshold": "착공지수 <80 공급 급감·가격 압력 / >130 공급 과잉 안정",
        "score": score,
    }


def sig_12_kospi_regime(d: dict) -> dict:
    """12. KOSPI 레짐"""
    kospi = g(d, "KOSPI")
    # KOSPI 수준: 3000 이상 → 안전, 2000 이하 → 위험
    s_kospi = score_0_10(kospi, 1800.0, 3000.0, invert=True) if kospi is not None else None
    score = s_kospi
    return {
        "id": "SIG12", "name": "KOSPI 레짐",
        "value": kospi, "unit": "pt",
        "detail": f"KOSPI({fmt(kospi, 0)}pt)",
        "threshold": "KOSPI <2000 약세장 / <1800 심각",
        "score": score,
    }


# ---------------------------------------------------------------------------
# 전체 신호 실행
# ---------------------------------------------------------------------------
SIGNAL_FUNCS = [
    sig_01_term_spread, sig_02_real_rate_gap, sig_03_inflation_regime,
    sig_05_labor_market,
    # SIG06 소비자심리 소거: CSI(511Y004) 2022-08 이후 업데이트 없음,
    #   RETAIL_SALES_YOY(402Y015) 7개월 지연 + item_code 오류 → 두 입력 모두 API 데이터 부재
    sig_07_credit_stress, sig_08_business_cycle,
    sig_10_trade, sig_11_housing_market, sig_12_kospi_regime,
]


def run_all_signals(data: dict) -> list[dict]:
    results = []
    for func in SIGNAL_FUNCS:
        sig = func(data)
        sig["risk_label"] = risk_label(sig.get("score"))
        results.append(sig)
    return results


# ---------------------------------------------------------------------------
# 마크다운 보고서 생성
# ---------------------------------------------------------------------------
def build_md(signals: list[dict], generated_at: str) -> str:
    scores = [s.get("score") for s in signals]
    total = overall_risk(scores)
    total_label = risk_label(total)

    lines = [
        "# ECOS 거시경제 신호 대시보드",
        "",
        f"**생성일시**: {generated_at} (KST)",
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
        "| ID | 신호명 | 현재값 | 점수 | 등급 |",
        "|----|------|------|-----|-----|",
    ]

    for s in signals:
        val_str = f"{fmt(s['value'])} {s['unit']}" if s['value'] is not None else "N/A"
        score_str = fmt(s.get("score"))
        lines.append(f"| {s['id']} | {s['name']} | {val_str} | {score_str} | {s['risk_label']} |")

    lines += ["", "---", "", "## 신호별 상세"]

    for s in signals:
        lines += [
            "",
            f"### {s['id']} {s['name']}",
            "",
            f"- **현재값**: {fmt(s['value'])} {s['unit']}",
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
        "> 출처: 한국은행 ECOS API | 본 보고서는 자동 생성되며 투자 권고가 아닙니다.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("ECOS 신호 대시보드 생성 시작")
    print("=" * 60)

    data = load_data()
    print(f"  로드된 지표 수: {len(data)}")

    signals = run_all_signals(data)

    scores = [s.get("score") for s in signals]
    total = overall_risk(scores)
    print(f"\n  종합 위험도: {fmt(total)} / 10.0  {risk_label(total)}")
    print()
    for s in signals:
        print(f"  {s['id']} {s['name']:<20} 점수: {fmt(s.get('score')):<6} {s['risk_label']}")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = build_md(signals, generated_at)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    print(f"\n  Saved: {OUTPUT_MD}")
    print("=" * 60)


if __name__ == "__main__":
    main()
