#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_series_codes.py — ECOS 통계코드/항목코드가 시리즈 이름이 말하는 지표를 실제로 가리키는지 대조

배경: 2026-10-20 감사에서 아래가 코드와 이름이 달랐다(ECOS 응답의 STAT_NAME/ITEM_NAME 기준).
  GDP_GROWTH_*  200Y104/1118 = 광공업 부가가치 (GDP는 1400)
  INDPRO_YOY    401Y015/*AA/C = 수입물가지수 (광공업생산은 901Y033/AB00/1)
  IMPORT_PRICE_YOY 403Y005/B = 소득교역조건지수 (수입물가는 401Y015/*AA/W)
  BASE_MONEY    102Y004/ABA104 = 현금통화 (본원통화는 ABA1)
  HOUSING_START 901Y066/I15A = 설비투자지수 (미해결)
fetch가 성공해도 값이 다른 지표일 수 있어 성공률 검사로는 잡히지 않는다.

사용: python scripts/verify_series_codes.py   (ECOS_API_KEY 없으면 sample 키로 1건씩 조회)
종료코드: 불일치 있으면 1
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.environ.get("ECOS_API_KEY") or "sample"

# 시리즈 ID -> ECOS 응답(STAT_NAME + ITEM_NAME들)에 반드시 들어 있어야 하는 문자열
EXPECT = {
    "GDP_GROWTH_QOQ": "국내총생산",
    "GDP_GROWTH_YOY": "국내총생산",
    "INDPRO_YOY": "광공업",
    "SERVICE_PROD_YOY": "서비스업생산지수",
    "IMPORT_PRICE_YOY": "수입물가지수",
    "PPI_YOY": "생산자물가지수",
    "CPI_YOY": "소비자물가지수",
    "BASE_MONEY": "본원통화",
    "M2_YOY": "M2",
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
    "CLI_COINCIDENT": "동행",
    "CLI_LEADING": "선행",
    "FX_RESERVES": "외환보유액",
    "HOUSEHOLD_LOANS": "가계대출",
    "UNSOLD_HOUSING": "미분양",
    "HOUSING_START": "착공",          # 현재 901Y066 = 설비투자지수라 실패한다(미해결 항목)
    "DELINQUENCY_HOUSEHOLD": "가계대출",
}
PERIOD = {"M": ("202606", "202608"), "Q": ("2026Q1", "2026Q2"), "D": ("20261001", "20261015"), "A": ("2023", "2025")}


def defs():
    src = open(os.path.join(ROOT, "ecos_fetch.py"), encoding="utf-8").read()
    pat = r'\(\s*"([A-Z0-9_]+)",\s*"([0-9A-Z]+Y[0-9]+)",\s*"([DMQA])",\s*"([^"]*)"'
    return {sid: (stat, cyc, item) for sid, stat, cyc, item in re.findall(pat, src)}


def main():
    bad = 0
    d = defs()
    for sid, need in EXPECT.items():
        if sid not in d:
            print(f"[SKIP] {sid}: ecos_fetch.py에서 정의를 찾지 못함")
            continue
        stat, cyc, item = d[sid]
        a, b = PERIOD[cyc]
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/10/{stat}/{cyc}/{a}/{b}/{item}"
        try:
            body = json.load(urllib.request.urlopen(url, timeout=25))
        except Exception as e:
            print(f"[SKIP] {sid}: 조회 실패 {str(e)[:60]}")
            continue
        rows = (body.get("StatisticSearch") or {}).get("row") or []
        if not rows:
            print(f"[SKIP] {sid}: 응답 행 없음(기간·발표 지연일 수 있음)")
            continue
        text = " ".join(str(rows[0].get(k) or "") for k in
                        ("STAT_NAME", "ITEM_NAME1", "ITEM_NAME2", "ITEM_NAME3", "ITEM_NAME4"))
        times = {}
        for r in rows:
            times[r["TIME"]] = times.get(r["TIME"], 0) + 1
        dup = [t for t, n in times.items() if n > 1]
        ok = need in text and not dup
        bad += 0 if ok else 1
        why = "" if ok else (f"  기대 '{need}' 없음" if need not in text else f"  같은 TIME 중복 행 {dup[:2]}")
        print(f"[{'OK' if ok else 'FAIL'}] {sid:<24}{stat}/{item:<10} -> {text.strip()[:60]}{why}")
    print(f"\n불일치 {bad}건")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
