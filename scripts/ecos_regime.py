"""
scripts/ecos_regime.py
data/macro_latest.csv 를 읽어 성장·인플레이션 점수를 계산하고
2×2 매크로 레짐을 분류한 뒤 data/ecos_regime.md 를 생성합니다.

v3.4 (2026-07-22): 커버리지 신뢰도 표시, CLI 신선도 예외, 스코어링 범위 재조정
  - weighted_mean()은 그대로 두고 coverage_ratio() 신설 — components와 병렬로
    쌓은 base_weights(할인 전 원래 가중치)로 "값이 있는 요소의 가중치 비중"을
    별도 계산. 헤드라인 표에 커버리지 컬럼 추가
  - classify_regime()에 저커버리지(<MIN_COVERAGE=0.5) 분기 추가 — 기존
    None-score "분류 불가" 분기와 별개로, 점수는 있어도 요소 대부분이 결측이면
    레짐 확정 대신 "⚪ 분류 불가(데이터 부족)"로 보류. (2026-07-22 KOSIS 전량
    차단 실측 데이터로 검증: 성장 8%·인플레 38% 커버리지 모두 미달 확인)
  - GDP_GROWTH_YOY 범위 (-2.0, 8.0) → (-2.0, 10.0) — 2026Q1 7.30% 클리핑 해소
  - PPI_YOY 범위 (-3.0, 8.0) → (-3.0, 12.0) — 2026-05 8.51% 클리핑 해소
  - IMPORT_PRICE_YOY: 정상 스코어링 범위(IMPORT_PRICE_NORMAL_RANGE ±10%)와
    극단치 감지 임계(IMPORT_EXTREME_ABS ±30%)를 분리 — 기존엔 둘 다 15.0으로
    같아서 스코어링 범위 상한에 닿기만 해도 자동으로 극단값 취급까지 겹쳤음
  - KOSIS_CLI_COINCIDENT/LEADING: STALE_EXEMPT_SERIES 도입, effective_weight()에
    series_id 옵션 추가 — 구조적 약 2개월 지연에 신선도 할인(×0.7) 미적용
    (kosis_fetch.py STALENESS_EXEMPT와 동일 취지)

v3.3 (2026-07-22): CPI·광공업생산 KOSIS 차단 대응 ECOS 재배포 대체(g_fallback)
  - 인플레 1번째(CPI), 성장 5번째(광공업생산) 요소가 KOSIS 미수집 시
    ECOS CPI_YOY/INDPRO_YOY 로 자동 대체 (ecos_signals.py와 동일 로직)
  - 근원CPI는 검증된 ECOS 대체 코드가 없어 KOSIS 단일 소스 유지

v3.2 (2026-05-27): GDP·신선도 가중치, KOSPI 주석 정정
  - GDP_GROWTH_YOY 가중치 2.0→0.5 (분기 GDP, Q1 단일값)
  - 기준일 2개월+ 지연 지표 가중치 ×0.7
  - KOSPI ECOS 일별(802Y001/D) 최신 반영 — 구조 지연 주석 제거

v3.1 (2026-05-27): 근원CPI·수입물가·인플레 구성 개선
  - 인플레 5번째: KOSIS_RETAIL_YOY 제거 → 성장 축으로 이동 (수요≠물가)
  - 성장 6번째: KOSIS_RETAIL_YOY(w=1.0) 추가 (내수 수요)
  - IMPORT_PRICE_YOY winsorize ±15% + 극단값 가중치 0.5

v3.0 (2026-05-27): ECOS+KOSIS 통합 플랜 v1
  - INPUT_CSV: ecos_latest.csv → macro_latest.csv
  - 성장 점수: 6개→5개 요소, KOSPI 제거
      (KOSPI: 시장 선행지표 성격 → SIG12에서 별도 모니터링)
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

IMPORT_PRICE_NORMAL_RANGE = (-10.0, 10.0)  # 정상 스코어링 범위 (구 IMPORT_PRICE_WINSOR)
IMPORT_EXTREME_ABS   = 30.0           # 극단값(기저효과·관세충격) 감지 임계 — 정상범위와 분리(v3.4)
IMPORT_EXTREME_WEIGHT = 0.5           # 극단값 시 가중치 축소
STALE_MONTHS          = 2             # 이상 지연 시 가중치 축소
STALE_WEIGHT_FACTOR   = 0.7           # 2개월+ 지연 시 base weight × 0.7
GDP_BASE_WEIGHT       = 0.5           # 분기 GDP YoY — Q1 단일값 반영

STALE_EXEMPT_SERIES = {"KOSIS_CLI_COINCIDENT", "KOSIS_CLI_LEADING"}
# 통계청 경기지수 — 구조적 약 2개월 지연이 정상이라 신선도 감가 제외
# (kosis_fetch.py STALENESS_EXEMPT와 동일 취지, v3.4)

MIN_COVERAGE = 0.5   # base weight의 이 비율 미만이 실측이면 레짐 분류 보류 (v3.4)


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


def raw_date(data: dict, series_id: str) -> str:
    return str(data.get(f"{series_id}__date", "N/A"))


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


def months_lag(date_str: str) -> int | None:
    """YYYYMM / YYYYMMDD / YYYYQN 기준일 → 현재 대비 개월 지연."""
    if not date_str or date_str == "N/A":
        return None
    today = datetime.now(_KST).date()
    try:
        if len(date_str) == 6 and date_str.isdigit():
            obs = datetime(int(date_str[:4]), int(date_str[4:6]), 1, tzinfo=_KST).date()
            return (today.year - obs.year) * 12 + (today.month - obs.month)
        if len(date_str) == 8 and date_str.isdigit():
            obs = datetime(
                int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]), tzinfo=_KST
            ).date()
            return (today.year - obs.year) * 12 + (today.month - obs.month)
        if len(date_str) == 6 and "Q" in date_str.upper():
            y = int(date_str[:4])
            q = int(date_str[-1])
            obs_m = (q - 1) * 3 + 1
            obs = datetime(y, obs_m, 1, tzinfo=_KST).date()
            return (today.year - obs.year) * 12 + (today.month - obs.month)
    except (ValueError, TypeError):
        return None
    return None


def effective_weight(base: float, date_str: str, series_id: str | None = None) -> float:
    if series_id in STALE_EXEMPT_SERIES:
        return base
    lag = months_lag(date_str)
    if lag is not None and lag >= STALE_MONTHS:
        return round(base * STALE_WEIGHT_FACTOR, 4)
    return base


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


def coverage_ratio(
    components: list[tuple], base_weights: list[float]
) -> tuple[float | None, float, float]:
    """축(성장/인플레) 커버리지 = 값이 있는 요소들의 base weight 합 / 전체 base weight 합.

    반드시 base weight(할인 전 원래 가중치)로 계산한다 — components[i][7]은 이미
    effective_weight()의 신선도·극단값 할인이 적용된 값이라 이걸 쓰면 그 할인
    계수가 바뀔 때마다 커버리지도 같이 흔들려버린다.
    반환: (0-1 커버리지 비율 또는 None, 커버된 base weight, 전체 base weight)
    """
    total = sum(base_weights)
    if total == 0:
        return None, 0.0, 0.0
    covered = sum(bw for c, bw in zip(components, base_weights) if c[6] is not None)
    return round(covered / total, 4), round(covered, 4), round(total, 4)


def fmt(v: float | None, d: int = 2) -> str:
    return "N/A" if v is None else f"{v:.{d}f}"


def fmt_pct(v: float | None) -> str:
    return "N/A" if v is None else f"{v * 100:.0f}%"


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
    base_weights = []

    # 1. 실질 GDP YoY (weight 0.5) — 분기 GDP, Q1 단일값
    # 범위 (-2.0, 8.0)→(-2.0, 10.0) 확대 (2026Q1 7.30% 클리핑 해소, v3.4)
    gdp_base_w = GDP_BASE_WEIGHT
    gdp = g(data, "GDP_GROWTH_YOY")
    gdp_w = effective_weight(gdp_base_w, raw_date(data, "GDP_GROWTH_YOY"))
    s, w = score_component(gdp, -2.0, 10.0, weight=gdp_w)
    components.append(("GDP_GROWTH_YOY", "실질GDP 전년비", gdp, "%",
                        g(data, "GDP_GROWTH_YOY__chg_prev"),
                        g(data, "GDP_GROWTH_YOY__chg_yoy"),
                        s, w, gdate(data, "GDP_GROWTH_YOY")))
    base_weights.append(gdp_base_w)

    # 2. 고용률 (weight 1.0) — KOSIS 통계청
    emp_base_w = 1.0
    emp = g(data, "KOSIS_EMP_RATE")
    emp_w = effective_weight(emp_base_w, raw_date(data, "KOSIS_EMP_RATE"))
    s, w = score_component(emp, 58.0, 65.0, weight=emp_w)
    components.append(("KOSIS_EMP_RATE", "고용률(15세이상)", emp, "%",
                        g(data, "KOSIS_EMP_RATE__chg_prev"),
                        g(data, "KOSIS_EMP_RATE__chg_yoy"),
                        s, w, gdate(data, "KOSIS_EMP_RATE")))
    base_weights.append(emp_base_w)

    # 3. 경기동행지수 순환변동치 (weight 1.5) — KOSIS 통계청, 약 2개월 지연
    coin_base_w = 1.5
    coin = g(data, "KOSIS_CLI_COINCIDENT")
    coin_w = effective_weight(coin_base_w, raw_date(data, "KOSIS_CLI_COINCIDENT"), series_id="KOSIS_CLI_COINCIDENT")
    s, w = score_component(coin, 94.0, 104.0, weight=coin_w)
    components.append(("KOSIS_CLI_COINCIDENT", "경기동행지수순환변동", coin, "지수",
                        g(data, "KOSIS_CLI_COINCIDENT__chg_prev"),
                        g(data, "KOSIS_CLI_COINCIDENT__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CLI_COINCIDENT")))
    base_weights.append(coin_base_w)

    # 4. 경기선행지수 순환변동치 (weight 1.5) — KOSIS 통계청, 약 2개월 지연
    lead_base_w = 1.5
    lead = g(data, "KOSIS_CLI_LEADING")
    lead_w = effective_weight(lead_base_w, raw_date(data, "KOSIS_CLI_LEADING"), series_id="KOSIS_CLI_LEADING")
    s, w = score_component(lead, 94.0, 104.0, weight=lead_w)
    components.append(("KOSIS_CLI_LEADING", "경기선행지수순환변동", lead, "지수",
                        g(data, "KOSIS_CLI_LEADING__chg_prev"),
                        g(data, "KOSIS_CLI_LEADING__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CLI_LEADING")))
    base_weights.append(lead_base_w)

    # 5. 광공업생산 YoY (weight 1.0) — KOSIS 우선, 차단 시 ECOS 재배포(INDPRO_YOY) 대체
    indpro_base_w = 1.0
    indpro, indpro_src = g_fallback(data, "KOSIS_INDPRO_YOY", "INDPRO_YOY")
    indpro_w = effective_weight(indpro_base_w, raw_date(data, indpro_src))
    s, w = score_component(indpro, -10.0, 15.0, weight=indpro_w)
    indpro_label = "광공업생산 전년비" + (" (ECOS 재배포)" if indpro_src == "INDPRO_YOY" else "")
    components.append((indpro_src, indpro_label, indpro, "%",
                        g(data, f"{indpro_src}__chg_prev"),
                        g(data, f"{indpro_src}__chg_yoy"),
                        s, w, gdate(data, indpro_src)))
    base_weights.append(indpro_base_w)

    # 6. 소매판매 YoY (weight 1.0) — KOSIS 통계청, 내수 수요 (구 인플레 5번째에서 이동)
    retail_base_w = 1.0
    retail = g(data, "KOSIS_RETAIL_YOY")
    retail_w = effective_weight(retail_base_w, raw_date(data, "KOSIS_RETAIL_YOY"))
    s, w = score_component(retail, -5.0, 15.0, weight=retail_w)
    components.append(("KOSIS_RETAIL_YOY", "소매판매 전년비(내수)", retail, "%",
                        g(data, "KOSIS_RETAIL_YOY__chg_prev"),
                        g(data, "KOSIS_RETAIL_YOY__chg_yoy"),
                        s, w, gdate(data, "KOSIS_RETAIL_YOY")))
    base_weights.append(retail_base_w)

    # KOSPI 제거: 시장 선행지표 성격 → SIG12 에서 별도 모니터링

    cov, cov_w, total_w = coverage_ratio(components, base_weights)
    pairs = [(c[6], c[7]) for c in components]
    total = weighted_mean(pairs)
    return {"score": total, "components": components,
            "coverage": cov, "covered_weight": cov_w, "total_weight": total_w}


# ---------------------------------------------------------------------------
# 인플레이션 점수 (0-10, 높을수록 강한 인플레이션)
# 5개 요소 — % 단위 완전 통일 (v3.0)
# ---------------------------------------------------------------------------
def compute_inflation_score(data: dict) -> dict:
    """인플레이션 점수 계산.
    컴포넌트 튜플: (key, label, val, unit, chg_prev, chg_yoy, score, weight, date)
    """
    components = []
    base_weights = []

    # 1. CPI YoY (weight 2.0) — KOSIS 우선, 차단 시 ECOS 재배포(CPI_YOY, 901Y009/0) 대체
    cpi_base_w = 2.0
    cpi, cpi_src = g_fallback(data, "KOSIS_CPI_YOY", "CPI_YOY")
    cpi_w = effective_weight(cpi_base_w, raw_date(data, cpi_src))
    s, w = score_component(cpi, -0.5, 6.0, weight=cpi_w)
    cpi_label = "소비자물가 전년비" + (" (ECOS 재배포)" if cpi_src == "CPI_YOY" else "")
    components.append((cpi_src, cpi_label, cpi, "%",
                        g(data, f"{cpi_src}__chg_prev"),
                        g(data, f"{cpi_src}__chg_yoy"),
                        s, w, gdate(data, cpi_src)))
    base_weights.append(cpi_base_w)

    # 2. 근원CPI YoY (weight 2.0) — 통계청 농산물·석유류제외, KOSIS 단일 소스
    # (ECOS 재배포 후보 코드 미검증 — StatisticItemList 조회 전까지 대체 불가)
    core_base_w = 2.0
    core = g(data, "KOSIS_CORE_CPI_YOY")
    core_w = effective_weight(core_base_w, raw_date(data, "KOSIS_CORE_CPI_YOY"))
    s, w = score_component(core, 0.0, 5.0, weight=core_w)
    components.append(("KOSIS_CORE_CPI_YOY", "근원CPI 전년비(통계청)", core, "%",
                        g(data, "KOSIS_CORE_CPI_YOY__chg_prev"),
                        g(data, "KOSIS_CORE_CPI_YOY__chg_yoy"),
                        s, w, gdate(data, "KOSIS_CORE_CPI_YOY")))
    base_weights.append(core_base_w)

    # 3. PPI YoY (weight 1.5) — ECOS 한국은행
    # 범위 (-3.0, 8.0)→(-3.0, 12.0) 확대 (2026-05 8.51% 클리핑 해소, v3.4)
    ppi_base_w = 1.5
    ppi = g(data, "PPI_YOY")
    ppi_w = effective_weight(ppi_base_w, raw_date(data, "PPI_YOY"))
    s, w = score_component(ppi, -3.0, 12.0, weight=ppi_w)
    components.append(("PPI_YOY", "생산자물가 전년비", ppi, "%",
                        g(data, "PPI_YOY__chg_prev"),
                        g(data, "PPI_YOY__chg_yoy"),
                        s, w, gdate(data, "PPI_YOY")))
    base_weights.append(ppi_base_w)

    # 4. 수입물가 YoY (weight 1.0) — ECOS. 정상 스코어링 범위(±10%)와 극단값
    # 감지 임계(±30%)를 분리(v3.4) — 예전엔 둘 다 15.0으로 같아서 스코어링
    # 범위 상한에 닿기만 해도 자동으로 극단값 취급까지 겹쳤음.
    imp_base_w = 1.0
    imp = g(data, "IMPORT_PRICE_YOY")
    imp_w = effective_weight(imp_base_w, raw_date(data, "IMPORT_PRICE_YOY"))
    if imp is not None and abs(imp) > IMPORT_EXTREME_ABS:
        imp_w = min(imp_w, IMPORT_EXTREME_WEIGHT)
    s, w = score_component(imp, *IMPORT_PRICE_NORMAL_RANGE, weight=imp_w)
    components.append(("IMPORT_PRICE_YOY", "수입물가 전년비", imp, "%",
                        g(data, "IMPORT_PRICE_YOY__chg_prev"),
                        g(data, "IMPORT_PRICE_YOY__chg_yoy"),
                        s, w, gdate(data, "IMPORT_PRICE_YOY")))
    base_weights.append(imp_base_w)

    cov, cov_w, total_w = coverage_ratio(components, base_weights)
    pairs = [(c[6], c[7]) for c in components]
    total = weighted_mean(pairs)
    return {"score": total, "components": components,
            "coverage": cov, "covered_weight": cov_w, "total_weight": total_w}


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


def classify_regime(
    growth_score: float | None,
    inflation_score: float | None,
    growth_coverage: float | None = None,
    inflation_coverage: float | None = None,
) -> dict:
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

    # 커버리지가 낮으면 점수는 있어도 레짐 판정을 보류한다 (v3.4).
    # 예: 요소 1개만으로 계산된 점수가 우연히 5를 넘겨도 그걸로 Overheating을
    # 단정하면 안 됨 — weighted_mean()은 결측 요소를 그냥 건너뛰기 때문에
    # 헤드라인 점수만 봐서는 몇 개 중 몇 개로 계산됐는지 알 수 없다.
    low_cov = (
        (growth_coverage is not None and growth_coverage < MIN_COVERAGE)
        or (inflation_coverage is not None and inflation_coverage < MIN_COVERAGE)
    )
    if low_cov:
        return {
            "key": ("unknown", "unknown"),
            "name": "⚪ 분류 불가",
            "kor": "데이터 부족 (저커버리지)",
            "growth": f"{growth_score:.2f} (커버리지 {fmt_pct(growth_coverage)})",
            "inflation": f"{inflation_score:.2f} (커버리지 {fmt_pct(inflation_coverage)})",
            "implication": (
                f"커버리지 기준({MIN_COVERAGE:.0%}) 미달 — 성장 {fmt_pct(growth_coverage)}, "
                f"인플레 {fmt_pct(inflation_coverage)}. 결측 지표 보강 후 재시도하세요."
            ),
            "asset_hint": "N/A (데이터 보강 필요)",
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
        f"| 구분 | 점수 (0-10) | 커버리지 | 판정 |",
        f"|-----|-----------|--------|-----|",
        f"| 성장 점수 | **{fmt(gs)}** | {fmt_pct(growth.get('coverage'))} | "
        f"{'강함 (>5)' if gs is not None and gs > GROWTH_THRESHOLD else ('약함 (≤5)' if gs is not None else '⚠️ 데이터 부족 (N/A)')} |",
        f"| 인플레이션 점수 | **{fmt(is_)}** | {fmt_pct(inflation.get('coverage'))} | "
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
        "> KOSPI 제외: 시장 선행지표 → SIG12 에서 별도 모니터링",
        "> GDP 가중치 0.5 (분기), 2개월+ 지연 지표 가중치 ×0.7 (CLI 동행·선행지수 제외 — 구조적 지연 정상)",
        "> 6번째: 소매판매 YoY — 구 인플레 5번째에서 이동 (내수 수요)",
        f"> 커버리지: {fmt_pct(growth.get('coverage'))} "
        f"({fmt(growth.get('covered_weight'))}/{fmt(growth.get('total_weight'))} 가중치) "
        f"— {MIN_COVERAGE:.0%} 미만 시 레짐 분류 보류 (v3.4)",
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
        "> 수입물가: 정상 스코어링 범위 ±10%, |YoY|>30% 시 가중치 0.5 (기저효과·관세충격, v3.4 임계 분리)",
        f"> 커버리지: {fmt_pct(inflation.get('coverage'))} "
        f"({fmt(inflation.get('covered_weight'))}/{fmt(inflation.get('total_weight'))} 가중치) "
        f"— {MIN_COVERAGE:.0%} 미만 시 레짐 분류 보류 (v3.4)",
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
    regime    = classify_regime(
        growth["score"], inflation["score"],
        growth["coverage"], inflation["coverage"],
    )

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
