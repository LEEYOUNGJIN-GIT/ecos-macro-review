"""
discover_ecos_codes.py
ECOS 통계표/항목 코드를 실측 조회하는 헬퍼. 새 시리즈를 SERIES 레지스트리에
추가하기 전, stat_code/item_code를 추측이 아니라 이 스크립트의 실제 API
응답으로 확인하기 위해 사용한다.

⚠ 이 스크립트의 출력을 직접 확인하지 않고 stat_code/item_code를
  ecos_fetch.py 에 하드코딩하지 말 것 (커뮤니티에 흔히 도는 값도 기준연도
  개편 등으로 틀릴 수 있음).

사용법:
  python discover_ecos_codes.py --keyword 소비자동향조사   # 통계표명에 검색어가 포함된 표 목록
  python discover_ecos_codes.py --stat-code 511Y002        # 해당 표의 세부 항목(item) 목록
  python discover_ecos_codes.py --keyword X --stat-code Y  # 둘 다 실행

동작:
  --keyword: StatisticTableList 전체 조회 후, 각 행을 JSON으로 펼쳐 검색어가
             포함된 행만 출력한다 (필드명이 정확히 무엇이든 걸리도록 raw
             JSON 문자열 매칭 사용 — API 응답 스키마를 백 퍼센트 확신할 수
             없어 필드명을 미리 고정하지 않았다).
  --stat-code: StatisticItemList 조회 후 모든 행을 JSON으로 그대로 출력한다.
             item_code·주기·데이터 시작/종료 시점을 눈으로 확인하고 고른다.

ECOS API 문서: https://ecos.bok.or.kr/api/#/DevGuide/StatisticsSearch
"""

import argparse
import json
import os
import sys

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY = os.environ.get("ECOS_API_KEY", "sample")
BASE_URL = "https://ecos.bok.or.kr/api"


def _get_rows(url: str) -> list[dict]:
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        print(f"[ERROR] 요청 실패: {exc}")
        return []

    if "RESULT" in body:
        code = body["RESULT"].get("CODE", "")
        msg = body["RESULT"].get("MESSAGE", "")
        print(f"[ERROR] ECOS 응답 오류 [{code}] {msg}")
        return []

    for val in body.values():
        if isinstance(val, dict) and "row" in val:
            return val["row"]

    print("[WARN] 예상한 응답 구조가 아님 — raw body 출력")
    print(json.dumps(body, ensure_ascii=False)[:2000])
    return []


def search_tables(keyword: str, limit: int) -> list[dict]:
    """전체 통계표 목록(StatisticTableList)에서 keyword가 포함된 행을 찾는다."""
    url = f"{BASE_URL}/StatisticTableList/{API_KEY}/json/kr/1/{limit}"
    rows = _get_rows(url)
    matches = [r for r in rows if keyword in json.dumps(r, ensure_ascii=False)]
    print(f"\n=== '{keyword}' 포함 통계표: {len(matches)}건 (전체 조회 {len(rows)}건) ===")
    for r in matches:
        print(" ", json.dumps(r, ensure_ascii=False))
    if not matches and rows:
        print("  (매칭 없음 — 전체 목록은 조회됐으니 keyword 철자/띄어쓰기를 바꿔 재시도)")
    return matches


def list_items(stat_code: str, limit: int) -> list[dict]:
    """지정 통계표코드(StatisticItemList)의 세부 항목(item) 전부를 출력한다."""
    url = f"{BASE_URL}/StatisticItemList/{API_KEY}/json/kr/1/{limit}/{stat_code}"
    rows = _get_rows(url)
    print(f"\n=== {stat_code} 세부 항목: {len(rows)}건 ===")
    for r in rows:
        print(" ", json.dumps(r, ensure_ascii=False))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="ECOS 통계표/항목 코드 조회 헬퍼")
    parser.add_argument("--keyword", help="통계표명 검색어 (예: 소비자동향조사)")
    parser.add_argument("--stat-code", help="세부 항목을 조회할 통계표코드 (예: 511Y002)")
    parser.add_argument("--limit", type=int, default=3000, help="최대 조회 건수 (기본 3000)")
    args = parser.parse_args()

    if not args.keyword and not args.stat_code:
        parser.error("--keyword 또는 --stat-code 중 하나는 필요합니다")

    if not API_KEY or API_KEY == "sample":
        print("[WARN] ECOS_API_KEY 미설정 — sample 키는 결과가 제한적일 수 있습니다.")

    if args.keyword:
        search_tables(args.keyword, args.limit)
    if args.stat_code:
        list_items(args.stat_code, args.limit)


if __name__ == "__main__":
    main()
