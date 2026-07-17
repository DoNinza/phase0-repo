#!/usr/bin/env python3
"""GPT-5.6 Sol 독립 코드 리뷰 하네스.

Claude Code의 Agent/서브에이전트는 Claude 계열 모델만 실행 가능해서
(공식 확인, 2026-07-17) OpenAI 모델을 "서브에이전트"로 못 데려온다 —
대신 이 스크립트가 그 역할을 한다: 지금 저장소의 diff를 OpenAI
Responses API(model="gpt-5.6-sol")로 보내 독립적인 2차 리뷰를 받는다.
Fable(전략 기획)과는 역할이 다르다 — 이건 순수 코드 리뷰 전용, 다른
벤더 모델로 상관된 맹점을 줄이는 게 목적이다.

사용법:
    python scripts/gpt_review.py                  # 커밋 안 된 변경사항 리뷰
    python scripts/gpt_review.py --range HEAD~3    # 최근 3커밋 리뷰
    python scripts/gpt_review.py --staged          # staged 변경사항만
"""

from __future__ import annotations

import subprocess
import sys
from typing import Callable

import requests

from phase0.config.openai_credentials import CredentialsMissingError, load_credentials

RESPONSES_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-5.6-sol"

REVIEW_INSTRUCTIONS = """\
너는 독립적인 2차 코드 리뷰어다. 이 저장소는 한국 KOSPI 주식 자동매매
"리서치" 시스템이다(Phase 0 방법론): 사전등록된 파라미터, 정직한 부정적
결과 보고, 절대 실거래 없음(페이퍼 트레이딩 전용)이 핵심 원칙이다.

diff를 검토해서 다음만 지적해라:
1. 정합성 버그 — 실제로 틀린 로직, 잘못된 계산, 경계값 오류, 예외 케이스
   누락. 구체적인 입력값과 그로 인한 잘못된 출력/동작을 명시할 것.
2. look-ahead bias/데이터 스누핑 위험 — 미래 정보를 쓰는 것처럼 보이는
   코드, 사전등록 원칙 위반 소지.
3. 재사용/단순화 기회 — 단, 확신이 높을 때만.

스타일 지적, 주석 부족, 사소한 네이밍은 무시해라. 문제가 없으면
"발견된 문제 없음"이라고만 답해라. 근거 없이 문제를 만들어내지 마라 —
불확실하면 불확실하다고 명시해라. 한국어로 답해라.
"""

Fetcher = Callable[[str, dict, dict], "requests.Response"]


def _default_fetcher(url: str, headers: dict, body: dict) -> requests.Response:
    resp = requests.post(url, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    return resp


def get_diff(range_arg: str | None = None, staged: bool = False) -> str:
    if range_arg:
        cmd = ["git", "diff", range_arg]
    elif staged:
        cmd = ["git", "diff", "--staged"]
    else:
        cmd = ["git", "diff"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
    return result.stdout


def call_gpt_review(api_key: str, diff_text: str, fetcher: Fetcher = _default_fetcher) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": MODEL,
        "instructions": REVIEW_INSTRUCTIONS,
        "input": f"다음 git diff를 리뷰해라:\n\n```diff\n{diff_text}\n```",
    }
    resp = fetcher(RESPONSES_URL, headers, body)
    payload = resp.json()
    for item in payload.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return content["text"]
    raise RuntimeError(f"GPT 응답에서 텍스트를 찾을 수 없음: {payload}")


def main() -> None:
    args = sys.argv[1:]
    range_arg = None
    staged = False
    for i, a in enumerate(args):
        if a == "--range":
            range_arg = args[i + 1]
        if a == "--staged":
            staged = True

    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"오류: {exc}")
        sys.exit(1)

    diff_text = get_diff(range_arg, staged)
    if not diff_text.strip():
        print("리뷰할 diff가 없습니다(변경사항 없음).")
        return

    print(f"GPT-5.6 Sol에 리뷰 요청 중... (diff {len(diff_text)}자)\n")
    review = call_gpt_review(creds.api_key, diff_text)
    print("=" * 60)
    print("GPT-5.6 Sol 리뷰")
    print("=" * 60)
    print(review)


if __name__ == "__main__":
    main()
