"""
scripts/fx_cross_check.py
ECOS 일별 원/달러(USD_KRW_DAILY, 매매기준율) vs FRED DEXKOUS 차이 분포 리포트.

리포트 전용 — 어떤 이력 파일도 수정하지 않고, 두 계열을 병합·보정하지 않는다.
두 계열은 정의가 다르다:
  - ECOS USD_KRW_DAILY: 서울외국환중개 매매기준율 (KST 기준 일자)
  - FRED DEXKOUS: Fed H.10, 뉴욕 정오 매입환율 (미국 영업일 기준)
따라서 차이는 "오차"가 아니라 시점·정의 차이를 포함한다. 보고 항목은
겹치는 일자의 평균 차이·평균 절대차·최대 절대차와 양측 결측일 수로 한정한다.

--usdkrw 의 정본은 사용자 잔고의 외화예수금 산출값이며 ECOS 환율은 보조·검증용이다
(docs/SERIES_SCHEMA.md).

사용법:
  python scripts/fx_cross_check.py --fred-csv path/to/DEXKOUS.csv
  python scripts/fx_cross_check.py                # fredgraph.csv 공개 엔드포인트에서 받음
  python scripts/fx_cross_check.py --since 2025-01-01 --out report.md

종료코드: 0=리포트 생성, 3=입력 계열 없음(USD_KRW_DAILY 미확보 등), 4=FRED 로드 실패.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ECOS_CSV = ROOT / "data" / "series" / "ecos" / "USD_KRW_DAILY.csv"
FREDGRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS"


def _parse_float(v: str) -> float | None:
    v = (v or "").strip()
    if v in ("", ".", "-", "NaN", "nan"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_series_csv(text: str) -> dict[str, float | None]:
    """date,value 또는 FRED 형식(DATE|observation_date, DEXKOUS) CSV -> {date: value|None}."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header or len(header) < 2:
        return {}
    out: dict[str, float | None] = {}
    for row in reader:
        if len(row) < 2 or not row[0].strip():
            continue
        out[row[0].strip()] = _parse_float(row[1])
    return out


def compare(ecos: dict[str, float | None], fred: dict[str, float | None],
            since: str | None = None) -> dict:
    if since:
        ecos = {d: v for d, v in ecos.items() if d >= since}
        fred = {d: v for d, v in fred.items() if d >= since}
    # 비교 구간은 양측 관측이 모두 존재하는 기간으로 제한
    e_obs = {d for d, v in ecos.items() if v is not None}
    f_obs = {d for d, v in fred.items() if v is not None}
    if not e_obs or not f_obs:
        return {"overlap_days": 0, "ecos_obs": len(e_obs), "fred_obs": len(f_obs)}
    lo = max(min(e_obs), min(f_obs))
    hi = min(max(e_obs), max(f_obs))
    e_in = {d for d in e_obs if lo <= d <= hi}
    f_in = {d for d in f_obs if lo <= d <= hi}
    both = sorted(e_in & f_in)
    diffs = [(d, ecos[d] - fred[d]) for d in both]
    res = {
        "window_start": lo,
        "window_end": hi,
        "ecos_obs": len(e_in),
        "fred_obs": len(f_in),
        "overlap_days": len(both),
        "missing_in_ecos": len(f_in - e_in),   # FRED 관측은 있으나 ECOS 결측
        "missing_in_fred": len(e_in - f_in),   # ECOS 관측은 있으나 FRED 결측
    }
    if diffs:
        vals = [x for _, x in diffs]
        max_d, max_v = max(diffs, key=lambda t: abs(t[1]))
        res.update(
            mean_diff=round(sum(vals) / len(vals), 4),
            mean_abs_diff=round(sum(abs(x) for x in vals) / len(vals), 4),
            max_abs_diff=round(abs(max_v), 4),
            max_abs_diff_date=max_d,
        )
    return res


def render(res: dict) -> str:
    lines = [
        "# USD/KRW 일별 교차검증 (ECOS 매매기준율 vs FRED DEXKOUS)",
        "",
        "> 정의가 다른 두 계열(서울 매매기준율 vs 뉴욕 정오 매입환율)의 차이 분포 — 보정·병합 없음.",
        "> --usdkrw 정본은 외화예수금 산출값이며 이 리포트는 보조 검증용.",
        "",
        "| 항목 | 값 |",
        "|---|---|",
    ]
    labels = [
        ("window_start", "비교 구간 시작"), ("window_end", "비교 구간 끝"),
        ("ecos_obs", "ECOS 관측일 수"), ("fred_obs", "FRED 관측일 수"),
        ("overlap_days", "겹치는 일수"), ("missing_in_ecos", "ECOS 결측일 수(FRED만 존재)"),
        ("missing_in_fred", "FRED 결측일 수(ECOS만 존재)"),
        ("mean_diff", "평균 차이 (ECOS−FRED, 원)"), ("mean_abs_diff", "평균 절대차 (원)"),
        ("max_abs_diff", "최대 절대차 (원)"), ("max_abs_diff_date", "최대 절대차 일자"),
    ]
    for k, label in labels:
        if k in res:
            lines.append(f"| {label} | {res[k]} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--ecos-csv", type=Path, default=ECOS_CSV)
    ap.add_argument("--fred-csv", type=Path, help="DEXKOUS CSV 경로 (없으면 fredgraph 다운로드)")
    ap.add_argument("--since", help="YYYY-MM-DD 이후만 비교")
    ap.add_argument("--out", type=Path, help="마크다운 리포트 저장 경로 (선택)")
    args = ap.parse_args(argv)

    if not args.ecos_csv.exists():
        print(f"[SKIP] {args.ecos_csv} 없음 — USD_KRW_DAILY 가 아직 CONFIRMED 되지 않았음 "
              "(data/series/ecos_candidates.csv 확인)")
        return 3
    ecos = load_series_csv(args.ecos_csv.read_text(encoding="utf-8"))

    try:
        if args.fred_csv:
            fred_text = args.fred_csv.read_text(encoding="utf-8")
        else:
            r = requests.get(FREDGRAPH_URL, timeout=30)
            r.raise_for_status()
            fred_text = r.text
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] FRED DEXKOUS 로드 실패: {exc}")
        return 4
    fred = load_series_csv(fred_text)
    if not fred:
        print("[ERROR] FRED DEXKOUS 파싱 결과가 비어 있음")
        return 4

    report = render(compare(ecos, fred, args.since))
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
