# ECOS 수집 구조 감사 (Phase 0)

- 작성일: 2026-10-12
- 대상 커밋: `d0e0a06` (data: auto-update 2026-10-12 09:43 KST)
- 근거 자료: 저장소 코드(`ecos_fetch.py`, `discover_ecos_codes.py`, `kosis_fetch.py`, `scripts/*.py`,
  `.github/workflows/*.yml`), 커밋된 산출물(`data/*.csv`), git 이력(`git log -S`).

## 0. 실호출 여부 (먼저 밝혀 둠)

| 대상 | 결과 |
|---|---|
| `ecos.bok.or.kr` | **미실행**. 작업 환경 egress 프록시가 CONNECT 를 거부함(403). `ECOS_API_KEY` 도 없음 |
| `fred.stlouisfed.org` | **미실행**. 같은 이유(403) |
| `discover_ecos_codes.py` | **미실행**. 같은 이유 |

이 문서에서 "실측"은 **커밋된 산출물과 git 이력에서 읽은 사실**만을 뜻한다. ECOS 응답 형식이나
코드값을 기억에 기대어 적은 곳은 "(미확인)"으로 표시했다. 이번 작업에서 CONFIRMED 처리한 신규 코드는
**없다**. 후보는 전부 `UNVERIFIED` 상태로 `data/series/ecos_candidates.csv` 에 등록돼 있고,
Actions 에서 `ecos_series_collect.py --probe` 가 처음 돌 때 2절 규칙으로 판정된다.

## 1. 시리즈 정의 구조 (`ecos_fetch.SERIES`)

형식: `(series_id, stat_code, 주기, item_code, 단위, 레이블, calc_type)` 튜플 39개.
`item_code` 는 `/` 로 하위 항목을 이어 붙인 경로다(`0000001/0000100`, `*AA/C`).
StatisticSearch URL: `{BASE_URL}/{API_KEY}/json/kr/1/200/{stat}/{주기}/{start}/{end}/{item}`
— **API 키가 URL 경로 세그먼트**에 들어간다.

조회 구간(`_date_range`, 요청은 항상 1~200행 한 페이지):

| 주기 | 시작 | 종료 | 비고 |
|---|---|---|---|
| D | 오늘−280일 | 어제 | 200행 한도 때문에 280일로 제한 |
| M | 4년 전 1월 | 이번 달 | 미래 오류 시 6개월 당겨 재시도 |
| Q | 6년 전 Q1 | 올해 Q4 | |
| A | 10년 전 | 올해 | (현재 A 주기 시리즈 없음) |

### 1.1 시리즈별 주기 (39개)

"최신 기준일"은 2026-10-12 커밋된 `data/ecos_latest.csv` 의 `date` 열.

| series_id | stat_code | item_code | 주기 | 단위(코드상) | calc_type | 최신 기준일 | 이력 저장 |
|---|---|---|---|---|---|---|---|
| BOK_BASE_RATE | 722Y001 | 0101000 | **M** | % | - | 202609 | 저장 |
| GOV_BOND_3Y | 721Y001 | 5020000 | **M** | % | - | 202609 | 저장 |
| GOV_BOND_10Y | 721Y001 | 5050000 | **M** | % | - | 202609 | 저장 |
| CD_91D | 721Y001 | 2010000 | **M** | % | - | 202609 | 저장 |
| CORP_BOND_AA_MINUS | 721Y001 | 7020000 | M | % | - | 202609 | 저장 |
| CORP_BOND_BBB_MINUS | 721Y001 | 7030000 | M | % | - | 202609 | 저장 |
| CPI_YOY | 901Y009 | 0 | M | % | yoy_pct | 202609 | 저장 |
| CORE_CPI_YOY | 901Y010 | QB | M | % | yoy_pct | 202609 | 저장 |
| PPI_YOY | 404Y014 | *AA | M | % | yoy_pct | 202608 | 저장 |
| IMPORT_PRICE_YOY | 403Y005 | B | M | % | yoy_pct | 202608 | 저장 |
| CLI_COINCIDENT | 901Y067 | I16D | M | 지수 | - | 202608 | 저장 |
| CLI_LEADING | 901Y067 | I16E | M | 지수 | - | 202608 | 저장 |
| GDP_GROWTH_QOQ | 200Y104 | 1118 | Q | % | qoq_pct | 2026Q2 | 저장 |
| GDP_GROWTH_YOY | 200Y104 | 1118 | Q | % | yoy_pct | 2026Q2 | 저장 |
| INDPRO_YOY | 401Y015 | *AA/C | M | % | yoy_pct | 202608 | 저장 |
| SERVICE_PROD_YOY | 901Y038 | I51A | M | % | yoy_pct | 202608 | 저장 |
| M2_YOY | 161Y006 | BBHA00 | M | % | yoy_pct | 202607 | 저장 |
| BASE_MONEY | 102Y004 | ABA104 | M | 십억원 | - | 202607 | 저장 |
| BANK_LOANS | 104Y016 | BDCA1 | M | 십억원 | - | 202607 | 저장 |
| KB_HOUSE_YOY | 901Y062 | P63A | M | % | yoy_pct | 202609 | 저장 |
| KB_JEONSE_YOY | 901Y063 | P64A | M | % | yoy_pct | 202609 | 저장 |
| HOUSING_START | 901Y066 | I15A | M | 지수 | - | 202608 | 저장 |
| KOSPI | 802Y001 | 0001000 | **D** | pt | - | 20261008 | 저장 |
| KOSDAQ | 802Y001 | 0089000 | D | pt | - | 20261008 | 저장 |
| USD_KRW | 731Y004 | 0000001/0000100 | **M** | 원 | - | 202609 | 저장 |
| CD_BOK_SPREAD | 721Y001 | SPREAD | M | % | - | 202609 | 제외(파생) |
| CREDIT_SPREAD | 721Y001 | CSPREAD | M | % | - | 202609 | 제외(파생) |
| CCSI | 511Y002 | FME | M | 지수 | - | 202609 | 저장 |
| ESI_RAW | 513Y001 | E1000 | M | 지수 | - | 202609 | 저장 |
| ESI_CYCLE | 513Y001 | E2000 | M | 지수 | - | 202609 | 저장 |
| NEWS_SENTIMENT | 521Y001 | A001 | D | 지수 | - | **(누락)** | 저장 |
| EXPECTED_INFLATION | 511Y003 | FMB | M | % | - | 202609 | 저장 |
| FX_RESERVES | 732Y001 | 99 | M | 백만달러 | - | 202609 | 저장 |
| HOUSEHOLD_LOANS | 151Y002 | 1111000 | M | 십억원 | - | 202607 | 저장 |
| UNSOLD_HOUSING | 901Y074 | I410A | M | 호 | - | 202608 | 저장 |
| APT_PRICE_NATIONAL | 901Y089 | 100 | M | % | yoy_pct | 202607 | 저장 |
| APT_PRICE_SEOUL | 901Y089 | 200 | M | 지수 | - | 202607 | 저장 |
| APT_PRICE_CAPITAL | 901Y089 | 300 | M | 지수 | - | 202607 | 저장 |
| DELINQUENCY_HOUSEHOLD | 901Y054 | MO3AB | M | % | - | 202607 | 저장 |

### 1.2 hurdle 입력 지표의 주기 — 결론

| 지침 입력 | 현재 시리즈 | 주기 | 의미 |
|---|---|---|---|
| `--hurdle` (국고3년) | GOV_BOND_3Y (721Y001/5020000) | **월(M)** | 월 단위 값. 2026-10-12 기준 최신이 202609 |
| `--cash-hurdle` (CD91) | CD_91D (721Y001/2010000) | **월(M)** | 같음 |
| (참고) 기준금리 | BOK_BASE_RATE (722Y001/0101000) | 월(M) | |
| (참고) 국고10년 | GOV_BOND_10Y (721Y001/5050000) | 월(M) | |
| (참고) KOSPI | KOSPI (802Y001/0001000) | **일(D)** | 코드 주석: "월별(M) 요청 시 빈 결과 → 일별(D) 사용" |

- 금리 4종은 **일별이 아니라 월별**이다. 월 값이 월평균인지 월말인지는 응답의 항목명·통계표명으로
  확인해야 하는데 이번에 실호출을 못 해 **미확인**이다(ECOS 721Y001 은 "시장금리(월,분기,년)"
  계열로 알려져 있으나 이 역시 기억에 근거함).
- 자동화 입력으로 일별 값이 필요하면 별도 일별 계열이 있어야 한다. 후보를 등록해 뒀다(3절) —
  `GOV_BOND_3Y_DAILY`, `CD_91D_DAILY`, `GOV_BOND_10Y_DAILY`, `BOK_BASE_RATE_DAILY`. 전부 UNVERIFIED.
  CONFIRMED 전에는 수집하지 않는다.

### 1.3 감사 중 발견한 기존 코드의 문제 (이번 작업에서 수정하지 않음)

불변 조건(SERIES 정의 수정 금지, 기존 산출물 불변) 때문에 기록만 한다.

1. **NEWS_SENTIMENT 가 2026-08-31 이후 산출물에서 빠져 있다.** git 이력상 마지막 등장은
   `4f85bb0`(2026-08-30)이고, 그때 기준일이 `20260610`(81일 전)이었다. 2026-08-28·29 도 각각
   `20260608`·`20260609` 로 같은 81일 지연이다. 280일 구간을 1~200행 한 페이지로만 요청하므로,
   주말에도 값이 있는(7일/주) 일별 계열이면 **가장 오래된 200일만** 받게 된다. 이 계산과 맞아떨어진다.
   08-31 이후 아예 빠진 원인은 로그가 없어 미확인이다. 신규 수집기는 `list_total_count` 기준으로
   페이지를 나눠 받으므로 이 절단이 생기지 않는다.
   KOSPI·KOSDAQ 는 영업일만 있어 280일 ≈ 190영업일이라 아직 200행 안쪽이다. 여유가 거의 없다.
2. **FX_RESERVES 단위 표기가 의심된다.** 코드상 단위는 `백만달러`, 값은 `440,556,700` 이다.
   백만달러라면 440조 달러여서 말이 안 된다. `천달러`(= 약 4,406억 달러)로 읽어야 상식에 맞는다.
   신규 메타는 응답의 `UNIT_NAME` 을 그대로 보존하므로, 첫 실행 뒤 `data/series/ecos_meta.csv`
   에서 확정할 수 있다. 단위 환산은 하지 않는다.
3. **API 키 노출 경로.** `ecos_fetch.fetch_series` 는 예외를 `print(f"... {exc}")` 로 그대로
   출력한다. `requests` 의 HTTPError·ConnectionError 메시지에는 키가 들어간 URL 이 포함된다.
   GitHub Actions 는 secret 값 전체를 로그에서 가려 주므로 Actions 로그로는 새지 않는다.
   다만 로컬 실행 로그로는 샐 수 있다. `main()` 은 키 끝 4자리도 출력한다. 신규 수집기는 모든 출력과
   파일 기록을 `mask_secret()` 에 통과시키며, 테스트로 검증한다.
4. `fetch_series` 는 RESULT.CODE 를 경고로만 찍고 빈 리스트를 반환한다. 그래서 데이터 없음·인증
   오류·한도 초과를 구분할 수 없다. 신규 수집기가 이 함수를 재사용하지 않고, URL 형식만 같은
   자체 호출 함수를 쓰는 이유다.

## 2. USD_KRW 와 일별 원/달러

- `USD_KRW = ("731Y004", "M", "0000001/0000100")`: 코드 주석이 "0000001=USD, 0000100=월평균자료",
  레이블이 "원/달러 환율 월평균"이고, README 에도 "원/달러 환율 월평균"으로 명시돼 있다.
  → **월평균 계열이 맞다**(코드·문서 기준. 응답 항목명 확인은 미실행).
- 일별 매매기준율 탐색: `discover_ecos_codes.py` 는 **미실행**(네트워크 차단).
  - 후보: `731Y001` (주요국 통화의 대원화환율, 일별) / `0000001` (원/미국달러 매매기준율).
    ECOS 공개 자료에 대한 기억에 근거한 값이며 **UNVERIFIED** 다.
  - 2절 규칙에 따른 재탐색 계획(Actions `Discover ECOS Codes` 수동 실행):
    1. `--keyword 대원화환율`
    2. `--keyword 매매기준율`
    3. `--keyword 환율` (위 둘에서 못 찾았을 때)
    4. 찾은 표에 대해 `--stat-code <코드>` 로 item 확인
    5. **항목 존재 확인만으로 끝내지 않는다.** `ecos_series_collect.py --probe` 의 실조회에서
       데이터 행이 1개 이상 오고 항목명에 "미국달러"가 있어야 CONFIRMED 다.
  - 세 키워드로도 못 찾으면 "없음"으로 단정하지 않고 UNVERIFIED 로 둔다.

## 3. `ecos_latest.csv`·`macro_latest.csv` 컬럼과 갱신 방식

| 파일 | 컬럼 | 갱신 |
|---|---|---|
| `data/ecos_latest.csv` | series_id,label,value,date,unit,stat_code,period,chg_prev,chg_mid,chg_yoy,note | 매 실행 **덮어쓰기**(`to_csv`, utf-8-sig). 수집 실패 행은 `drop_failed` 로 제거된다 |
| `data/macro_latest.csv` | 위 11개 + source(`ecos`/`kosis`) | `merge_macro.py` 가 매 실행 **덮어쓰기**. 같은 series_id 면 KOSIS 를 우선하고 N/A 행은 제거한다 |
| `data/kosis_latest.csv` | ecos_latest 와 같은 11개 | 덮어쓰기. **2026-10-12 커밋본은 헤더만 있다**(그날 KOSIS 전량 실패) |
| `data/kosis_status_log.csv` | date,success,total,status | 누적(최근 30건) |

- `value` 는 calc_type 을 적용한 **변환값**이다(예: CPI_YOY = 지수의 전년비 %). `date` 는 ECOS 원본
  TIME 문자열이다(YYYYMM / YYYYMMDD / YYYYQn).
- `ecos_fetch.save_csv` 는 `data/ecos_history/ecos_{ts}.csv` 스냅샷도 쓰지만 `.gitignore` 에 있어
  커밋되지 않는다. 즉 **지금은 시계열 이력이 저장소에 남지 않는다.** 이번 작업이 이 공백을 채운다.
- 신규 이력은 calc_type 을 적용하지 **않은** ECOS 원자료(`DATA_VALUE`)다. 그래서 `CPI_YOY.csv` 에는
  지수 수준이 들어간다. 메타 `series_type=RAW;calc=yoy_pct` 로 이를 표시한다(docs/SERIES_SCHEMA.md).

## 4. 워크플로

### 4.1 `ecos_daily.yml`
- 트리거: cron `10 21 * * *`(KST 06:10) + 수동. 커밋 시각을 보면 실제 실행은 09~10시대로 밀린다.
- `concurrency: group: ${{ github.workflow }}`, `cancel-in-progress: false` → 같은 워크플로끼리는
  직렬로 돈다.
- Step 4: `git add data/` 후 변경이 없으면 커밋하지 않는다. push 가 거부되면 최대 5회
  `fetch` + `merge -X ours` 를 반복한다. 주석에 따르면 예전 rebase 방식이 Re-run 때 "자기 자신의
  결과"와 충돌해 30회 중 18회 실패했고, 그래서 merge 방식으로 바꿨다(커밋 `d19703d`).

### 4.2 충돌 가능성
- `sync_claude_project.yml`: `ECOS Daily Fetch` 완료(success) 시 실행된다. **커밋하지 않으므로
  push 충돌은 없다.** 업로드 대상은 md 3개와 macro_latest.csv 로 고정돼 있다. `data/series/` 는
  추가하지 않았다.
- `discover_ecos.yml`: 수동 전용이고 `contents: read` 라 커밋하지 않는다.
- 신규 `tests.yml`: PR 전용이고 읽기 전용이다.
- 결론: main 에 push 하는 워크플로는 `ecos_daily.yml` 하나뿐이다. 이력 수집을 **같은 job 의 Step 3b**
  로 넣으면 push 하는 주체가 늘지 않는다. 별도 워크플로로 분리하면 비슷한 시각에 main 에 push 하는
  경쟁자가 하나 더 생긴다.
- 지시서는 "pull --rebase"를 요구했지만, 이 저장소는 rebase 방식이 실패했던 이력 때문에 merge 루프로
  바꾼 상태다. 그래서 기존 루프를 그대로 공유했다. `-X ours` 의 한계도 있다. 같은 시각 두 실행이
  `_collect_log.csv`·`_revisions.csv` 의 같은 끝부분에 append 하다 충돌하면, 상대 실행의 로그 행이
  사라질 수 있다. 이력 파일 자체는 다음 실행의 재조회 구간에서 복구된다.

## 5. 증분 재조회 기간 N (개정 흡수)

| 주기 | N | 근거 |
|---|---|---|
| D | 10일 | 시장 데이터는 사후 개정이 드물다. 휴장·지연 반영분 흡수용 |
| M | 6개월 | 산업활동·통화 지표는 1~3개월 잠정치 개정이 흔하다. 여유를 둠 |
| Q | 8분기 | GDP 는 속보→잠정→연간 개편으로 과거 1~2년이 바뀐다 |
| A | 3년 | (현재 대상 없음) |

- 기준연도 개편(예: 지수 기준연도 변경)은 전 구간이 바뀌므로 N 기간 재조회로는 흡수되지 않는다.
  그래서 재조회 구간의 기존 관측 중 50% 이상(최소 3건)이 바뀌면 그 시리즈만 **전 구간을 다시
  받는다**. 바뀐 값은 모두 `_revisions.csv` 에 남는다. 수동 `--full` 도 지원한다.

## 6. 무효 코드 레지스트리 (v3.6 제거 12종)

`data/ecos_invalid_codes.csv` 에 기록했다. 근거는 커밋 `d576471`
("fix(v3.6): 실측 fetch 검증으로 확인된 무효 ECOS 코드 12종 제거", 2026-07-22)이다.
item_code 는 그 직전 정의(`fb4c1a4` 의 ecos_fetch.py)에서 복원했다.

| key | stat_code | item_code |
|---|---|---|
| BSI_ACTUAL_ALL | 512Y013 | AA/99988 |
| BSI_ACTUAL_MFG | 512Y013 | AA/C0000 |
| BSI_FORECAST_ALL | 512Y014 | BA/99988 |
| BSI_FORECAST_MFG | 512Y014 | BA/C0000 |
| EXPORT_CN_YOY | 901Y121 | CN/T002 |
| IMPORT_CN_YOY | 901Y121 | CN/T004 |
| EXPORT_US_YOY | 901Y121 | US/T002 |
| IMPORT_US_YOY | 901Y121 | US/T004 |
| DELINQUENCY_BANK_ALL | 901Y054 | AB |
| LOAN_SURVEY_1 | 514Y001 | AA |
| LOAN_SURVEY_2 | 514Y002 | BB |
| LOAN_SURVEY_3 | 514Y003 | CC |

- 전부 `error=INFO-200`, `verified_at=2026-07-22` 다. 공통 교훈은 StatisticItemList 로 항목이
  보여도 StatisticSearch 실조회는 INFO-200 일 수 있다는 것이다. 같은 표(901Y054)라도 item 마다
  유효성이 다르다(MO3AB 정상, AB 무효).
- 수집기는 `key` 또는 `(stat_code, item_code)` 가 레지스트리와 일치하는 시리즈와 후보를 수집·probe
  대상에서 제외한다(테스트로 검증).
- 레지스트리는 무효 판정된 **그 조합**만 막는다. 같은 지표(예: BSI)를 다른 올바른 코드로 다시
  찾는 것까지 막지는 않는다.

## 7. 코드 검증 규칙 (이 저장소 실측 교훈의 규칙화)

1. 후보 코드는 discover 의 "항목 존재"만으로 CONFIRMED 처리하지 않는다. `ecos_fetch` 와 같은
   StatisticSearch URL 경로로 실조회해 **데이터 행이 1개 이상** 와야 한다. 동시에 항목명이 기대
   키워드를 모두 포함해야 한다(901Y092 를 주택으로 오인했던 v2.2 사례 방지).
2. HTTP 200 이어도 본문 `RESULT.CODE` 를 해석한다. 분류는 아래와 같다. 코드표는 ECOS 개발가이드
   기준이며 기억에 근거해 적었다 — 첫 실호출 때 실제 메시지와 대조가 필요하다.
   - `INFO-200` → NO_DATA (재시도 안 함)
   - `INFO-100` → AUTH_ERROR (즉시 중단, 종료코드 2)
   - `ERROR-602` → RATE_LIMIT (지수 백오프 2·4·8초)
   - `ERROR-400/500/600/601`, HTTP 5xx·429, 네트워크 오류 → 일시 오류 (지수 백오프)
   - `ERROR-100/101/200/300/301` → REQUEST_ERROR (재시도 안 함)
3. 주기별 날짜 형식: D=YYYYMMDD, M=YYYYMM, Q=YYYYQ1~Q4, A=YYYY. 주기와 형식이 안 맞으면 오류로 처리하고
   추정하지 않는다.
4. 못 찾았을 때 "없음"으로 단정하지 않는다. 다른 키워드로 2회 더 탐색한 뒤에도 못 찾으면
   UNVERIFIED 로 둔다.
5. 한 TIME 에 서로 다른 값이 여러 개 오면(하위 item 차원이 고정되지 않음) 임의로 고르지 않고
   AMBIGUOUS_ITEM 으로 실패 처리한다.
