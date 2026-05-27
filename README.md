# ECOS + KOSIS 한국 거시경제 자동 모니터링

한국은행 ECOS API (21개) + 통계청·관세청 KOSIS API (14개) = **총 35개 지표**를 매일 자동 수집·분석하고 Claude.ai 프로젝트에 동기화하는 시스템입니다.

---

## 아키텍처

```
[ECOS API]          [KOSIS API]
 21개 지표           14개 지표
 ecos_fetch.py       kosis_fetch.py
      │                   │
      └───────┬───────────┘
              ▼
       merge_macro.py
    data/macro_latest.csv
    (35개 통합, source 컬럼)
              │
       ┌──────┴──────┐
       ▼             ▼
 ecos_signals.py  ecos_regime.py
  11개 신호 계산    레짐 분류
       │             │
       ▼             ▼
 ecos_signals.md  ecos_regime.md
       │
       ▼
 sync_claude_project.yml
 → Claude.ai Project 자동 동기화
```

---

## 지표 목록 (35개)

### ECOS 유지 21개 (한국은행 원천)

| series_id | 지표명 | 단위 | 신호/레짐 사용 |
|-----------|--------|------|-------------|
| BOK_BASE_RATE | 한국은행 기준금리 | % | SIG01, SIG02 |
| GOV_BOND_3Y | 국고채 3년 | % | SIG07 파생 |
| GOV_BOND_10Y | 국고채 10년 | % | SIG01 |
| CD_91D | CD 91일 | % | SIG07 파생 |
| CORP_BOND_AA_MINUS | 회사채 AA- | % | 팩트 전용 |
| CORP_BOND_BBB_MINUS | 회사채 BBB- | % | SIG07 파생 |
| PPI_YOY | 생산자물가 전년비 | % YoY | SIG03, 레짐인플레(w=1.5) |
| IMPORT_PRICE_YOY | 수입물가 전년비 | % YoY | 레짐인플레(w=1.0) |
| GDP_GROWTH_QOQ | 실질GDP 전기비 | % | 팩트 전용 |
| GDP_GROWTH_YOY | 실질GDP 전년비 | % | 레짐성장(w=2.0) |
| M2_YOY | M2 광의통화 전년비 | % | 팩트 전용 |
| BASE_MONEY | 본원통화 잔액 | 십억원 | 팩트 전용 |
| BANK_LOANS | 예금은행 총대출금 | 십억원 | 팩트 전용 |
| KB_HOUSE_YOY | KB주택매매가격 전년비 | % YoY | SIG11 |
| KB_JEONSE_YOY | KB주택전세가격 전년비 | % YoY | SIG11 |
| HOUSING_START | 주택착공지수 | 지수 | SIG11 |
| USD_KRW | 원/달러 환율 월평균 | 원 | 팩트 전용 |
| CD_BOK_SPREAD | CD-기준금리 스프레드 (파생) | %p | SIG07 |
| CREDIT_SPREAD | 회사채BBB-국채3Y 스프레드 (파생) | %p | SIG07 |
| KOSPI | KOSPI 지수 | pt | **SIG12 전용 — 레짐 성장 제외** |
| KOSDAQ | KOSDAQ 지수 | pt | 팩트 전용 |

> **KOSPI**: ECOS 구조적 지연 ~6-7개월. 레짐 성장 점수에서 제외, SIG12에서만 사용.

### KOSIS 신규 14개 (통계청·관세청 원천)

| series_id | 지표명 | 단위 | 신호/레짐 사용 | 발표지연 |
|-----------|--------|------|-------------|---------|
| KOSIS_CPI_YOY | 소비자물가 전년동월비 | % YoY | SIG03, 레짐인플레(w=2.0) | 익월 7일 |
| KOSIS_CORE_CPI_YOY | 근원물가 전년동월비 (OECD방식) | % YoY | SIG02, SIG03, 레짐인플레(w=2.0) | 익월 7일 |
| KOSIS_UNEMP_RATE | 실업률 | % | SIG05 | 익월 15일 |
| KOSIS_EMP_RATE | 고용률(15세이상) | % | SIG05, 레짐성장(w=1.0) | 익월 15일 |
| KOSIS_LABOR_PART | 경제활동참가율 | % | **팩트 전용** | 익월 15일 |
| KOSIS_EMP_CHANGE | 취업자수 전년동기 증감 | 천명 | SIG05 | 익월 15일 |
| KOSIS_CLI_COINCIDENT | 동행지수 순환변동치 | 지수(100기준) | SIG08, 레짐성장(w=1.5) | 약 2개월 |
| KOSIS_CLI_LEADING | 선행지수 순환변동치 | 지수(100기준) | SIG08, 레짐성장(w=1.5) | 약 2개월 |
| KOSIS_INDPRO_YOY | 광공업생산지수 전년비 | % YoY | SIG09, 레짐성장(w=1.0) | 익월 말 |
| KOSIS_EXPORT_YOY | 수출 전년동월비 (통관기준) | % YoY | SIG10 | 익월 1~5일 |
| KOSIS_IMPORT_YOY | 수입 전년동월비 (통관기준) | % YoY | SIG10 참고 | 익월 1~5일 |
| KOSIS_RETAIL_YOY | 소매판매 전년동월비 | % YoY | SIG06, 레짐인플레(w=1.0) | 익월 말 |
| KOSIS_SERVICE_PROD_YOY | 서비스업생산지수 전년비 | % YoY | SIG06 | 익월 말 |
| KOSIS_TRADE_BALANCE | 무역수지 | 백만달러 | **팩트 전용** | 익월 1~5일 |

> **KOSIS_CORE_CPI_YOY**: OECD방식(식품·에너지제외). 구 ECOS QB(농산물·석유류제외)와 정의 상이.
> **팩트 전용**: 신호/레짐 점수 산정에 미사용, 분석 참고 전용.
> **⚠️ tblId/itmId 초안값**: 최초 실행 전 `python kosis_fetch.py --validate` 로 검증 필수.

---

## 신호 대시보드 (11개)

| ID | 신호명 | 입력 지표 | 레인지 |
|----|--------|---------|-------|
| SIG01 | 장단기 금리 스프레드 | GOV_BOND_10Y - BOK_BASE_RATE | %p |
| SIG02 | 실질금리 갭 | BOK_BASE_RATE - KOSIS_CORE_CPI_YOY | %p |
| SIG03 | 인플레이션 레짐 | KOSIS_CPI_YOY, KOSIS_CORE_CPI_YOY, PPI_YOY | % 복합 |
| SIG05 | 노동시장 종합 | KOSIS_UNEMP_RATE, KOSIS_EMP_CHANGE, KOSIS_EMP_RATE | % |
| SIG06 | 내수·소비 | KOSIS_RETAIL_YOY, KOSIS_SERVICE_PROD_YOY | % YoY |
| SIG07 | 신용 스트레스 | CREDIT_SPREAD, CD_BOK_SPREAD | %p |
| SIG08 | 경기 사이클 | KOSIS_CLI_COINCIDENT, KOSIS_CLI_LEADING | 지수 |
| SIG09 | 산업생산 모멘텀 | KOSIS_INDPRO_YOY | % YoY |
| SIG10 | 수출 모멘텀 | KOSIS_EXPORT_YOY, KOSIS_IMPORT_YOY | % YoY |
| SIG11 | 주택시장 | KB_HOUSE_YOY, KB_JEONSE_YOY, HOUSING_START | % / 지수 |
| SIG12 | KOSPI 레짐 | KOSPI | pt |

> **SIG04** 기대인플레 디앵커링: ECOS 미수록, BOK 서베이 데이터 비공개.

---

## 레짐 분류 (2×2 매트릭스)

성장 점수(5개 요소) × 인플레이션 점수(5개 요소)로 아래 4가지 레짐 분류:

| 레짐 | 성장 | 인플레 |
|------|------|-------|
| ✨ Goldilocks | 강함(>5) | 낮음(≤5) |
| 🔥 Overheating | 강함(>5) | 높음(>5) |
| ⚠️ Stagflation | 약함(≤5) | 높음(>5) |
| ❄️ Recession Risk | 약함(≤5) | 낮음(≤5) |

**성장 5요소**: GDP_GROWTH_YOY(w=2.0), KOSIS_EMP_RATE(w=1.0), KOSIS_CLI_COINCIDENT(w=1.5), KOSIS_CLI_LEADING(w=1.5), KOSIS_INDPRO_YOY(w=1.0)

**인플레 5요소**: KOSIS_CPI_YOY(w=2.0), KOSIS_CORE_CPI_YOY(w=2.0), PPI_YOY(w=1.5), IMPORT_PRICE_YOY(w=1.0), KOSIS_RETAIL_YOY(w=1.0)

> **KOSPI 제외**: ECOS 구조 지연 ~7개월 + 시장 선행지표 성격 → 레짐 성장 점수 제외, SIG12 전용

---

## 파일 구조

```
ecos-macro-review/
├── ecos_fetch.py                  ECOS 21개 지표 수집
├── kosis_fetch.py                 KOSIS 14개 지표 수집 (신규)
├── scripts/
│   ├── merge_macro.py             ECOS+KOSIS 병합 → macro_latest.csv (신규)
│   ├── ecos_signals.py            11개 신호 계산 (macro_latest.csv 입력)
│   └── ecos_regime.py             레짐 분류 (macro_latest.csv 입력)
├── data/
│   ├── ecos_latest.csv / .md      ECOS 21개 원천 (기준일 컬럼 포함)
│   ├── kosis_latest.csv / .md     KOSIS 14개 원천 (기준일+발표지연 포함)
│   ├── macro_latest.csv           통합 35개 + source 컬럼
│   ├── ecos_signals.md            신호 대시보드 (기준일 이질성 경고 포함)
│   └── ecos_regime.md             레짐 분류 보고서 (기준일 컬럼 포함)
├── reference/
│   ├── KOSIS_Only_Macro_Indicators.md
│   └── Daily_Batch_Notable_Indicators.md
├── .github/workflows/
│   ├── ecos_daily.yml             일일 데이터 수집 → 분석 자동화
│   └── sync_claude_project.yml    Claude.ai 동기화
└── claude_project_instructions.md Claude.ai 분석 가이드
```

---

## 자동화 워크플로

매일 KST 08:30 실행 (`ecos_daily.yml`):

```
Step 1a: ecos_fetch.py     (ECOS_API_KEY)   → data/ecos_latest.csv/.md
Step 1b: kosis_fetch.py    (KOSIS_API_KEY)  → data/kosis_latest.csv/.md
Step 1c: merge_macro.py                     → data/macro_latest.csv
Step 2:  ecos_signals.py                    → data/ecos_signals.md
Step 3:  ecos_regime.py                     → data/ecos_regime.md
Step 4:  git commit & push data/
```

이후 `sync_claude_project.yml`이 완료 이벤트를 받아 4개 `.md` 파일을 Claude.ai 프로젝트에 자동 동기화합니다.

---

## 설정

### GitHub Secrets 등록 (2개)

| Secret 이름 | 설명 | 발급처 |
|------------|------|-------|
| `ECOS_API_KEY` | 한국은행 ECOS Open API 키 | https://ecos.bok.or.kr/api/ |
| `KOSIS_API_KEY` | KOSIS Open API 키 | https://kosis.kr/openapi/ |

기타 Claude.ai 동기화용 Secrets: `CLAUDE_SESSION_KEY`, `CLAUDE_ORG_ID`, `CLAUDE_PROJECT_ID`

### KOSIS tblId 최초 검증

KOSIS API key 발급 후 로컬에서 반드시 실행:

```bash
export KOSIS_API_KEY=your_key
python kosis_fetch.py --validate
```

`[WARN]` 항목은 [KOSIS 통합검색](https://kosis.kr/statHtml/statHtml.do)에서 올바른 `tblId`, `itmId`, `objL1` 확인 후 `kosis_fetch.py` 의 `KOSIS_SERIES` 레지스트리를 수정하세요.

### 로컬 실행

```bash
pip install -r requirements.txt

# 개별 실행
python ecos_fetch.py
python kosis_fetch.py
python scripts/merge_macro.py
python scripts/ecos_signals.py
python scripts/ecos_regime.py
```

---

## 데이터 신선도

| 지표 그룹 | 발표 주기 | 발표일 기준 |
|----------|---------|-----------|
| 수출·수입 (통관) | 월 1회 | 익월 1~5일 |
| CPI·근원CPI | 월 1회 | 익월 7일경 |
| 고용 (취업자·실업률) | 월 1회 | 익월 15일경 |
| 광공업생산·소매판매 | 월 1회 | 익월 말 |
| 경기종합지수 | 월 1회 | **약 2개월 지연** (통계청 특성) |
| GDP | 분기 1회 | 잠정치 25일경 |
| KOSPI | 일별 | ECOS ~6-7개월 지연 (구조적 특성) |

---

## 주요 설계 결정

- **KOSPI 레짐 제외**: ECOS 구조 지연 ~7개월로 현재 시황 미반영. SIG12 전용으로 추적.
- **KOSIS_CORE_CPI_YOY**: OECD방식(식품·에너지제외)로 전환. 구 ECOS QB(농산물·석유류제외)와 정의 상이.
- **단위 통일**: 인플레이션 점수 5요소 모두 % YoY로 통일 (구 취업자증감 천명 제거).
- **기준일 표기**: 모든 출력 보고서에 지표별 기준일 컬럼 추가로 시의성 투명화.
- **KOSIS_CAPEX_YOY**: tblId 미확인으로 Phase 2 이후 추가 예정.

---

> **면책**: 본 프로젝트는 자동 생성 정보 제공 목적이며, 투자 권고가 아닙니다.
> 출처: 한국은행 ECOS API + 통계청·관세청 KOSIS API
