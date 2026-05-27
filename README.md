# ECOS + KOSIS 한국 거시경제 자동 모니터링

한국은행 ECOS API (21개) + 통계청 KOSIS API (11개) = **총 32개 지표**를 매일 자동 수집·분석하고 Claude.ai 프로젝트에 동기화하는 시스템입니다.

---

## 아키텍처

```
[ECOS API]          [KOSIS API]
 21개 지표           11개 지표
 ecos_fetch.py       kosis_fetch.py
      │                   │
      └───────┬───────────┘
              ▼
       merge_macro.py
    data/macro_latest.csv
    (32개 통합, source 컬럼)
              │
       ┌──────┴──────┐
       ▼             ▼
 ecos_signals.py  ecos_regime.py
  10개 신호 계산    레짐 분류
       │             │
       ▼             ▼
 ecos_signals.md  ecos_regime.md
       │
       ▼
 sync_claude_project.yml
 → Claude.ai Project 자동 동기화 (md 4개 + macro_latest.csv)
```

---

## 지표 목록 (32개)

### ECOS 21개 (한국은행 원천)

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

> **KOSPI**: ECOS 802Y001 일별 수집. 레짐 성장 점수에서 제외, SIG12에서만 사용.

### KOSIS 11개 (통계청 원천)

| series_id | 지표명 | 단위 | 신호/레짐 사용 | 발표지연 |
|-----------|--------|------|-------------|---------|
| KOSIS_CPI_YOY | 소비자물가 전년동월비 | % YoY | SIG03, 레짐인플레(w=2.0) | 익월 7일 |
| KOSIS_CORE_CPI_YOY | 근원물가 전년동월비 (농산물·석유류제외) | % YoY | SIG02, SIG03, 레짐인플레(w=2.0) | 익월 7일 |
| KOSIS_UNEMP_RATE | 실업률 | % | SIG05 | 익월 15일 |
| KOSIS_EMP_RATE | 고용률(15세이상) | % | SIG05, 레짐성장(w=1.0) | 익월 15일 |
| KOSIS_LABOR_PART | 경제활동참가율 | % | **팩트 전용** | 익월 15일 |
| KOSIS_EMP_CHANGE | 취업자수 전년동기 증감 | 천명 | SIG05 | 익월 15일 |
| KOSIS_CLI_COINCIDENT | 동행지수 순환변동치 | 지수(100기준) | SIG08, 레짐성장(w=1.5) | 약 2개월 |
| KOSIS_CLI_LEADING | 선행지수 순환변동치 | 지수(100기준) | SIG08, 레짐성장(w=1.5) | 약 2개월 |
| KOSIS_INDPRO_YOY | 광공업생산지수 전년비 | % YoY | SIG09, 레짐성장(w=1.0) | 익월 말 |
| KOSIS_RETAIL_YOY | 소매판매 전년동월비 | % YoY | SIG06, 레짐성장(w=1.0) | 익월 말 |
| KOSIS_SERVICE_PROD_YOY | 서비스업생산지수 전년비 | % YoY | SIG06 | 익월 말 |

> **KOSIS_CORE_CPI_YOY**: 통계청 농산물·석유류제외 지수(DT_1J22007, C1=QB).
> **제외 지표 (v1.2)**: KOSIS 수출·수입·무역수지 — 관세청 Open API `tblId` 미확인으로 파이프라인에서 제거. SIG10(수출 모멘텀) 미구현.

---

## 신호 대시보드 (10개)

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
| SIG11 | 주택시장 | KB_HOUSE_YOY, KB_JEONSE_YOY, HOUSING_START | % / 지수 |
| SIG12 | KOSPI 레짐 | KOSPI | pt |

> **미구현**: SIG04 기대인플레 디앵커링(ECOS 미수록), SIG10 수출 모멘텀(KOSIS 관세청 API 미연동).

---

## 레짐 분류 (2×2 매트릭스)

성장 점수(5개 요소) × 인플레이션 점수(5개 요소)로 4가지 레짐 분류:

| 레짐 | 성장 | 인플레 |
|------|------|-------|
| ✨ Goldilocks | 강함(>5) | 낮음(≤5) |
| 🔥 Overheating | 강함(>5) | 높음(>5) |
| ⚠️ Stagflation | 약함(≤5) | 높음(>5) |
| ❄️ Recession Risk | 약함(≤5) | 낮음(≤5) |

**성장 6요소**: GDP_GROWTH_YOY(w=2.0), KOSIS_EMP_RATE(w=1.0), KOSIS_CLI_COINCIDENT(w=1.5), KOSIS_CLI_LEADING(w=1.5), KOSIS_INDPRO_YOY(w=1.0), KOSIS_RETAIL_YOY(w=1.0)

**인플레 4요소**: KOSIS_CPI_YOY(w=2.0), KOSIS_CORE_CPI_YOY(w=2.0), PPI_YOY(w=1.5), IMPORT_PRICE_YOY(w=1.0, ±15% winsorize)

---

## 파일 구조

```
ecos-macro-review/
├── ecos_fetch.py                  ECOS 21개 지표 수집
├── kosis_fetch.py                 KOSIS 11개 지표 수집
├── scripts/
│   ├── merge_macro.py             ECOS+KOSIS 병합 → macro_latest.csv
│   ├── ecos_signals.py            10개 신호 계산
│   └── ecos_regime.py             레짐 분류
├── data/
│   ├── ecos_latest.csv / .md      ECOS 21개 원천
│   ├── kosis_latest.csv / .md     KOSIS 11개 원천
│   ├── macro_latest.csv           통합 32개 + source 컬럼
│   ├── ecos_signals.md            신호 대시보드
│   └── ecos_regime.md             레짐 분류 보고서
├── .github/workflows/
│   ├── ecos_daily.yml             일일 데이터 수집 → 분석
│   └── sync_claude_project.yml    Claude.ai 동기화
└── claude_project_instructions.md
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

이후 `sync_claude_project.yml`이 완료 이벤트를 받아 5개 파일을 Claude.ai 프로젝트에 동기화합니다.

---

## 설정

### GitHub Secrets

| Secret | 설명 |
|--------|------|
| `ECOS_API_KEY` | 한국은행 ECOS Open API 키 |
| `KOSIS_API_KEY` | KOSIS Open API 키 (대시보드 값 **그대로**, `=` 포함, base64 디코딩 금지) |
| `CLAUDE_SESSION_KEY`, `CLAUDE_ORG_ID`, `CLAUDE_PROJECT_ID` | Claude 프로젝트 동기화 |

### KOSIS 검증

```bash
export KOSIS_API_KEY='your_key_from_kosis_dashboard'
python kosis_fetch.py --validate
```

### 로컬 실행

```bash
pip install -r requirements.txt
python ecos_fetch.py
python kosis_fetch.py
python scripts/merge_macro.py
python scripts/ecos_signals.py
python scripts/ecos_regime.py
```

---

> **면책**: 본 프로젝트는 자동 생성 정보 제공 목적이며, 투자 권고가 아닙니다.  
> 출처: 한국은행 ECOS API + 통계청 KOSIS API
