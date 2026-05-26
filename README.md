# 📊 ECOS 한국 거시경제 자동 모니터링

> **한국은행 ECOS API → 31개 지표 수집 → 10개 파생 신호 → 2×2 레짐 분류 → claude.ai 자동 분석**

[![ECOS Daily Fetch](https://github.com/LEEYOUNGJIN-GIT/ecos-macro-review/actions/workflows/ecos_daily.yml/badge.svg)](https://github.com/LEEYOUNGJIN-GIT/ecos-macro-review/actions/workflows/ecos_daily.yml)

---

## 📐 아키텍처

```
┌─────────────┐   ~32회 API 호출   ┌──────────────────────┐
│  ECOS API   │ ─────────────────► │  ecos_fetch.py       │
│  (한국은행)  │                    │  30개 지표 수집       │
└─────────────┘                    └──────┬───────────────┘
                                          │
                               ┌──────────▼──────────┐
                               │  data/               │
                               │  ├ ecos_latest.csv   │  ← 원천 데이터
                               │  └ ecos_latest.md    │  ← 팩트 테이블
                               └──────────┬───────────┘
                                          │
                      ┌───────────────────┼───────────────────┐
                      ▼                                       ▼
            ┌──────────────────┐                   ┌──────────────────┐
            │ ecos_signals.py  │                   │ ecos_regime.py   │
            │ 10개 파생 신호    │                   │ 성장·인플레 점수  │
            │ 종합 위험도       │                   │ 2×2 레짐 분류    │
            └────────┬─────────┘                   └────────┬─────────┘
                     │                                      │
                     ▼                                      ▼
            ecos_signals.md                        ecos_regime.md
                     │                                      │
                     └──────────────┬───────────────────────┘
                                    ▼
                            ┌───────────────┐
                            │  claude.ai    │
                            │  GitHub 연동   │
                            │  자동 분석     │
                            └───────────────┘
```

---

## 📁 파일 구조

```
ecos-macro-review/
├── .github/
│   └── workflows/
│       └── ecos_daily.yml              ← GitHub Actions (매일 KST 08:30)
├── scripts/
    │   ├── ecos_signals.py                 ← 10개 파생 신호 대시보드
│   └── ecos_regime.py                  ← 2×2 레짐 분류 엔진
├── data/
│   ├── .gitkeep
│   ├── ecos_latest.csv                 ← 최신 원천 데이터 (자동 생성)
│   ├── ecos_latest.md                  ← Claude용 팩트 테이블 (자동 생성)
│   ├── ecos_signals.md                 ← 9개 신호 보고서 (자동 생성)
│   ├── ecos_regime.md                  ← 레짐 분류 보고서 (자동 생성)
│   └── ecos_history/
│       └── ecos_YYYYMMDD_HHMMSS.csv    ← 일별 히스토리 (자동)
├── ecos_fetch.py                       ← ECOS API 수집 + 팩트 테이블 생성
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 📊 수집 지표 (31개, 8개 카테고리)

| # | 카테고리 | 지표 수 | 주요 지표 |
|---|---------|--------|---------|
| 01 | 금리·채권 | 6 | 기준금리, 국고채3Y/10Y, CD91일, 회사채AA-/BBB- |
| 02 | 물가·인플레 | 4 | CPI, 근원CPI, PPI, 수입물가지수(403Y005/B) |
| 03 | GDP·경기·생산 | 5 | 실질GDP(QoQ/YoY), 경기동행지수, 경기선행지수, 광공업생산 YoY |
| 04 | 노동시장 | 4 | 실업률, 취업자수증감, 경제활동참가율, 고용률 |
| 05 | 통화·유동성 | 2 | 본원통화, 기업대출 |
| 06 | 주택시장 | 4 | 주택매매거래금액, 임대거래금액, 아파트매매금액, 착공지수 |
| 07 | 수출입·무역 | 2 | 수출금액 YoY, 수입금액 YoY (금액지수, 403Y003/403Y001) |
| 08 | 금융시장 | 4 | KOSPI, KOSDAQ, CD-기준금리 스프레드, 크레딧스프레드 |

> **소거된 시리즈**: BSI_ALL(512Y014) · CSI(511Y004) · RETAIL_SALES_YOY(402Y015) — ECOS API 데이터 부재 확인  
> **수출입 시리즈 참고**: 403Y003/403Y001은 금액지수(가격×물량 복합)이며 물량지수와 다름  
> **KOSPI 데이터**: ECOS 802Y001 일별 시리즈, 구조적 특성상 약 4-5개월 지연 게재

---

## 📡 신호 대시보드 (10개)

`scripts/ecos_signals.py`가 생성하는 10개 파생 신호:

| ID | 신호 | 주요 입력 | 임계 기준 |
|----|-----|---------|---------|
| SIG01 | 장단기 금리 스프레드 | 국고채10Y - 기준금리 | <0 역전 → 침체 경고 |
| SIG02 | 실질금리 갭 | 기준금리 - 근원CPI YoY | ≥2.0 강한 긴축 |
| SIG03 | 인플레이션 레짐 | CPI, 근원CPI, PPI 복합 | ≥3.5 고인플레 / ≤1.0 디플레 |
| SIG05 | 노동시장 종합 | 실업률, 취업자증감, 고용률 | 실업률 ≥4.5 위험 |
| SIG07 | 신용 스트레스 | 회사채BBB-국채3Y, CD-기준금리 | 크레딧 스프레드 ≥2.0 경계 |
| SIG08 | 경기 사이클 | 경기동행지수, 선행지수 순환변동 | <98 경기 하강 / <96 침체 신호 |
| SIG09 | 산업생산 모멘텀 | 광공업생산지수 YoY (401Y015/원계열) | YoY <-5% 경계 / <-10% 위험 |
| SIG10 | 수출 모멘텀 | 수출금액 YoY, 수입금액 YoY | 수출 YoY <-10% 위험 |
| SIG11 | 주택시장 | 착공지수 (거래금액 참고) | 착공 <80 공급 급감 |
| SIG12 | KOSPI 레짐 | KOSPI 지수 수준 | KOSPI <4000 하락 경계 / <3000 약세장 (2026년 기준) |

> **미구현 신호**: SIG04 기대인플레 디앵커링 (ECOS 미수록, BOK 서베이 비공개)  
> **소거된 신호**: SIG06 소비자심리 — CSI·RETAIL_SALES_YOY 모두 API 데이터 부재

**종합 위험도**: 70%×평균 + 30%×최대 → 5단계 (🟢안정 → 🔴위험)

---

## 🏛️ 레짐 분류 (2×2 매트릭스)

`scripts/ecos_regime.py`가 생성하는 매크로 레짐:

```
        인플레 ↑ (>5)
             │
 ⚠️ Stagflation  │  🔥 Overheating
  (성장↓ 인플레↑) │  (성장↑ 인플레↑)
─────────────┼──────────────  성장 →
 ❄️ Recession    │  ✨ Goldilocks
  (성장↓ 인플레↓) │  (성장↑ 인플레↓)
             │
        인플레 ↓ (≤5)
```

| 레짐 | 성장 | 인플레 | 시사점 |
|-----|-----|-------|------|
| ✨ Goldilocks | >5 | ≤5 | 위험자산 우호, 안정적 정책 |
| 🔥 Overheating | >5 | >5 | 긴축 가능성, 실질금리 상승 |
| ⚠️ Stagflation | ≤5 | >5 | 정책 딜레마, 방어적 포지셔닝 |
| ❄️ Recession Risk | ≤5 | ≤5 | 부양 기대, 안전자산 선호 |

**성장 점수** (6요소): 실질GDP, 고용률, 경기동행/선행지수, KOSPI, 광공업생산 YoY  
**인플레 점수** (5요소): CPI, 근원CPI, PPI, 수입물가지수(403Y005/B), 취업자증감(임금 대용)

---

## ⚙️ 설정 방법

### 1단계: ECOS API 키 발급

[한국은행 ECOS 개발자센터](https://ecos.bok.or.kr/api/)에서 무료 발급  
(회원가입 후 1일 이내 활성화, 월 10,000건 무료)

### 2단계: GitHub Secrets 등록

`Settings → Secrets and variables → Actions → New repository secret`

| Name | Value |
|------|-------|
| `ECOS_API_KEY` | 발급받은 API 키 |

### 3단계: 로컬 실행 (선택)

```bash
# .env 파일 생성
echo "ECOS_API_KEY=your_api_key_here" > .env

pip install -r requirements.txt
python ecos_fetch.py
python scripts/ecos_signals.py
python scripts/ecos_regime.py
```

### 4단계: 워크플로우 확인

`.github/workflows/ecos_daily.yml`이 매일 **KST 08:30** (UTC 23:30)에 실행.

```
# 실행 순서
1. ecos_fetch.py          → data/ecos_latest.csv, data/ecos_latest.md
2. scripts/ecos_signals.py → data/ecos_signals.md
3. scripts/ecos_regime.py  → data/ecos_regime.md
4. git commit & push
```

`Actions` 탭 → `Run workflow`으로 수동 실행도 가능.

---

## 🤖 claude.ai 연동

### GitHub 통합

1. claude.ai → Settings → Integrations → **GitHub** 연결
2. `YOUR_USERNAME/ecos-macro-review` 레포 선택
3. 대화 시작 시 `data/` 폴더의 4개 파일 자동 참조:
   - `ecos_latest.md` — 31개 원천 팩트 테이블
   - `ecos_signals.md` — 10개 신호 대시보드 (SIG01~03·05·07~12, SIG04·06 제외)
   - `ecos_regime.md` — 레짐 분류 보고서
   - `ecos_latest.csv` — 상세 데이터 (필요 시)

### 분석 프롬프트 예시

```
@ecos-macro-review 의 data/ecos_signals.md, data/ecos_regime.md, data/ecos_latest.md 를 읽고
아래 분석을 수행해 주세요:

1. 현재 매크로 레짐과 9개 신호의 핵심 시사점 요약
2. 전주 대비 가장 큰 변화를 보인 상위 3개 지표
3. 향후 1~3개월 리스크 시나리오 (Bull / Base / Bear)
4. 한국 투자자 관점의 시사점 (원화, 금리, 주식, 부동산)
```

---

## 📅 스케줄

| 항목 | 값 |
|-----|---|
| 실행 주기 | 매일 KST 08:30 (UTC 23:30) |
| API 호출 수 | ~34회 (지표당 1회, 0.3초 간격) |
| API 한도 | 월 10,000건 (개인 무료) |
| 금일 데이터 포함 여부 | ECOS 발표 시점 의존 (D: 당일, M: 전월, Q: 전분기) |
| 히스토리 보관 | data/ecos_history/ 에 일별 CSV 자동 저장 |
| 수동 실행 | Actions → Run workflow |

---

## 🔑 License

이 프로젝트는 개인 학습·분석 목적으로 제작되었습니다.  
ECOS 데이터는 한국은행 ECOS 이용약관을 따릅니다.
