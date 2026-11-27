# data/series/ 스키마

시리즈별 전체 이력 저장소. FRED 저장소와 같은 `date,value` 규약을 쓴다.
기존 산출물(`data/*_latest.*`, `ecos_signals.md`, `ecos_regime.md`, `kosis_status_log.csv`)과는
별개의 **추가** 산출물이며, 수집기는 기존 산출물을 쓰지 않는다(`kosis_latest.csv` 는 읽기만 함).

```
data/series/
├── ecos/{series_id}.csv     ECOS 원자료 이력 (source_kind=ECOS)
├── kosis/{series_id}.csv    kosis_latest.csv 복사 이력 (source_kind=KOSIS_COPY)
├── ecos_meta.csv            시리즈별 실측 메타 (ECOS + KOSIS_COPY 공용)
├── ecos_candidates.csv      신규 후보 코드의 검증 상태
├── _revisions.csv           개정 감지 이력 (append)
└── _collect_log.csv         실행 로그 (append)
data/ecos_invalid_codes.csv  무효 코드 레지스트리 (수집·probe 제외 목록)
```

인코딩은 UTF-8(BOM 없음), 줄바꿈 `\n` 이다.

## 1. 이력 파일 `{series_id}.csv`

```
date,value
2026-07-01,118.42
2026-08-01,118.97
```

| 열 | 규약 |
|---|---|
| date | ISO `YYYY-MM-DD`. 일=그날, **월=1일, 분기=분기 첫날(1/4/7/10월 1일), 연=1월 1일**. 오름차순, 중복 없음 |
| value | 원자료 문자열 그대로(소수 자릿수 보존). 결측은 **빈 값** |

- ECOS 원본 TIME ↔ ISO 변환은 손실 없이 왕복된다(`2026Q3` ↔ `2026-07-01`). 그래서 `time_raw` 열은
  두지 않는다.
- **단위 환산을 하지 않는다.** `ecos_fetch` 의 calc_type(yoy_pct 등)도 적용하지 않는다.
  예: `ecos/CPI_YOY.csv` 에는 전년비가 아니라 소비자물가지수 **수준**이 들어 있다.
  series_id 는 `ecos_fetch.SERIES` 와 1:1 대응을 유지하려고 그대로 쓴다.
  `GDP_GROWTH_QOQ`·`GDP_GROWTH_YOY` 는 같은 원자료(200Y104/1118)라 두 파일의 내용이 같다.
- 파생 스프레드(`CD_BOK_SPREAD`, `CREDIT_SPREAD`)는 ECOS 원자료가 아니어서 저장하지 않는다.
  구성 시리즈 이력으로 다시 계산할 수 있다.
- 결측 보존:
  - 응답 값이 `-`·공백이면 빈 값으로 저장한다. 다른 값으로 메우지 않는다.
  - 이미 저장된 관측이 응답에서 빠지거나 빈 값으로 오면 **기존 값을 유지**한다(삭제하지 않음).
  - 숫자 값이 바뀐 경우만 개정으로 취급한다(`3.5` 와 `3.50` 은 같은 값).

## 2. 메타 `ecos_meta.csv`

```
series_id,stat_code,item_code1,cycle,unit,series_type,seasonal_adj,observation_start,
observation_end,publication_lag_days,source_kind,probed_at
```

| 열 | 내용 |
|---|---|
| series_id | 이력 파일명과 같음 |
| stat_code | ECOS 통계표 코드. KOSIS_COPY 는 kosis_latest.csv 의 stat_code |
| item_code1 | 요청에 쓴 ECOS item 경로 **전체**(`0000001/0000100` 처럼 `/` 로 하위 항목 포함). KOSIS_COPY 는 빈 값 |
| cycle | D / M / Q / A |
| unit | ECOS 응답 `UNIT_NAME` **그대로**(환산·정규화 금지). 응답에 없으면 직전 메타 값을 유지하고 경고. KOSIS_COPY 는 kosis_latest.csv 의 unit |
| series_type | `RAW`(원자료) 또는 `RAW;calc=<calc_type>`(ecos_fetch 가 산출물에서 이 변환을 적용함을 표시) / `KOSIS_LATEST_AS_IS`(kosis_latest 의 값 = 이미 변환된 값) |
| seasonal_adj | 응답 STAT_NAME·ITEM_NAME 에 `계절조정` → SA, `원계열`·`원지수` → NSA, 그 외 **UNKNOWN**(수집 로그에 경고) |
| observation_start / observation_end | 이력에서 값이 있는 첫·마지막 date |
| publication_lag_days | 수집일(KST) − observation_end (일). 월·분기는 기간 첫날 기준이라 기간 길이가 포함된다 |
| source_kind | `ECOS` / `KOSIS_COPY` |
| probed_at | 이 메타를 마지막으로 갱신한 실행 시각 (ISO, +0900) |

이번 실행에서 실패한 시리즈는 직전 메타 행을 그대로 유지한다.

## 3. KOSIS_COPY 규약

- 원천은 그날의 `data/kosis_latest.csv` 다. 값이 있는 행만 `kosis/{series_id}.csv` 에 (date, value)로
  반영한다. date 는 kosis_latest 의 `date`(YYYYMM)를 ISO 로 바꾼 값이다.
- KOSIS 수집이 실패한 날(헤더만 있거나 value 가 빈 행)은 **아무것도 쓰지 않는다.** ECOS 재배포
  값(CPI_YOY 등)이나 직전 값으로 메우지 않는다. KOSIS→ECOS 대체(`g_fallback`)는 신호 계산 단계
  (`ecos_signals.py`·`ecos_regime.py`)의 책임이며, 이력 저장 단계에서는 하지 않는다.
  값이 빈 행은 `_collect_log.csv` 에 `KOSIS_MISSING` 으로 남긴다.
- KOSIS 수집 자체는 이번 작업에서 확장하지 않았다(kosis_fetch.py 무수정). 그래서 KOSIS 이력은
  "KOSIS 가 성공한 날의 최신 1개 관측"만 쌓인다.

## 4. 후보 `ecos_candidates.csv`

```
series_id,stat_code,item_code1,cycle,expect_name,status,result_code,rows_returned,item_name,probed_at,note
```

| status | 의미 | 자동 재조회(--probe) |
|---|---|---|
| UNVERIFIED | 아직 실조회 안 함 | O |
| CONFIRMED | 실조회 데이터 행 ≥ 1 **그리고** 항목명이 `expect_name` 키워드(파이프 기호로 구분)를 모두 포함 → 이 상태만 수집 | - |
| NO_DATA | INFO-200 또는 빈 행 | X (사람이 코드 재탐색) |
| NAME_MISMATCH | 데이터는 있으나 항목명이 기대와 다름 | X |
| AUTH_ERROR / RATE_LIMIT / ERROR | 인증 오류 / 한도 초과 / 그 외 오류 | O |

CONFIRMED 후보는 **새 series_id 로 별도 저장**한다. 기존 시리즈와 병합하거나 대체하지 않는다.

## 5. 로그

- `_collect_log.csv`: `run_at,series_id,rows_added,rows_revised,status,error`
  - status: `OK`, `NO_DATA`, `AUTH_ERROR`, `RATE_LIMIT`, `TRANSIENT`, `NETWORK`, `REQUEST_ERROR`,
    `HTTP_ERROR`, `AMBIGUOUS_ITEM`, `PARSE_ERROR`, `UNKNOWN_ERROR`, `KOSIS_MISSING`
  - error 는 API 키를 마스킹한 뒤 기록한다(`StatisticSearch/***/...`).
- `_revisions.csv`: `series_id,date,old_value,new_value,detected_at`

수집기 종료코드: 0=전부 성공, 1=일부 실패(나머지는 저장됨), 2=인증 오류·키 없음으로 중단.

## 6. 원/달러 환율 사용 원칙

- `USD_KRW`(731Y004, **월평균**)는 기존대로 유지한다.
- 일별 매매기준율은 CONFIRMED 될 때만 `USD_KRW_DAILY` 라는 **별도 series_id** 로 저장한다.
  두 계열을 병합·대체하지 않는다.
- **`--usdkrw` 의 정본은 사용자 잔고의 외화예수금 산출값이다.** ECOS 환율(USD_KRW, USD_KRW_DAILY)은
  보조·검증용이다.
- `scripts/fx_cross_check.py` 는 ECOS 매매기준율과 FRED `DEXKOUS`(Fed H.10, 뉴욕 정오 매입환율)의
  일별 차이를 보고한다. 보고 항목은 평균 차이, 평균·최대 절대차, 양측 결측일 수다. 두 계열은 정의와
  기준 시각이 달라 차이가 0 이 아닌 것이 정상이다. 리포트만 만들고 어느 계열도 보정하지 않는다.

## 7. 검증

- `python scripts/validate_series.py` — 위 스키마 계약을 검사한다(헤더, ISO·주기 규약, 정렬,
  숫자, 메타 1:1, source_kind, 무효 코드 부재, 키 노출).
- `python -m unittest discover -s tests -t .` — fixture 테스트와 기존 산출물 골든 회귀.
