#!/usr/bin/env python3
"""hermes_profile/data/schedule-presets.yaml을 읽어 `<profile> cron create`로
실제 등록한다 (tradermonty/hermes-trading-research-agent-work-package의
cron/create_cron_jobs.py 구조를 그대로 참고 — 실제 배포돼 검증된 패턴).

VPS에 아직 실제로 설치·검증해본 적은 없다(이 저장소는 Windows 개발 환경
에서 작성됨) — Hermes를 설치한 뒤 이 스크립트를 실행하면서 `<profile>
cron create` 호출이 실제로 통하는지 처음 확인하게 된다. 문제가 생기면
`hermes cron --help`로 정확한 옵션을 다시 확인할 것.

사용법:
    HERMES_PROFILE_CMD="hermes -p phase0-trader" HERMES_REPO_DIR=/opt/phase0_repo \
        python cron/create_cron_jobs.py

주의: `hermes profile install --alias`가 붙여주는 별도 실행 파일(예:
`phase0-trader` 자체를 PATH 명령으로)은 실제로는 만들어지지 않는 걸 VPS
설치 중 확인했다 — 설치 완료 메시지에 나온 `hermes -p <profile>` 형태만
확실히 동작한다. 그래서 기본값을 그 형태로 둔다. HERMES_PROFILE_CMD는
공백 포함 문자열(예: "hermes -p phase0-trader")도 그대로 받는다.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

PROFILE_DIR = Path(__file__).resolve().parents[1]
PRESETS_PATH = PROFILE_DIR / "data" / "schedule-presets.yaml"

PROFILE_CMD = os.environ.get("HERMES_PROFILE_CMD", "hermes -p phase0-trader")
DELIVER_OVERRIDE = os.environ.get("HERMES_CRON_DELIVER")
REPO_DIR = os.environ.get("HERMES_REPO_DIR", "/opt/phase0_repo")


def build_prompt(prompt_file: Path, timezone: str) -> str:
    text = prompt_file.read_text(encoding="utf-8")
    text = text.replace("{{TIMEZONE}}", timezone)
    text = text.replace("{{REPO_DIR}}", REPO_DIR)
    return text


def main() -> None:
    config = yaml.safe_load(PRESETS_PATH.read_text(encoding="utf-8"))
    timezone = config["timezone"]
    presets = config["presets"]

    print(f"프로필: {PROFILE_CMD}, 저장소: {REPO_DIR}, 타임존: {timezone}")
    print(f"{len(presets)}개 스케줄 등록 시작\n")

    for preset in presets:
        prompt_path = PROFILE_DIR / preset["prompt_file"]
        prompt_body = build_prompt(prompt_path, timezone)
        deliver = DELIVER_OVERRIDE or preset.get("deliver", "local")

        cmd = [
            *shlex.split(PROFILE_CMD), "cron", "create",
            preset["schedule"], prompt_body,
            "--name", preset["name"],
            "--deliver", deliver,
        ]
        print(f"  {preset['name']}: {preset['schedule']}")
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            print(f"실패: '{PROFILE_CMD}' 명령을 찾을 수 없습니다 — "
                  "hermes가 PATH에 있는지, 프로필 이름이 맞는지 확인하세요.")
            sys.exit(1)
        except subprocess.CalledProcessError as exc:
            print(f"  경고: {preset['name']} 등록 실패(exit {exc.returncode}) — "
                  "'hermes cron --help'로 옵션을 다시 확인하세요.")

    print(f"\n완료. `{PROFILE_CMD} cron list`로 등록 결과를 확인하세요.")


if __name__ == "__main__":
    main()
