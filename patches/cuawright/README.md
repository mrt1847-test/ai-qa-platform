# CUAWright 패치

상태: **패치 없음.** 기준 원본은 `35dbcf389ce2d9a77eb22f539c79a1274ea53559`이고, 텍스트 스냅샷은 `third_party/cuawright/upstream`이다.

이 디렉터리는 아직 적용할 diff를 두지 않는다. 제품 API는 생성 Python/bash/`skill.py`를 실행하지 않는다. `inspect_cuawright_source`는 파일을 읽기만 하며, 아래 hook 이름은 W01-03 이후 계측 후보의 식별자다. 콜백을 설치하거나 upstream 함수를 호출하지 않는다.

| hook | 경계 |
|---|---|
| `hook.web.code_output.page_exec` | `local_browser._run_python_code`, `browser_session._run_step_code`의 생성 코드 실행 |
| `hook.web.code_output.shell` | `local_workspace.execute`의 `shell=True` |
| `hook.web.code_output.run_skill` | Skill Factory `run_skill` / `_replay`의 `python skill.py` |
| `hook.web.code_output.step_script` | step `.py` 기록 |
| `hook.web.code_output.script_py` | 누적 `script.py` 기록 |
| `hook.web.code_output.shell_step` | step `.sh` 기록 |
| `hook.web.code_output.shell_history` | `command_history.sh` 기록 |
| `hook.web.code_output.skill_py` | library/replay의 `skill.py` 기록 |
| `hook.web.code_output.taskspec` | `taskspec.json` 기록 |
| `hook.web.playwright.launch` | `chromium.launch` / persistent context / doctor |
| `hook.web.playwright.cdp` | `connect_over_cdp` |
| `hook.web.playwright.cdp_process` | 로컬 Chromium 프로세스 기동 |
| `hook.web.playwright.navigate` | 준비 단계 `page.goto` |
| `hook.web.playwright.screenshot` | `page.screenshot` |
| `hook.web.llm.query` | agent/model `query` |
| `hook.web.llm.usage` | OpenAI usage 정규화 |
| `hook.web.llm.image_qa` | `run_image_qa` |
| `hook.web.llm.self_reflection` | `run_self_reflection_async` |
| `hook.web.llm.skill_factory` | `llm_json`과 retrieve/decide/fill/learn |
| `hook.web.llm.recommend` | `recommend` |
| `hook.web.llm.route` | `route` |
| `hook.web.writer.*` | PNG, trajectory, debug, log, config snapshot, session JSON |
| `hook.web.action.dispatch` | `DefaultAgent.execute_actions`가 environment로 행동을 넘기는 지점 |

`base.yaml`의 shell은 `/bin/bash`다. 이 목록은 Windows native 실행 가능 판정이 아니다. 격리 VM과 typed IPC는 W01-02의 범위다.
