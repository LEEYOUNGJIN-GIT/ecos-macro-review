"""
scripts/ecos_regime.py
data/macro_latest.csv 를 읽어 성장·인플레이션 점수를 계산하고
2×2 매크로 레짐을 분류한 뒤 data/ecos_regime.md 를 생성합니다.

v3.1 (2026-05-27): 근원CPI·수입물가·인플레 구성 개선
  - 인플레 5번째: KOSIS_RETAIL_YOY 제거 → 성장 축으로 이동 (수요≠물가)
  - 성장 6번째: KOSIS_RETAIL_YOY(w=1.0) 추가 (내수 수요)
  - IMPORT_PRICE_YOY winsorize ±15% + 극단값 가중치 0.5

v3.0 (2026-05-27): ECOS+KOSIS 통합 플랜 v1
  - INPUT_CSV: ecos_latest.csv → macro_latest.csv
  - 성장 점수: 6개→5개 요소, KOSPI 제거
      (KOSPI: ECOS 구조 지연 ~7개월 + 시장 선행지표 성격 → SIG12에서 별도 모니터링)
  - 인플레 점수: EMPLOYMENT_CHANGE(천명) → KOSIS_RETAIL_YOY(% YoY)
      (단위 이질성 해소: 모든 인플레 요소 % 단위로 통일)
  - series_id 키 매핑 9개: KOSIS_ 접두사로 전환
  - 컴포넌트 튜플에 date 필드 추가 (9번째)
  - build_md() 성장·인플레 테이블에 기준일 컬럼 추가
  - 보고서 footer → ECOS + KOSIS 출처 반영

v2.5 (2026-05-27):
  - load_data(): chg_prev / chg_yoy 컬럼 로딩 추가
  - compute_growth/inflation_score(): 컴포넌트 튜플에 chg_prev/chg_yoy 추가
  - build_md(): 성장·인플레 점수 테이블에 전기비/YoY비 컬럼 추가

v2.2 (2026-05-26):
  - CORE_CPI_YOY 데이터 정정으로 인플레이션 점수 자동 개선

v2.1 (2026-05-26):
  - 성장 점수에 INDPRO_YOY(광공업생산 전년비, weight 1.0) 추가 → 6개 요소

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

DATA_DIR   = Path(__file__).parent.parent / "data"
INPUT_CSV  = DATA_DIR / "macro_latest.csv"
OUTPUT_MD  = DATA_DIR / "ecos_regime.md"

GROWTH_THRESHOLD    = 5.0
INFLATION_THRESHOLD = 5.0

IMPORT_PRICE_WINSOR = (-15.0, 15.0)   # % YoY — 기저효과·관세충격 클리핑
IMPORT_EXTREME_ABS  = 15.0            # winsorize 적용 임계
IMPORT_EXTREME_WEIGHT = 0.5           # 극단값 시 가중치 축소


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def load_data() -> dict[str, float | None]:
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
    v = data.get(key)
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else v


def gdate(data: dict, series_id: str) -> str:
    raw = str(data.get(f"{series_id}__date", "N/A"))
    if len(raw) == 6 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:]}"
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def score_component(
    value: float | None,
    low: float,
    high: float,
    weight: float = 1.0,
    invert: bool = False,
) -> tuple[float | None, float]:
    if value is None:
        return None, weight
    clipped = max(low, min(high, value))
    raw     = (clipped - low) / (high - low) * 10.0
    scored  = 10.0 - raw if invert else raw
    return round(scored, 4), weight


def weighted_mean(pairs: list[tuple[float | None, float]]) -> float | None:
    valid   = [(v, w) for v, w in pairs if v is not None]
    if not valid:
        return None
    total_w = sum(w for _, w in valid)
    return round(sum(v * w for v, w in valid) / total_w, 4)


def fmt(v: float | None, d: int = 2) -> str:
    return "N/A" if v is None else f"{v:.{d}f}"


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


# ---------------------------------------------------------------------------
# 성장 점수 (0-10, 높을수록 강한 성장)
# 5개 요소 — KOSPI 제거 (v3.0)
# ---------------------------------------------------------------------------
def compute_growth_score(data: dict) -> dict:
    """성장 점수 계산.
    컴포넌트 튜플: (key, label, val, unit, chg_prev, chg_yoy, score, weight, date)
    """
    components = []

    # 1. 실질 GDP YoY (weight 2.0) — 잠재성장률 대비 위치
    gdp = g(data, "GDP_GROWTH_YOY")
    s, w = score_component(gdp, -2.0, 8.0, weight=2.0)
    components.append(("GDP_GROWTH_YOY", "실질GDP 전년비", gdp, "%",
                        g(data, "GDP_GROWTH_YOY__chg_prev"),
                        g(data, "GDP_GROWTH_YOY__chg_yoy"),
                        s, w, gdate(data, "GDP_GROWTH_YOY")))

    # 2. 고용률 (weight 1.0) — KOSIS 통계청
    emp = g(data, "KOSIS_EMP_RATE")
    s, w = score_component(emp, 58.0, 65.0, weight=1.0)
    components.append(("KOSIS_EMP_RATE", "고용률(15세이상)", emp, "%",
                        g(data, "KOSIS_EMP_RATE__chg_prev"),
                        g(data, "KOSIS_EMP_RATE__chg_yoy"),
                        s, w, gdate(data, "KOSIS_EMP_RATE")))

    # 3. 경기동행지수 순환변동치 (weight 1.5) — KOSIS 통계청, 약 2개월 지연
    coin = g(data, "KOSIS_CLI_COINCIDENT")
    s, w = score_component(coin, 94.0, 104.0, weight=1.5)
    components.append(("KOSIS_CLI_COINCIDENT", "경기동행지수순환변동", coin, "지수",
                        g(data, "KOSIS_CLI_COINCIDENT__chg_prev"),
                        g(data, "KOSIS_CLI_COINCIDENT__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CLI_COINCIDENT")))

    # 4. 경기선행지수 순환변동치 (weight 1.5) — KOSIS 통계청, 약 2개월 지연
    lead = g(data, "KOSIS_CLI_LEADING")
    s, w = score_component(lead, 94.0, 104.0, weight=1.5)
    components.append(("KOSIS_CLI_LEADING", "경기선행지수순환변동", lead, "지수",
                        g(data, "KOSIS_CLI_LEADING__chg_prev"),
                        g(data, "KOSIS_CLI_LEADING__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CLI_LEADING")))

    # 5. 광공업생산 YoY (weight 1.0) — KOSIS 통계청, 실물 생산 활동
    indpro = g(data, "KOSIS_INDPRO_YOY")
    s, w = score_component(indpro, -10.0, 15.0, weight=1.0)
    components.append(("KOSIS_INDPRO_YOY", "광공업생산 전년비", indpro, "%",
                        g(data, "KOSIS_INDPRO_YOY__chg_prev"),
                        g(data, "KOSIS_INDPRO_YOY__chg_yoy"),
                        s, w, gdate(data, "KOSIS_INDPRO_YOY")))

    # 6. 소매판매 YoY (weight 1.0) — KOSIS 통계청, 내수 수요 (구 인플레 5번째에서 이동)
    retail = g(data, "KOSIS_RETAIL_YOY")
    s, w = score_component(retail, -5.0, 15.0, weight=1.0)
    components.append(("KOSIS_RETAIL_YOY", "소매판매 전년비(내수)", retail, "%",
                        g(data, "KOSIS_RETAIL_YOY__chg_prev"),
                        g(data, "KOSIS_RETAIL_YOY__chg_yoy"),
                        s, w, gdate(data, "KOSIS_RETAIL_YOY")))

    # KOSPI 제거 이유: ECOS 구조 지연 ~7개월 + 시장 선행지표 성격
    # → SIG12 에서 별도 모니터링

    pairs = [(c[6], c[7]) for c in components]
    total = weighted_mean(pairs)
    return {"score": total, "components": components}


# ---------------------------------------------------------------------------
# 인플레이션 점수 (0-10, 높을수록 강한 인플레이션)
# 5개 요소 — % 단위 완전 통일 (v3.0)
# ---------------------------------------------------------------------------
def compute_inflation_score(data: dict) -> dict:
    """인플레이션 점수 계산.
    컴포넌트 튜플: (key, label, val, unit, chg_prev, chg_yoy, score, weight, date)
    """
    components = []

    # 1. CPI YoY (weight 2.0) — KOSIS 통계청, BOK 목표 2%
    cpi = g(data, "KOSIS_CPI_YOY")
    s, w = score_component(cpi, -0.5, 6.0, weight=2.0)
    components.append(("KOSIS_CPI_YOY", "소비자물가 전년비", cpi, "%",
                        g(data, "KOSIS_CPI_YOY__chg_prev"),
                        g(data, "KOSIS_CPI_YOY__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CPI_YOY")))

    # 2. 근원CPI YoY (weight 2.0) — 통계청 농산물·석유류제외
    core = g(data, "KOSIS_CORE_CPI_YOY")
    s, w = score_component(core, 0.0, 5.0, weight=2.0)
    components.append(("KOSIS_CORE_CPI_YOY", "근원CPI 전년비(통계청)", core, "%",
                        g(data, "KOSIS_CORE_CPI_YOY__chg_prev"),
                        g(data, "KOSIS_CORE_CPI_YOY__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CORE_CPI_YOY")))

    # 3. PPI YoY (weight 1.5) — ECOS 한국은행
    ppi = g(data, "PPI_YOY")
    s, w = score_component(ppi, -3.0, 8.0, weight=1.5)
    components.append(("PPI_YOY", "생산자물가 전년비", ppi, "%",
                        g(data, "PPI_YOY__chg_prev"),
                        g(data, "PPI_YOY__chg_yoy"),
                        s, w, gdate(data, "PPI_YOY")))

    # 4. 수입물가 YoY (weight 1.0) — ECOS, winsorize ±15% (기저효과 왜곡 방지)
    imp = g(data, "IMPORT_PRICE_YOY")
    imp_w = 1.0
    imp_score_val = imp
    if imp is not None and abs(imp) > IMPORT_EXTREME_ABS:
        lo, hi = IMPORT_PRICE_WINSOR
        imp_score_val = max(lo, min(hi, imp))
        imp_w = IMPORT_EXTREME_WEIGHT
    s, w = score_component(imp_score_val, *IMPORT_PRICE_WINSOR, weight=imp_w)
    components.append(("IMPORT_PRICE_YOY", "수입물가 전년비", imp, "%",
                        g(data, "IMPORT_PRICE_YOY__chg_prev"),
                        g(data, "IMPORT_PRICE_YOY__chg_yoy"),
                        s, w, gdate(data, "IMPORT_PRICE_YOY")))

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
    g_state = "high" if growth_score    > GROWTH_THRESHOLD    else "low"
    i_state = "high" if inflation_score > INFLATION_THRESHOLD else "low"
    regime  = REGIMES[(g_state, i_state)].copy()
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
    gs  = growth["score"]
    is_ = inflation["score"]

    lines = [
        "# ECOS + KOSIS 매크로 레짐 분류 보고서",
        "",
        f"**생성일시**: {generated_at} (KST)",
        "",
        "---",
        "",
        "## 현재 레짐",
        "",
        f"| 구분 | 점수 (0-10) | 판정 |",
        f"|-----|-----------|-----|",
        f"| 성장 점수 | **{fmt(gs)}** | "
        f"{'강함 (>5)' if gs is not None and gs > GROWTH_THRESHOLD else ('약함 (≤5)' if gs is not None else '⚠️ 데이터 부족 (N/A)')} |",
        f"| 인플레이션 점수 | **{fmt(is_)}** | "
        f"{'높음 (>5)' if is_ is not None and is_ > INFLATION_THRESHOLD else ('낮음 (≤5)' if is_ is not None else '⚠️ 데이터 부족 (N/A)')} |",
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
        "## 성장 점수 상세 (가중평균, 6개 요소)",
        "",
        "> 전기비·YoY비: % 지표는 YoY율 가속도(%p), 지수 지표는 절대 변화",
        "> KOSPI 제외: ECOS 구조 지연 ~7개월, SIG12 에서 별도 모니터링",
        "> 6번째: 소매판매 YoY — 구 인플레 5번째에서 이동 (내수 수요)",
        "",
        "| 지표 | 값 | 단위 | 기준일 | 전기비 | YoY비 | 성장 점수 기여 (0-10) | 가중치 |",
        "|-----|---|-----|------|------|------|---------------------|------|",
    ]

    for key, label, val, unit, chg_prev, chg_yoy, score, weight, obs_date in growth["components"]:
        lines.append(
            f"| {label} | {fmt(val)} | {unit}"
            f" | {obs_date} | {fmt_chg(chg_prev)} | {fmt_chg(chg_yoy)}"
            f" | {fmt(score)} | {weight} |"
        )

    lines += [
        f"| **종합 성장 점수** | | | | | | **{fmt(gs)}** | — |",
        "",
        "---",
        "",
        "## 인플레이션 점수 상세 (가중평균, 4개 요소)",
        "",
        "> 전기비·YoY비: % 지표는 YoY율 가속도(%p)",
        "> 수입물가: ±15% winsorize, |YoY|>15% 시 가중치 0.5 (기저효과·관세충격)",
        "",
        "| 지표 | 값 | 단위 | 기준일 | 전기비 | YoY비 | 인플레 점수 기여 (0-10) | 가중치 |",
        "|-----|---|-----|------|------|------|----------------------|------|",
    ]

    for key, label, val, unit, chg_prev, chg_yoy, score, weight, obs_date in inflation["components"]:
        lines.append(
            f"| {label} | {fmt(val)} | {unit}"
            f" | {obs_date} | {fmt_chg(chg_prev)} | {fmt_chg(chg_yoy)}"
            f" | {fmt(score)} | {weight} |"
        )

    lines += [
        f"| **종합 인플레 점수** | | | | | | **{fmt(is_)}** | — |",
        "",
        "---",
        "",
        "> ※ KOSPI는 레짐 성장 점수 제외 (SIG12에서 별도 모니터링)",
        "> 출처: 한국은행 ECOS API + 통계청 KOSIS API | "
        "본 보고서는 자동 생성되며 투자 권고가 아닙니다.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 엔트리포인트
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("레짐 분류 보고서 생성 시작 (ECOS + KOSIS)")
    print("=" * 60)

    data = load_data()

    growth    = compute_growth_score(data)
    inflation = compute_inflation_score(data)
    regime    = classify_regime(growth["score"], inflation["score"])

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
