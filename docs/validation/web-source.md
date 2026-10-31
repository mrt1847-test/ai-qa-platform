# CUAWright 공개 원본의 출력·쓰기 경계

기준 SHA: `35dbcf389ce2d9a77eb22f539c79a1274ea53559`  
커밋 시각: 2026-10-26 20:02:22 -0700 (`Merge pull request #68 from danfiedler-msft/danfiedler/pin-actions`)  
git tree: `07891da0da10c1ef9782aa7352f39ea30bc3300d`  
패키지: `cuawright` 0.2.0, Python ≥3.10  
라이선스: `MIT AND Apache-2.0` (`pyproject.toml` 10행). `LICENSE`는 MIT, `NOTICE`는 브라우저 runtime MIT와 imported desktop runtime Apache-2.0을 구분한다. desktop 라이선스 원문은 `licenses/OSWorld-runtime-APACHE-2.0.txt`다.

기계가 읽는 목록은 [SOURCE.json](../../third_party/cuawright/SOURCE.json)이다. 위치는 `third_party/cuawright/upstream`의 해당 파일·행과 대조했다. 제품 함수 `inspect_cuawright_source`는 이 트리를 읽기만 하고 생성 코드를 실행하지 않는다.

## 스냅샷에서 뺀 것

전체 clone에서 SHA를 확인한 뒤, 실행 경계가 아닌 매체 9개(`assets/*.mp4`, `assets/*.png`)와 `.git`은 텍스트 스냅샷에 넣지 않았다. `TREE_MANIFEST.sha256`는 포함한 190개 파일의 sha256이다. `release/`의 desktop OSWorld runtime과 Skill Factory `examples/`의 샘플 `final_script.py`/`skill.py`는 트리에는 있으나 이번 Web authoring 경계의 writer로 세지 않는다.

## 네 가지 경계

- **code 생성·실행:** live browser는 모델 `python_code`를 step 파일과 `script.py`에 쓰고 `_run_python_code`에서 page/context/browser를 넘긴 채 실행한다. workspace 경로는 bash 명령을 step `.sh`와 `command_history.sh`에 쓰고 `shell=True`, `executable=/bin/bash`로 실행한다. `FINAL_SCRIPT_PATH`는 `final_script.py`를 가리키지만, 그 파일 자체는 모델이 shell로 쓴다. Skill Factory는 `skill.py`를 저장하고 `python skill.py taskspec.json`을 subprocess로 실행한다.
- **직접 Playwright:** `LocalBrowserEnvironment._prepare_async`가 `local_cdp`면 기존 CDP에 접속하고, `local_persistent`면 persistent context를, 그 외에는 `chromium.launch` 후 새 context/page를 만든다. `browser_session.open_browser_session`과 `persistent_local_browser._cmd_create`도 CDP/Chromium 프로세스를 연다. `doctor.check_screenshot`은 진단용 launch다.
- **LLM helper:** `DefaultAgent.query` → `Model.query`. 이미지 판정은 `run_image_qa`, 사후 판정은 `run_self_reflection_async`. Skill Factory의 retrieve/decide/fill/learn은 `llm_json`을 호출하고, `recommend` → `route`는 실패 또는 adapt/skip에서 agent로 넘어갈 수 있다. OpenAI `_usage_metrics_from_response_payload`는 빠진 usage를 정수로 정규화한다.
- **PNG/debug writer:** live 관찰은 `page.screenshot`으로 `step_NNNN.png` 또는 `browser_step_NNNN.png`를 쓴다. `DefaultAgent.save`가 `trajectory.json`을, `_write_debug_step_artifact`가 debug step JSON과 `steps.md`를 쓴다. config snapshot, runtime log, task metadata, session JSON, self-reflection 결과 JSON도 writer다. `task_screenshot_paths`는 스크린샷 디렉터리를 읽는 쪽이다.

`local_cdp`는 기존 브라우저에 붙을 수 있다. 같은 PC 격리와 driver 전용 handle은 이 목록의 범위 밖이다.

## 파일

| 종류 | 위치 | 심볼 | hook |
|---|---|---|---|
| source_file | `LICENSE:1` | `LICENSE` | `hook.web.source.license` |
| source_file | `NOTICE:1` | `NOTICE` | `hook.web.source.notice` |
| source_file | `pyproject.toml:10` | `project.license` | `hook.web.source.license` |
| source_file | `licenses/OSWorld-runtime-APACHE-2.0.txt:1` | `OSWorld-runtime` | `hook.web.source.license` |
| source_file | `src/cuawright/webwright/config/base.yaml:54` | `environment_class` | `hook.web.source.workspace_config` |
| source_file | `src/cuawright/webwright/config/base.yaml:58` | `shell` | `hook.web.source.shell` |
| source_file | `src/cuawright/webwright/config/base.yaml:65` | `browser_mode` | `hook.web.source.browser_mode` |
| source_file | `src/cuawright/webwright/run/cli.py:32` | `run_one` | `hook.web.source.run_one` |
| source_file | `src/cuawright/webwright/run/cli.py:83` | `trajectory_output` | `hook.web.writer.trajectory` |

## code 출력

| 종류 | 위치 | 심볼 | hook |
|---|---|---|---|
| code_output | `src/cuawright/webwright/environments/local_browser.py:424` | `_persist_step_code` | `hook.web.code_output.step_script` |
| code_output | `src/cuawright/webwright/environments/local_browser.py:427` | `_persist_step_code` | `hook.web.code_output.script_py` |
| code_output | `src/cuawright/webwright/environments/local_browser.py:442` | `_run_python_code` | `hook.web.code_output.page_exec` |
| code_output | `src/cuawright/webwright/environments/local_workspace.py:175` | `_persist_step_command` | `hook.web.code_output.shell_step` |
| code_output | `src/cuawright/webwright/environments/local_workspace.py:178` | `_persist_step_command` | `hook.web.code_output.shell_history` |
| code_output | `src/cuawright/webwright/environments/local_workspace.py:232` | `execute` | `hook.web.code_output.shell` |
| code_output | `src/cuawright/webwright/tools/browser_session.py:732` | `_run_step_code` | `hook.web.code_output.page_exec` |
| code_output | `src/cuawright/webwright/tools/browser_session.py:823` | `_cmd_step` | `hook.web.code_output.step_script` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/library.py:55` | `Library.add` | `hook.web.code_output.skill_py` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/update.py:103` | `_replay` | `hook.web.code_output.skill_py` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/update.py:110` | `_replay` | `hook.web.code_output.run_skill` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py:40` | `run_skill` | `hook.web.code_output.taskspec` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py:44` | `run_skill` | `hook.web.code_output.run_skill` |

## writer

분류되지 않은 writer는 0이다. 파일에 쓰는 지점만 writer이고, 실행·모델 호출은 action에 둔다.

| 종류 | 위치 | 심볼 | hook |
|---|---|---|---|
| code_output | `src/cuawright/webwright/environments/local_browser.py:424` | `_persist_step_code` | `hook.web.code_output.step_script` |
| code_output | `src/cuawright/webwright/environments/local_browser.py:427` | `_persist_step_code` | `hook.web.code_output.script_py` |
| code_output | `src/cuawright/webwright/environments/local_workspace.py:175` | `_persist_step_command` | `hook.web.code_output.shell_step` |
| code_output | `src/cuawright/webwright/environments/local_workspace.py:178` | `_persist_step_command` | `hook.web.code_output.shell_history` |
| code_output | `src/cuawright/webwright/tools/browser_session.py:823` | `_cmd_step` | `hook.web.code_output.step_script` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/library.py:55` | `Library.add` | `hook.web.code_output.skill_py` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/update.py:103` | `_replay` | `hook.web.code_output.skill_py` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py:40` | `run_skill` | `hook.web.code_output.taskspec` |
| png_debug | `src/cuawright/webwright/environments/local_browser.py:247` | `prepare` | `hook.web.writer.task_metadata` |
| png_debug | `src/cuawright/webwright/environments/local_browser.py:487` | `_capture_observation` | `hook.web.writer.screenshot` |
| png_debug | `src/cuawright/webwright/environments/local_workspace.py:189` | `_write_step_log` | `hook.web.writer.step_log` |
| png_debug | `src/cuawright/webwright/environments/local_workspace.py:204` | `prepare` | `hook.web.writer.task_metadata` |
| png_debug | `src/cuawright/webwright/agents/default.py:145` | `_write_debug_step_artifact` | `hook.web.writer.debug_step` |
| png_debug | `src/cuawright/webwright/agents/default.py:148` | `_write_debug_step_artifact` | `hook.web.writer.debug_markdown` |
| png_debug | `src/cuawright/webwright/agents/default.py:519` | `save` | `hook.web.writer.trajectory` |
| png_debug | `src/cuawright/webwright/utils/logging.py:19` | `append_runtime_log` | `hook.web.writer.runtime_log` |
| png_debug | `src/cuawright/webwright/config/__init__.py:103` | `snapshot_config_specs` | `hook.web.writer.config_snapshot` |
| png_debug | `src/cuawright/webwright/config/__init__.py:116` | `snapshot_config_specs` | `hook.web.writer.config_snapshot` |
| png_debug | `src/cuawright/webwright/config/__init__.py:121` | `snapshot_config_specs` | `hook.web.writer.config_snapshot` |
| png_debug | `src/cuawright/webwright/tools/browser_session.py:343` | `_atomic_write_private_json` | `hook.web.writer.session_state` |
| png_debug | `src/cuawright/webwright/tools/browser_session.py:913` | `_cmd_step` | `hook.web.writer.screenshot` |
| png_debug | `src/cuawright/webwright/tools/self_reflection.py:642` | `main` | `hook.web.writer.reflection_result` |
| png_debug | `src/cuawright/webwright/tools/persistent_local_browser.py:163` | `_cmd_create` | `hook.web.writer.session_state` |
| png_debug | `src/cuawright/webwright/run/doctor.py:60` | `check_screenshot` | `hook.web.writer.doctor_screenshot` |

## action

| 종류 | 위치 | 심볼 | hook |
|---|---|---|---|
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:289` | `_ensure_local_cdp_browser` | `hook.web.playwright.cdp_process` |
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:316` | `_prepare_async` | `hook.web.playwright.launch` |
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:330` | `_prepare_async` | `hook.web.playwright.cdp` |
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:344` | `_prepare_async` | `hook.web.playwright.launch` |
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:355` | `_prepare_async` | `hook.web.playwright.launch` |
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:368` | `_prepare_async` | `hook.web.playwright.navigate` |
| code_output | `src/cuawright/webwright/environments/local_browser.py:442` | `_run_python_code` | `hook.web.code_output.page_exec` |
| direct_playwright | `src/cuawright/webwright/environments/local_browser.py:487` | `_capture_observation` | `hook.web.playwright.screenshot` |
| code_output | `src/cuawright/webwright/environments/local_workspace.py:232` | `execute` | `hook.web.code_output.shell` |
| direct_playwright | `src/cuawright/webwright/tools/browser_session.py:223` | `open_browser_session` | `hook.web.playwright.cdp` |
| code_output | `src/cuawright/webwright/tools/browser_session.py:732` | `_run_step_code` | `hook.web.code_output.page_exec` |
| direct_playwright | `src/cuawright/webwright/tools/browser_session.py:913` | `_cmd_step` | `hook.web.playwright.screenshot` |
| direct_playwright | `src/cuawright/webwright/tools/persistent_local_browser.py:144` | `_cmd_create` | `hook.web.playwright.cdp_process` |
| direct_playwright | `src/cuawright/webwright/run/doctor.py:54` | `check_screenshot` | `hook.web.playwright.launch` |
| direct_playwright | `src/cuawright/webwright/run/doctor.py:60` | `check_screenshot` | `hook.web.playwright.screenshot` |
| code_output | `src/cuawright/webwright/agents/default.py:478` | `execute_actions` | `hook.web.action.dispatch` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/update.py:110` | `_replay` | `hook.web.code_output.run_skill` |
| code_output | `extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py:44` | `run_skill` | `hook.web.code_output.run_skill` |
| llm_helper | `src/cuawright/webwright/models/base.py:688` | `query` | `hook.web.llm.query` |
| llm_helper | `src/cuawright/webwright/models/openai_model.py:172` | `_usage_metrics_from_response_payload` | `hook.web.llm.usage` |
| llm_helper | `src/cuawright/webwright/tools/image_qa.py:71` | `run_image_qa` | `hook.web.llm.image_qa` |
| llm_helper | `src/cuawright/webwright/tools/self_reflection.py:403` | `run_self_reflection_async` | `hook.web.llm.self_reflection` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/skill_factory/llm.py:83` | `llm_json` | `hook.web.llm.skill_factory` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/skill_factory/retrieve.py:47` | `_retrieve_llm` | `hook.web.llm.skill_factory` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/skill_factory/decide.py:39` | `_decide_llm` | `hook.web.llm.skill_factory` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/skill_factory/fill.py:55` | `fill_params` | `hook.web.llm.skill_factory` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/skill_factory/learn.py:72` | `canonicalize_answers` | `hook.web.llm.skill_factory` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/tools/skill_use.py:58` | `recommend` | `hook.web.llm.recommend` |
| llm_helper | `extensions/skill-factory/src/cuawright/webwright/skill_factory/route.py:127` | `route` | `hook.web.llm.route` |
| llm_helper | `src/cuawright/webwright/agents/default.py:439` | `query` | `hook.web.llm.query` |
| llm_helper | `src/cuawright/webwright/agents/default.py:448` | `query` | `hook.web.llm.query` |
| png_debug | `src/cuawright/webwright/utils/browser_evidence.py:97` | `task_screenshot_paths` | `hook.web.writer.screenshot_index` |

anchor 문자열은 SOURCE.json과 검사 코드에 있다. 행 번호만으로 위치를 옮기지 않는다.
