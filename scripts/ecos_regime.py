"""
scripts/ecos_regime.py
data/ecos_latest.csv 를 읽어 성장·인플레이션 점수를 계산하고
2×2 매크로 레짐을 분류한 뒤 data/ecos_regime.md 를 생성합니다.

v2.5 (2026-05-27):
  - load_data(): chg_prev / chg_yoy 컬럼 로딩 추가
  - compute_growth/inflation_score(): 컴포넌트 튜플에 chg_prev/chg_yoy 추가
  - build_md(): 성장·인플레 점수 테이블에 전기비/YoY비 컬럼 추가
  - fmt_chg() 헬퍼 추가

v2.2 (2026-05-26):
  - CORE_CPI_YOY 데이터 정정(item "11"=신선어개 → "QB"=농산물및석유류제외지수)으로
    인플레이션 점수 자동 개선 (4.18% → 2.19% YoY 정정)
  - 인플레이션 점수 구성 요소에서 HOUSE_PRICE 관련 오류 데이터 영향 제거
    (해당 시리즈는 ecos_fetch.py에서 제거)

v2.1 (2026-05-26):
  - 성장 점수에 INDPRO_YOY(광공업생산 전년비, weight 1.0) 추가 → 6개 요소
  - KOSPI 범위 조정: (1800, 3200) → (2500, 8500) (2026년 시장 수준 반영)
  - IMPORT_PRICE_YOY 범위 확대: (-10, 15) → (-20, 40)으로 변경
    (403Y005/B 수입물가지수 YoY가 30%+ 수준도 커버하도록)

레짐 매트릭스:
        인플레 ↑ (>5)
             │
 ⚠️ Stagflation  │  🔥 Overheating
  (성장↓ 인플레↑) │  (성장↑ 인플레↑)
─────────────┼──────────────  성장 →
 ❄️ Recession    │  ✨ Goldilocks
  (성장↓ 인플레↓) │  (성장↑ 인플레↓)
             │
        인플레 ↓ (≤5)
"""

import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

_KST = ZoneInfo("Asia/Seoul")

DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_CSV = DATA_DIR / "ecos_latest.csv"
OUTPUT_MD = DATA_DIR / "ecos_regime.md"

GROWTH_THRESHOLD = 5.0
INFLATION_THRESHOLD = 5.0


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def load_data() -> dict[str, float | None]:
    if not INPUT_CSV.exists():
        sys.exit(f"[ERROR] {INPUT_CSV} 파일이 없습니다. ecos_fetch.py를 먼저 실행하세요.")
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
    v = data.get(key)
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else v


def score_component(
    value: float | None,
    low: float,
    high: float,
    weight: float = 1.0,
    invert: bool = False,
) -> tuple[float | None, float]:
    """[low, high] 구간에서 0-10 정규화 후 weight 반환."""
    if value is None:
        return None, weight
    clipped = max(low, min(high, value))
    raw = (clipped - low) / (high - low) * 10.0
    scored = 10.0 - raw if invert else raw
    return round(scored, 4), weight


def weighted_mean(pairs: list[tuple[float | None, float]]) -> float | None:
    valid = [(v, w) for v, w in pairs if v is not None]
    if not valid:
        return None
    total_w = sum(w for _, w in valid)
    return round(sum(v * w for v, w in valid) / total_w, 4)


def fmt(v: float | None, d: int = 2) -> str:
    return "N/A" if v is None else f"{v:.{d}f}"


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


# ---------------------------------------------------------------------------
# 성장 점수 (0-10, 높을수록 강한 성장)
# 6개 요소 (소거: RETAIL_SALES_YOY·CSI — API 데이터 부재)
# ---------------------------------------------------------------------------
def compute_growth_score(data: dict) -> dict:
    """성장 점수 계산. 컴포넌트 튜플: (key, label, val, unit, chg_prev, chg_yoy, score, weight)"""
    components = []

    # 1. 실질 GDP YoY (weight 2.0) — 범위 (-2.0, 8.0)으로 확대 (2026Q1 6.42% 클리핑 해소)
    gdp = g(data, "GDP_GROWTH_YOY")
    s, w = score_component(gdp, -2.0, 8.0, weight=2.0)
    components.append(("GDP_GROWTH_YOY", "실질GDP 전년비", gdp, "%",
                        g(data, "GDP_GROWTH_YOY__chg_prev"), g(data, "GDP_GROWTH_YOY__chg_yoy"), s, w))

    # 2. 고용률 (weight 1.0)
    emp = g(data, "EMPLOYMENT_RATE")
    s, w = score_component(emp, 58.0, 65.0, weight=1.0)
    components.append(("EMPLOYMENT_RATE", "고용률", emp, "%",
                        g(data, "EMPLOYMENT_RATE__chg_prev"), g(data, "EMPLOYMENT_RATE__chg_yoy"), s, w))

    # 3. 경기동행지수 순환변동치 (weight 1.5)
    coin = g(data, "CLI_COINCIDENT")
    s, w = score_component(coin, 94.0, 104.0, weight=1.5)
    components.append(("CLI_COINCIDENT", "경기동행지수순환변동", coin, "지수",
                        g(data, "CLI_COINCIDENT__chg_prev"), g(data, "CLI_COINCIDENT__chg_yoy"), s, w))

    # 4. 경기선행지수 순환변동치 (weight 1.5)
    lead = g(data, "CLI_LEADING")
    s, w = score_component(lead, 94.0, 104.0, weight=1.5)
    components.append(("CLI_LEADING", "경기선행지수순환변동", lead, "지수",
                        g(data, "CLI_LEADING__chg_prev"), g(data, "CLI_LEADING__chg_yoy"), s, w))

    # 5. KOSPI (weight 1.0) — 범위 2500~8500으로 조정 (2026년 시장 수준 반영)
    kospi = g(data, "KOSPI")
    s, w = score_component(kospi, 2500.0, 8500.0, weight=1.0)
    components.append(("KOSPI", "KOSPI 지수", kospi, "pt",
                        g(data, "KOSPI__chg_prev"), g(data, "KOSPI__chg_yoy"), s, w))

    # 6. 광공업생산 YoY (weight 1.0) — 실물 생산 활동 반영
    indpro = g(data, "INDPRO_YOY")
    s, w = score_component(indpro, -10.0, 15.0, weight=1.0)
    components.append(("INDPRO_YOY", "광공업생산 전년비", indpro, "%",
                        g(data, "INDPRO_YOY__chg_prev"), g(data, "INDPRO_YOY__chg_yoy"), s, w))

    pairs = [(c[6], c[7]) for c in components]
    total = weighted_mean(pairs)
    return {"score": total, "components": components}


# ---------------------------------------------------------------------------
# 인플레이션 점수 (0-10, 높을수록 강한 인플레이션)
# 5개 요소
# ---------------------------------------------------------------------------
def compute_inflation_score(data: dict) -> dict:
    """인플레이션 점수 계산. 컴포넌트 튜플: (key, label, val, unit, chg_prev, chg_yoy, score, weight)"""
    components = []

    # 1. CPI YoY (weight 2.0)
    cpi = g(data, "CPI_YOY")
    s, w = score_component(cpi, -0.5, 6.0, weight=2.0)
    components.append(("CPI_YOY", "소비자물가 전년비", cpi, "%",
                        g(data, "CPI_YOY__chg_prev"), g(data, "CPI_YOY__chg_yoy"), s, w))

    # 2. 근원 CPI YoY (weight 2.0)
    core = g(data, "CORE_CPI_YOY")
    s, w = score_component(core, 0.0, 5.0, weight=2.0)
    components.append(("CORE_CPI_YOY", "근원CPI 전년비", core, "%",
                        g(data, "CORE_CPI_YOY__chg_prev"), g(data, "CORE_CPI_YOY__chg_yoy"), s, w))

    # 3. PPI YoY (weight 1.5)
    ppi = g(data, "PPI_YOY")
    s, w = score_component(ppi, -3.0, 8.0, weight=1.5)
    components.append(("PPI_YOY", "생산자물가 전년비", ppi, "%",
                        g(data, "PPI_YOY__chg_prev"), g(data, "PPI_YOY__chg_yoy"), s, w))

    # 4. 수입물가 YoY (weight 1.0) — 403Y005/B 수입품물가지수 기반, 범위 확대 적용
    imp = g(data, "IMPORT_PRICE_YOY")
    s, w = score_component(imp, -20.0, 40.0, weight=1.0)
    components.append(("IMPORT_PRICE_YOY", "수입물가 전년비", imp, "%",
                        g(data, "IMPORT_PRICE_YOY__chg_prev"), g(data, "IMPORT_PRICE_YOY__chg_yoy"), s, w))

    # 5. 취업자 증감 (weight 1.0)
    # 임금 데이터가 ECOS에 없어 고용 증감으로 노동수요 압력을 간접 반영.
    # 고용 증가 ≠ 임금 인플레이션이므로 해석 시 한계 유의.
    # chg_prev = 전월 대비 취업자증감 변화분 (천명), 단위 주의: "두 번째 차분"
    emp_chg = g(data, "EMPLOYMENT_CHANGE")
    s, w = score_component(emp_chg, -100.0, 500.0, weight=1.0)
    components.append(("EMPLOYMENT_CHANGE", "취업자수 증감(임금압력 대용)", emp_chg, "천명",
                        g(data, "EMPLOYMENT_CHANGE__chg_prev"), g(data, "EMPLOYMENT_CHANGE__chg_yoy"), s, w))

    pairs = [(c[6], c[7]) for c in components]
    total = weighted_mean(pairs)
    return {"score": total, "components": components}


# ---------------------------------------------------------------------------
# 레짐 분류
# ---------------------------------------------------------------------------
REGIMES = {
    ("high", "high"): {
        "name": "🔥 Overheating",
        "kor": "경기 과열",
        "growth": "강함 (>5)",
        "inflation": "높음 (>5)",
        "implication": "금리 인상 가능성 ↑, 실질금리 상승, 성장주 밸류에이션 압박",
        "asset_hint": "단기채 · 원자재 · 가치주 선호 / 장기채 · 성장주 비중 축소",
    },
    ("high", "low"): {
        "name": "✨ Goldilocks",
        "kor": "골디락스",
        "growth": "강함 (>5)",
        "inflation": "낮음 (≤5)",
        "implication": "위험자산 우호적, 안정적 통화정책, 실적 성장 기대",
        "asset_hint": "주식 · 크레딧 비중 확대 / 방어 자산 비중 축소",
    },
    ("low", "high"): {
        "name": "⚠️ Stagflation",
        "kor": "스태그플레이션",
        "growth": "약함 (≤5)",
        "inflation": "높음 (>5)",
        "implication": "정책 딜레마 (금리 인상 vs 경기 지원), 실질소득 감소",
        "asset_hint": "원자재 · TIPS · 현금 선호 / 주식 · 장기채 모두 불리",
    },
    ("low", "low"): {
        "name": "❄️ Recession Risk",
        "kor": "침체 위험",
        "growth": "약함 (≤5)",
        "inflation": "낮음 (≤5)",
        "implication": "경기 부양 기대, 금리 인하 가능성 ↑, 안전자산 선호",
        "asset_hint": "장기채 · 방어주 · 금 선호 / 경기 민감주 · 크레딧 비중 축소",
    },
}


def classify_regime(growth_score: float | None, inflation_score: float | None) -> dict:
    if growth_score is None or inflation_score is None:
        return {
            "key": ("unknown", "unknown"),
            "name": "⚪ 분류 불가",
            "kor": "데이터 부족",
            "growth": "N/A",
            "inflation": "N/A",
            "implication": "충분한 데이터가 수집된 후 재시도하세요.",
            "asset_hint": "N/A",
        }
    g_state = "high" if growth_score > GROWTH_THRESHOLD else "low"
    i_state = "high" if inflation_score > INFLATION_THRESHOLD else "low"
    regime = REGIMES[(g_state, i_state)].copy()
    regime["key"] = (g_state, i_state)
    return regime


# ---------------------------------------------------------------------------
# 마크다운 보고서 생성
# ---------------------------------------------------------------------------
def build_md(
    growth: dict,
    inflation: dict,
    regime: dict,
    generated_at: str,
) -> str:
    gs = growth["score"]
    is_ = inflation["score"]

    lines = [
        "# ECOS 매크로 레짐 분류 보고서",
        "",
        f"**생성일시**: {generated_at} (KST)",
        "",
        "---",
        "",
        "## 현재 레짐",
        "",
        f"| 구분 | 점수 (0-10) | 판정 |",
        f"|-----|-----------|-----|",
        f"| 성장 점수 | **{fmt(gs)}** | {'강함 (>5)' if gs is not None and gs > GROWTH_THRESHOLD else '약함 (≤5)'} |",
        f"| 인플레이션 점수 | **{fmt(is_)}** | {'높음 (>5)' if is_ is not None and is_ > INFLATION_THRESHOLD else '낮음 (≤5)'} |",
        "",
        f"### 레짐: {regime['name']} ({regime['kor']})",
        "",
        f"| 항목 | 내용 |",
        f"|-----|-----|",
        f"| 성장 | {regime['growth']} |",
        f"| 인플레이션 | {regime['inflation']} |",
        f"| 시사점 | {regime['implication']} |",
        f"| 자산 배분 힌트 | {regime['asset_hint']} |",
        "",
        "---",
        "",
        "## 레짐 매트릭스",
        "",
        "```",
        "             인플레 ↑ (>5)",
        "                  │",
        "  ⚠️ Stagflation  │  🔥 Overheating",
        "   (성장↓ 인플레↑) │  (성장↑ 인플레↑)",
        " ─────────────────┼──────────────────  성장 →",
        "  ❄️ Recession    │  ✨ Goldilocks",
        "   (성장↓ 인플레↓) │  (성장↑ 인플레↓)",
        "                  │",
        "             인플레 ↓ (≤5)",
        "```",
        "",
        "| 레짐 | 성장 | 인플레 | 시사점 |",
        "|-----|-----|-------|------|",
        "| ✨ Goldilocks | >5 | ≤5 | 위험자산 우호, 안정적 정책 |",
        "| 🔥 Overheating | >5 | >5 | 긴축 가능성, 실질금리 상승 |",
        "| ⚠️ Stagflation | ≤5 | >5 | 정책 딜레마, 방어적 포지셔닝 |",
        "| ❄️ Recession Risk | ≤5 | ≤5 | 부양 기대, 안전자산 선호 |",
        "",
        "---",
        "",
        "## 성장 점수 상세 (가중평균)",
        "",
        "> 전기비·YoY비: % 지표는 YoY율 가속도(%p), 지수/pt 지표는 절대 변화",
        "",
        "| 지표 | 값 | 단위 | 전기비 | YoY비 | 성장 점수 기여 (0-10) | 가중치 |",
        "|-----|---|-----|------|------|---------------------|------|",
    ]

    for key, label, val, unit, chg_prev, chg_yoy, score, weight in growth["components"]:
        lines.append(
            f"| {label} | {fmt(val)} | {unit}"
            f" | {fmt_chg(chg_prev)} | {fmt_chg(chg_yoy)}"
            f" | {fmt(score)} | {weight} |"
        )

    lines += [
        f"| **종합 성장 점수** | | | | | **{fmt(gs)}** | — |",
        "",
        "---",
        "",
        "## 인플레이션 점수 상세 (가중평균)",
        "",
        "> 전기비·YoY비: % 지표는 YoY율 가속도(%p), 취업자증감(천명)은 증감폭 변화분",
        "",
        "| 지표 | 값 | 단위 | 전기비 | YoY비 | 인플레 점수 기여 (0-10) | 가중치 |",
        "|-----|---|-----|------|------|----------------------|------|",
    ]

    for key, label, val, unit, chg_prev, chg_yoy, score, weight in inflation["components"]:
        lines.append(
            f"| {label} | {fmt(val)} | {unit}"
            f" | {fmt_chg(chg_prev)} | {fmt_chg(chg_yoy)}"
            f" | {fmt(score)} | {weight} |"
        )

    lines += [
        f"| **종합 인플레 점수** | | | | | **{fmt(is_)}** | — |",
        "",
        "---",
        "",
        "> 출처: 한국은행 ECOS API | 본 보고서는 자동 생성되며 투자 권고가 아닙니다.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("ECOS 레짐 분류 보고서 생성 시작")
    print("=" * 60)

    data = load_data()

    growth = compute_growth_score(data)
    inflation = compute_inflation_score(data)
    regime = classify_regime(growth["score"], inflation["score"])

    print(f"\n  성장 점수:      {fmt(growth['score'])} / 10.0")
    print(f"  인플레 점수:    {fmt(inflation['score'])} / 10.0")
    print(f"  현재 레짐:      {regime['name']} ({regime['kor']})")
    print(f"  시사점:         {regime['implication']}")
    print(f"  자산 배분 힌트: {regime['asset_hint']}")

    generated_at = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")
    md = build_md(growth, inflation, regime, generated_at)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    print(f"\n  Saved: {OUTPUT_MD}")
    print("=" * 60)


if __name__ == "__main__":
    main()
