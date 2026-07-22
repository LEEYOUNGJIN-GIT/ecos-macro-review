# ECOS + KOSIS 한국 거시경제 자동 모니터링

한국은행 ECOS API (51개) + 통계청 KOSIS API (11개) = **최대 62개 시리즈**를 매일 자동 수집·분석하고 Claude.ai 프로젝트에 동기화하는 시스템입니다.

> **KOSIS 재배포 대체 (v3.2~v3.5, 2026-07-22)**: GitHub Actions 환경에서 KOSIS(통계청) API가
> 날짜별로 간헐 차단되는 문제가 확인되어(성공/실패가 일자별로 혼재), CPI·근원CPI·광공업생산·
> 경기동행/선행지수·서비스업생산 6종은 ECOS 쪽에도 동일 지표를 병행 수집한다(`discover_ecos_codes.py`로
> 실측 검증). `ecos_signals.py`/`ecos_regime.py`는 KOSIS 값을 우선 사용하고, 그날 KOSIS가
> 비어 있으면 자동으로 이 ECOS 값으로 대체한다 — 상세는 `data/kosis_status_log.csv`(일자별
> 성공/실패 이력)와 `data/kosis_latest.md` 상단의 최근 수집 이력 표 참고.
>
> **신규 참고지표 24종 (v3.4)**: 소비자심리(CCSI)·ESI·뉴스심리지수·BSI·기대인플레이션·
> 외환보유액·국가별 수출입·가계대출·미분양주택·아파트실거래가·연체율·대출행태서베이 —
> 전부 `discover_ecos_codes.py`로 stat_code/item_code 실측 확인 후 추가. 신호/레짐 계산에는
> 쓰이지 않는 **[참조전용]** 팩트 데이터.

---

## 아키텍처

```
[ECOS API]          [KOSIS API]
 51개 시리즈          11개 지표
 ecos_fetch.py       kosis_fetch.py
      │                   │
      └───────┬───────────┘
              ▼
       merge_macro.py
    data/macro_latest.csv
    (최대 62개 통합, source 컬럼)
              │
       ┌──────┴──────┐
       ▼             ▼
 ecos_signals.py  ecos_regime.py
  10개 신호 계산    레짐 분류
   (KOSIS 우선,      (KOSIS 우선,
    ECOS 대체)        ECOS 대체)
       │             │
       ▼             ▼
 ecos_signals.md  ecos_regime.md
       │
       ▼
 sync_claude_project.yml
 → Claude.ai Project 자동 동기화 (md 4개 + macro_latest.csv)
```

---

## 지표 목록 (최대 62개)

### ECOS 51개 (한국은행 원천)

**핵심 지표 + KOSIS 재배포 대체 (27개)**

| series_id | 지표명 | 단위 | 신호/레짐 사용 |
|-----------|--------|------|-------------|
| BOK_BASE_RATE | 한국은행 기준금리 | % | SIG01, SIG02 |
| GOV_BOND_3Y | 국고채 3년 | % | SIG07 파생 |
| GOV_BOND_10Y | 국고채 10년 | % | SIG01 |
| CD_91D | CD 91일 | % | SIG07 파생 |
| CORP_BOND_AA_MINUS | 회사채 AA- | % | 팩트 전용 |
| CORP_BOND_BBB_MINUS | 회사채 BBB- | % | SIG07 파생 |
| CPI_YOY | 소비자물가지수 전년비 (901Y009/0) | % YoY | **[재배포 대체]** KOSIS_CPI_YOY 차단 시 SIG03·레짐인플레 사용 |
| CORE_CPI_YOY | 근원물가(농산물·석유류제외) 전년비 (901Y010/QB) | % YoY | **[재배포 대체]** KOSIS_CORE_CPI_YOY 차단 시 SIG02·SIG03·레짐인플레 사용 |
| PPI_YOY | 생산자물가 전년비 | % YoY | SIG03, 레짐인플레(w=1.5) |
| IMPORT_PRICE_YOY | 수입물가 전년비 | % YoY | 레짐인플레(w=1.0) |
| GDP_GROWTH_QOQ | 실질GDP 전기비 | % | 팩트 전용 |
| GDP_GROWTH_YOY | 실질GDP 전년비 | % | 레짐성장(w=0.5, 분기 데이터라 저가중) |
| CLI_COINCIDENT | 경기동행지수순환변동 (901Y067/I16D) | 지수 | **[재배포 대체]** KOSIS_CLI_COINCIDENT 차단 시 SIG08·레짐성장 사용 |
| CLI_LEADING | 경기선행지수순환변동 (901Y067/I16E) | 지수 | **[재배포 대체]** KOSIS_CLI_LEADING 차단 시 SIG08·레짐성장 사용 |
| INDPRO_YOY | 광공업생산지수 전년비 (401Y015/*AA/C) | % YoY | **[재배포 대체]** KOSIS_INDPRO_YOY 차단 시 SIG09·레짐성장 사용 |
| SERVICE_PROD_YOY | 서비스업생산지수 전년비 (901Y038/I51A) | % YoY | **[재배포 대체]** KOSIS_SERVICE_PROD_YOY 차단 시 SIG06 사용 |
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

**신규 참고지표 24개 (v3.4, 전부 [참조전용] — 신호/레짐 미사용)**

| 카테고리 | series_id | stat_code/item_code |
|---|---|---|
| 07_경제심리 | CCSI | 511Y002/FME |
| 07_경제심리 | ESI_RAW, ESI_CYCLE | 513Y001/E1000, E2000 |
| 07_경제심리 | NEWS_SENTIMENT | 521Y001/A001 (일별) |
| 07_경제심리 | BSI_ACTUAL_ALL, BSI_ACTUAL_MFG | 512Y013/AA·99988, AA·C0000 |
| 07_경제심리 | BSI_FORECAST_ALL, BSI_FORECAST_MFG | 512Y014/BA·99988, BA·C0000 |
| 07_경제심리 | EXPECTED_INFLATION | 511Y003/FMB |
| 08_대외건전성 | FX_RESERVES | 732Y001/99 |
| 08_대외건전성 | EXPORT_CN_YOY, IMPORT_CN_YOY | 901Y121/CN·T002, CN·T004 |
| 08_대외건전성 | EXPORT_US_YOY, IMPORT_US_YOY | 901Y121/US·T002, US·T004 |
| 09_가계부채·주택리스크 | HOUSEHOLD_LOANS | 151Y002/1111000 |
| 09_가계부채·주택리스크 | UNSOLD_HOUSING | 901Y074/I410A |
| 09_가계부채·주택리스크 | APT_PRICE_NATIONAL/SEOUL/CAPITAL | 901Y089/100, 200, 300 |
| 09_가계부채·주택리스크 | DELINQUENCY_HOUSEHOLD, DELINQUENCY_BANK_ALL | 901Y054/MO3AB, AB |
| 09_가계부채·주택리스크 | LOAN_SURVEY_1/2/3 | 514Y001~003/AA, BB, CC |

> 지표별 해석 노트는 `ecos_fetch.py`의 `SERIES_NOTES`에 있음. `EXPORT/IMPORT_CN·US_YOY`의
> T002/T004 수출입 매핑, `LOAN_SURVEY_1~3`의 AA/BB/CC 항목 의미는 관행적 추정이며 ITEM_NAME
> 재확인 권장(`discover_ecos_codes.py --stat-code <code>`).

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
| SIG02 | 실질금리 갭 | BOK_BASE_RATE - KOSIS_CORE_CPI_YOY(대체: CORE_CPI_YOY) | %p |
| SIG03 | 인플레이션 레짐 | KOSIS_CPI_YOY(대체: CPI_YOY), KOSIS_CORE_CPI_YOY(대체: CORE_CPI_YOY), PPI_YOY | % 복합 |
| SIG05 | 노동시장 종합 | KOSIS_UNEMP_RATE, KOSIS_EMP_CHANGE, KOSIS_EMP_RATE | % |
| SIG06 | 내수·소비 | KOSIS_RETAIL_YOY, KOSIS_SERVICE_PROD_YOY(대체: SERVICE_PROD_YOY) | % YoY |
| SIG07 | 신용 스트레스 | CREDIT_SPREAD, CD_BOK_SPREAD | %p |
| SIG08 | 경기 사이클 | KOSIS_CLI_COINCIDENT(대체: CLI_COINCIDENT), KOSIS_CLI_LEADING(대체: CLI_LEADING) | 지수 |
| SIG09 | 산업생산 모멘텀 | KOSIS_INDPRO_YOY(대체: INDPRO_YOY) | % YoY |
| SIG11 | 주택시장 | KB_HOUSE_YOY, KB_JEONSE_YOY, HOUSING_START | % / 지수 |
| SIG12 | KOSPI 레짐 | KOSPI | pt |

> **미구현**: SIG04 기대인플레 디앵커링(원자료 `EXPECTED_INFLATION` 참조전용 수집만 됨, 신호 미계산),
> SIG10 수출 모멘텀(KOSIS 관세청 API 미연동 — `EXPORT_CN_YOY`/`EXPORT_US_YOY` 참조전용 원자료는 있음).

---

## 레짐 분류 (2×2 매트릭스)

성장 점수(5개 요소) × 인플레이션 점수(5개 요소)로 4가지 레짐 분류:

| 레짐 | 성장 | 인플레 |
|------|------|-------|
| ✨ Goldilocks | 강함(>5) | 낮음(≤5) |
| 🔥 Overheating | 강함(>5) | 높음(>5) |
| ⚠️ Stagflation | 약함(≤5) | 높음(>5) |
| ❄️ Recession Risk | 약함(≤5) | 낮음(≤5) |

**성장 6요소**: GDP_GROWTH_YOY(w=0.5, 분기 데이터라 저가중), KOSIS_EMP_RATE(w=1.0), KOSIS_CLI_COINCIDENT(w=1.5, 대체: CLI_COINCIDENT), KOSIS_CLI_LEADING(w=1.5, 대체: CLI_LEADING), KOSIS_INDPRO_YOY(w=1.0, 대체: INDPRO_YOY), KOSIS_RETAIL_YOY(w=1.0)

**인플레 4요소**: KOSIS_CPI_YOY(w=2.0, 대체: CPI_YOY), KOSIS_CORE_CPI_YOY(w=2.0, 대체: CORE_CPI_YOY), PPI_YOY(w=1.5), IMPORT_PRICE_YOY(w=1.0, 정상범위 ±10%·극단감지 ±30%)

> CLI 동행·선행은 구조적 2개월 지연이 정상이라 신선도 할인(2개월+ 지연 시 가중치 ×0.7) 예외 적용.
> 커버리지(축별 값 존재 비중)가 50% 미만이면 레짐 확정을 보류하고 "⚪ 분류 불가"로 표시.

---

## 파일 구조

```
ecos-macro-review/
├── ecos_fetch.py                  ECOS 51개 시리즈 수집 (6종은 KOSIS 재배포 대체, 24종은 참조전용 신규)
├── kosis_fetch.py                 KOSIS 11개 지표 수집 + 일자별 수집 이력 로그
├── discover_ecos_codes.py         ECOS stat_code/item_code 실측 조회 헬퍼 (신규 시리즈 추가 전 검증용)
├── scripts/
│   ├── merge_macro.py             ECOS+KOSIS 병합 → macro_latest.csv
│   ├── validate_macro.py          병합 결과 품질 검증 (CI에서 실행)
│   ├── ecos_signals.py            10개 신호 계산 (KOSIS 우선, ECOS 대체)
│   └── ecos_regime.py             레짐 분류 + 커버리지 신뢰도 표시 (KOSIS 우선, ECOS 대체)
├── data/
│   ├── ecos_latest.csv / .md      ECOS 51개 원천 (07_경제심리·08_대외건전성·09_가계부채·주택리스크 포함)
│   ├── kosis_latest.csv / .md     KOSIS 11개 원천 + 최근 수집 이력 표
│   ├── kosis_status_log.csv       KOSIS 일자별 성공/실패 이력 (최근 30건)
│   ├── macro_latest.csv           통합 최대 62개 + source 컬럼
│   ├── ecos_signals.md            신호 대시보드
│   └── ecos_regime.md             레짐 분류 보고서 (커버리지 컬럼 포함)
├── .github/workflows/
│   ├── ecos_daily.yml             일일 데이터 수집 → 분석
│   ├── discover_ecos.yml          ECOS 코드 조회 수동 실행용 (데이터 파이프라인과 무관)
│   └── sync_claude_project.yml    Claude.ai 동기화
└── claude_project_instructions.md
```

---

## 자동화 워크플로

매일 KST 06:10 실행 (`ecos_daily.yml`):

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
