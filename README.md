# 📊 ECOS 한국 거시경제 자동 모니터링

> **한국은행 ECOS API → 50개 지표 수집 → 15개 파생 신호 → 2×2 레짐 분류 → claude.ai 자동 분석**

[![ECOS Daily Fetch](https://github.com/YOUR_USERNAME/ecos-macro-review/actions/workflows/ecos_daily.yml/badge.svg)](https://github.com/YOUR_USERNAME/ecos-macro-review/actions/workflows/ecos_daily.yml)

---

## 📐 아키텍처

```
┌─────────────┐   ~50회 API 호출   ┌──────────────────────┐
│  ECOS API   │ ─────────────────► │  ecos_fetch.py       │
│  (한국은행)  │                    │  50개 지표 수집       │
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
            │ 15개 파생 신호    │                   │ 성장·인플레 점수  │
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
│   ├── ecos_signals.py                 ← 15개 파생 신호 대시보드
│   └── ecos_regime.py                  ← 2×2 레짐 분류 엔진
├── data/
│   ├── .gitkeep
│   ├── ecos_latest.csv                 ← 최신 원천 데이터 (자동 생성)
│   ├── ecos_latest.md                  ← Claude용 팩트 테이블 (자동 생성)
│   ├── ecos_signals.md                 ← 15개 신호 보고서 (자동 생성)
│   ├── ecos_regime.md                  ← 레짐 분류 보고서 (자동 생성)
│   └── ecos_history/
│       └── ecos_YYYYMMDD_HHMMSS.csv    ← 일별 히스토리 (자동)
├── ecos_fetch.py                       ← ECOS API 수집 + 팩트 테이블 생성
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 📊 수집 지표 (50개, 10개 카테고리)

| # | 카테고리 | 지표 수 | 주요 지표 |
|---|---------|--------|---------|
| 01 | 금리·채권 | 6 | 기준금리, 국고채3Y/10Y, CD91일, 회사채AA-/BBB- |
| 02 | 환율 | 4 | 원/달러, 원/엔, 원/위안, 실질실효환율 |
| 03 | 물가·인플레 | 5 | CPI, 근원CPI, PPI, 기대인플레, 수입물가 |
| 04 | GDP·경기 | 5 | 실질GDP, 경기동행지수, 경기선행지수, CLI, BSI |
| 05 | 노동시장 | 5 | 실업률, 취업자수, 경제활동참가율, 고용률, 청년실업률 |
| 06 | 통화·유동성 | 5 | M2, M1, 본원통화, 가계부채, 기업대출 |
| 07 | 주택시장 | 4 | 주택매매가격지수, 전세가격지수, 아파트가격지수, 주택착공 |
| 08 | 수출입·무역 | 5 | 수출, 수입, 무역수지, 경상수지, 수출물량지수 |
| 09 | 소비·산업 | 5 | 소매판매, 광공업생산, 설비투자, 건설기성, CSI |
| 10 | 금융시장 | 6 | KOSPI, KOSDAQ, 외국인순매수, 크레딧스프레드, DSR |

---

## 📡 신호 대시보드 (15개)

`scripts/ecos_signals.py`가 생성하는 15개 파생 신호:

| # | 신호 | 주요 입력 | 임계 기준 |
|---|-----|---------|---------|
| 1 | 장단기 금리 스프레드 | 국고채10Y - 기준금리 | <0 역전 → 침체 경고 |
| 2 | 실질금리 갭 | 기준금리 - 근원CPI YoY | ≥2.0 강한 긴축 |
| 3 | 인플레이션 레짐 | CPI, 근원CPI, PPI | ≥3.5 고인플레 |
| 4 | 기대인플레 디앵커링 | 기대인플레이션 | ≥3.0 경계 |
| 5 | 환율 트렌드 | 원/달러 YoY, 실질실효환율 | YoY ≥10% 강세달러 |
| 6 | 노동시장 종합 | 실업률, 고용률, 취업자 증감 | 종합점수 0-10 |
| 7 | 소비자심리 | CSI, 소매판매 YoY | CSI <80 심각한 위축 |
| 8 | 통화·유동성 | M2 YoY, 가계부채 증감 | 종합점수 0-10 |
| 9 | 신용 스트레스 | 회사채-국채 스프레드, DSR | 스프레드 ≥2.0 경계 |
| 10 | 경기 사이클 | 동행지수, 선행지수 | 동반 하락 → 침체 경고 |
| 11 | 산업생산 모멘텀 | 광공업생산 MoM/YoY | 연속 하락 → 경기 둔화 |
| 12 | 무역·경상수지 | 무역수지, 수출 증감률 | 적자 전환 → 경보 |
| 13 | 주택시장 | 매매-전세 갭, 착공 | 종합점수 0-10 |
| 14 | KOSPI 레짐 | KOSPI YoY, 외국인 수급 | YoY <-20% 약세장 |
| 15 | 한·미 금리차 | 한국 기준금리 - 미 기준금리 | <-1.5% 역전 경보 |

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

**성장 점수** (8요소): GDP, 산업생산, 소비, 고용, 경기동행/선행지수, 소비심리, KOSPI  
**인플레 점수** (7요소): CPI, 근원CPI, PPI, 기대인플레, 수입물가, 원/달러, 임금

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
   - `ecos_latest.md` — 50개 원천 팩트 테이블
   - `ecos_signals.md` — 15개 신호 대시보드
   - `ecos_regime.md` — 레짐 분류 보고서
   - `ecos_latest.csv` — 상세 데이터 (필요 시)

### 분석 프롬프트 예시

```
@ecos-macro-review 의 data/ecos_signals.md, data/ecos_regime.md, data/ecos_latest.md 를 읽고
아래 분석을 수행해 주세요:

1. 현재 매크로 레짐과 15개 신호의 핵심 시사점 요약
2. 전주 대비 가장 큰 변화를 보인 상위 3개 지표
3. 향후 1~3개월 리스크 시나리오 (Bull / Base / Bear)
4. 한국 투자자 관점의 시사점 (원화, 금리, 주식, 부동산)
```

---

## 📅 스케줄

| 항목 | 값 |
|-----|---|
| 실행 주기 | 매일 KST 08:30 (UTC 23:30) |
| API 호출 수 | ~50회 (지표당 1회, 0.3초 간격) |
| API 한도 | 월 10,000건 (개인 무료) |
| 금일 데이터 포함 여부 | ECOS 발표 시점 의존 (D: 당일, M: 전월, Q: 전분기) |
| 히스토리 보관 | data/ecos_history/ 에 일별 CSV 자동 저장 |
| 수동 실행 | Actions → Run workflow |

---

## 🔑 License

이 프로젝트는 개인 학습·분석 목적으로 제작되었습니다.  
ECOS 데이터는 한국은행 ECOS 이용약관을 따릅니다.
