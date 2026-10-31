# 기술 조사 — Web·Android AI QA 플랫폼

조사일: **2026-10-30 (Asia/Seoul)**. 상태: 공개 소스 정적 검토 완료, 실행 검증 전. 중심 설계는 [DESIGN.md](DESIGN.md), 후속 작업은 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)를 따른다.

## 1. 조사 범위와 신뢰 수준

사용자가 첨부 프롬프트를 작업 지시로 지정했다. 그중 조사·설계·계획 작성만 수행했다. 제품 코드, 의존성 설치, 모델 호출, 서비스 실행, 기기 조작, 클라우드 생성·배포는 수행하지 않았다. 회사 비공개 플랫폼의 기술은 추정하지 않았다.

현재 작업 저장소는 `.git`만 있는 빈 저장소이며 `master`에 커밋이 없다. 작업 폴더와 상위 경로에서 적용할 `AGENTS.md`를 찾지 못했다. 기존 설계·코드와 충돌하거나 덮어쓴 파일이 없다.

표기 기준:

- **확인**: 고정 커밋의 공개 코드 또는 공식 문서를 직접 읽어 확인. 동작 보장은 아님.
- **미확인**: 실행하지 않았거나 접근에 실패했거나 근거가 부족함.
- **별도 개발**: upstream 기능을 그대로 서비스 기능으로 쓸 수 없어 플랫폼 또는 연동 패치가 필요함.
- **설계 판단**: 조사 사실을 바탕으로 한 추천. upstream 기능과 구분한다.

GitHub 커넥터로 저장소 메타데이터, 기본 브랜치 HEAD, 재귀 tree, 핵심 파일을 읽었다. tree 응답은 두 저장소 모두 `truncated=false`였다. README는 최초 main 조회 후 HEAD를 고정해 핵심 파일을 읽었다. 조사 도중 변경 가능성이 있는 root README의 소식은 참고 정보로만 사용한다.

## 2. 버전과 재현 기준

| 대상 | 조사 기준 | 날짜/상태 | 버전 해석 |
|---|---|---|---|
| MobileAgent | main `81fa28b564ef7a695521500bc15a0e1324b2b394` | 커밋 시각 2026-10-28 03:02:17 UTC | 실제 검토 대상은 `Mobile-Agent-v3.5/` 디렉터리. 버전 이름을 Git tag로 취급하지 않음 |
| Mobile-Agent 논문 | arXiv `2602.16855v1` | 2026-02-15 제출, 조회 당시 v1 표시 | GUI-Owl-1.5와 다중 플랫폼·다중 역할 구성 설명 |
| CUAWright | main `35dbcf389ce2d9a77eb22f539c79a1274ea53559` | 커밋 시각 2026-10-27 03:02:22 UTC | `pyproject.toml` 패키지 버전 `0.2.0`, Python ≥3.10 |

근거: [MobileAgent 커밋](https://github.com/X-PLUG/MobileAgent/commit/81fa28b564ef7a695521500bc15a0e1324b2b394), [CUAWright 커밋](https://github.com/microsoft/CUAWright/commit/35dbcf389ce2d9a77eb22f539c79a1274ea53559), [논문 v1](https://arxiv.org/abs/2602.16855v1), [CUAWright 패키지 메타데이터](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/pyproject.toml#L5-L34).

두 저장소의 GitHub releases API 조회는 빈 배열이었다. tags API는 커넥터가 허용하지 않았고, 직접 네트워크 조회는 DNS 실패했다. MobileAgent tags 웹 화면은 release 부재를 표시했으나 캐시된 화면이고 CUAWright tags 웹 조회는 실패했다. 따라서 **tag 목록·최신 tag는 미확인**이며, tag가 없다고 단정하지 않는다. 이 설계는 위 SHA만 재현 기준으로 삼는다.

조회한 MobileAgent tree/README에서 v3.5보다 높은 Mobile-Agent 디렉터리는 확인하지 못했다. 이후 root README에는 호스팅 추론, Wuying Cloud Phone, 별도 ToolCUA 프로젝트 소식이 있다. 이것을 v3.5 로컬 실행 API 변경이나 새 Mobile-Agent 버전 출시로 해석하지 않는다. CUAWright는 2026-10-03 Webwright에서 이름이 바뀌어 desktop 경로가 추가되었고, 예전 `webwright` CLI/import 호환을 유지한다. 오래된 Webwright 예제의 경로와 현재 `cuawright.webwright`를 구분해야 한다. [현재 저장소 README](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/README.md).

## 3. Mobile-Agent: 모델·프레임워크·도구·환경

GUI-Owl-1.5는 화면을 이해하고 행동 형식을 출력하는 모델이다. Mobile-Agent는 모델 호출·기억·계획·행동 실행을 조직하는 프레임워크 계열이다. ADB·Playwright·PyAutoGUI는 실제 기기 제어 도구다. 로컬 PC·실기기·에뮬레이터·클라우드 샌드박스는 실행 환경이다. 모델 API를 호출해도 로컬 기기 제어 워커가 생기는 것은 아니다.

v3.5는 Android 전용이 아니다. README와 실제 경로가 PC, Android, Web을 각각 제공한다. 논문의 manager/worker/reflector/notetaker와 메모리 설계는 전체 연구 구조의 설명이다. 실기기 `mobile_use`와 일반 Web `browser_use`의 간단한 실행 루프가 그 모든 역할을 동일하게 제공한다고 볼 근거는 없다. AndroidWorld 연구 경로와 실제 USB 기기 경로도 구분한다. [v3.5 README](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/README.md), [논문 §2.3.3](https://arxiv.org/html/2602.16855v1#S2.SS3.SSS3).

### 3.1 Android 실기기 경로

| 항목 | 확인 내용 | 플랫폼에 필요한 작업 |
|---|---|---|
| 진입점 | `mobile_use/run_gui_owl_1_5_for_mobile.py:main`, `parse_args`; `--device`, `--max_steps` 등 존재 | 사용자 입력을 CLI 문자열로 직접 연결하지 않는 실행 명세 작성 |
| 모델 | `utils.py:GUIOwlWrapper.predict_mm` → OpenAI SDK `chat.completions.create`; 화면은 base64 변환 | 응답 형식 호환성 검사, 취소·예산·사용량 계측 |
| 행동 | `AdbTools`: 캡처·tap·swipe·키보드·패키지 조회·앱 실행 | 반환 코드 검사, 안전한 인자 배열, 허용 패키지 강제 |
| 좌표 | 모델 출력 0–1000; runner가 `smart_resize` 크기로 변환 | 모델 입력 이미지에서 실제 터치 좌표까지 변환을 검증·수정 |
| 기억 | 메모리 내 `history`, 최근 이미지 4개와 앞선 행동 요약 | 작업별 영구 이벤트 저장. 실행 간 승인 경로 기억과 다름 |
| 로그 | stdout 모델 출력, 원본 PNG·주석 PNG 디렉터리 | 정형 이벤트와 최종 캡처, 비밀값·사고 텍스트 제거 |
| 완료 | `terminate` 또는 `answer`에서 break | QA validator가 별도로 판정 |
| 개입 | 앱 미발견·`interact`에서 `input()` 대기 | 비대화형 워커에서는 `BLOCKED/HUMAN_REQUIRED`로 전환 |

근거: [실기기 runner](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/mobile_use/run_gui_owl_1_5_for_mobile.py), [ADB·메시지·모델 wrapper](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/mobile_use/utils.py).

정적 검토에서 발견한 연동 전제:

1. `build_messages`는 `file://` 접두사가 있는 이미지 경로를 만들고, 변환기는 그 값을 `Image.open(image_path)`에 넘긴다(`utils.py:337–445,504–515`). URI를 로컬 경로로 정규화하는 처리가 이 경로에서 보이지 않는다. Windows에서 공백·한글 경로를 포함해 재현 확인이 필요하다.
2. 이미지 전송 시 resize는 factor 28, runner 좌표 변환은 factor 16을 사용한다. runner는 resized 좌표를 ADB에 전달하며 원본 픽셀로 되돌리는 명시적 변환이 보이지 않는다(`runner:76–90,193–208`, `utils:436–445`). 회전·내비게이션 영역을 포함한 좌표 정합성을 검증해야 한다. 실제 오차 크기는 미측정이다.
3. `AdbTools._run`은 `shell=True`이고 반환 코드를 호출자에게 전달하지 않는다(`utils:81–84`). 캡처도 shell redirect와 파일 존재를 이용한다. command 전달 성공과 제품 상태 검증을 모두 보완해야 한다.
4. 출력 디렉터리가 instruction 일부에서 만들어지고 동일 경로를 지운다(`runner:149–160`). 그대로 서비스에 노출하지 않고 UUID 작업 공간으로 교체한다. 종료 행동에서는 history 기록 전 break하므로 최종 상태 근거를 별도로 저장한다.
5. wrapper는 원본 응답을 반환하지만 runner는 `output_text, _, _`로 usage를 버린다. 앱 이름 resolver도 별도 모델을 부른다. 계측은 resolver까지 포함하거나 승인한 package ID를 직접 사용해 resolver를 비활성화한다.
6. prompt에 있는 `key`, Menu/Enter 등이 runner에서 모두 dispatch되지는 않는다. 실제 dispatch와 capability allowlist만 노출한다. `terminate(success)`는 테스트 PASS가 아니다.

### 3.2 Web 경로

| 항목 | 확인 내용 | 해석 |
|---|---|---|
| 진입점 | `browser_use/run_gui_owl_1_5_for_web.py:main(args)` → `PlaywrightComputer` → `Agent._agent_loop()` | 일반 Web 실행 코드 존재 |
| 모델 호출 | `agent.py:_call_api`, OpenAI SDK chat completions, `API_KEY` 환경 변수 | OpenAI 호환 주소만으로 행동 프로토콜 호환이 보장되지 않음 |
| 행동 | SoM 숫자 label → bbox 중심 → Playwright mouse/type/select/scroll 등 | Android의 0–1000 좌표 프로토콜과 다름 |
| 로그/메모리 | `messages.json`, `action_info.json`, 화면 `trajectory/`, `trajectory_som/`; 이전 동작 요약 | 플랫폼 event/usage hook은 별도 작업 |
| 검증 | 선택적 `--eval` 경로, `judge_result` → Online-Mind2Web judge | 연구용 자동 평가이며 승인 QA 계약과 다름 |
| 실행 환경 | Chromium launch `headless=args.headless`, async context manager로 close | headless 코드 경로 확인, Windows 실동작 미검증 |
| 세션 | 공유 `browser/playwright/storage_state.json`; `keep_user_info` 사용 시 읽기/쓰기 | 프로젝트·계정·run별 분리 패치 필요 |
| 새 탭 | `_handle_new_page`가 새 탭을 닫고 기존 탭으로 이동 | 여러 탭을 유지하는 시나리오 지원으로 취급하지 않음 |

근거: [Web 진입점](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/browser_use/run_gui_owl_1_5_for_web.py), [Agent](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/browser_use/agent.py), [Playwright 실행기](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/browser_use/browser/playwright/browser_playwright.py), [프롬프트](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/browser_use/prompts.py).

Web 연동 전제:

- `Agent._get_format_messages`는 `args.provider`를 참조하지만 이 runner argparse에는 `provider`가 없다. **정적 불일치 확인**, 실제 실행 실패는 미재현. 설정 normalization 또는 수정 필요.
- 프롬프트는 `go_back`을 제시하지만 dispatch는 `goback`을 처리한다. action enum 문자열에 `select` 따옴표도 불일치한다. 정규화된 내부 action schema로 검증하고 알 수 없는 행동은 거부해야 한다.
- `exec_action`은 인식하지 못한 행동도 마지막에 `SUCCESS`를 반환할 수 있다. 정확한 dispatcher와 실패 반환을 보완해야 한다.
- `_call_api`는 응답 본문만 돌려줘 usage가 유실된다. SDK root `base_url`에 README 예제의 전체 `/chat/completions` URL을 그대로 쓰지 않도록 endpoint 종류를 분리해 확인한다.
- 호출 재시도는 최대 50회이고 `time.sleep`을 쓴다. `max_tokens`, temperature 등의 CLI 옵션이 선언되어도 `_call_api`에서 실제 전달되는지 별도 확인해야 한다. 플랫폼의 한도 정책으로 교체한다.
- `type_text_at`은 기본적으로 Enter를 누른다. 입력과 제출이 별개인 QA 단계에서는 승인한 행동으로 분리해야 한다.
- SoM bbox는 DPR을 곱하는 코드가 있다. Chromium은 scale factor 1을 지정하는 경로가 있으나 모든 OS 분기에서 동일하지 않다. MVP는 DPR=1·viewport 고정으로 제한하고 iframe·스크롤·고DPI 케이스는 기술 검증한다.
- 업로드·다운로드·dialog가 안정적으로 기록·복구되는 플랫폼 계약은 확인하지 못했다. 하위 Playwright의 기능 존재와 해당 에이전트의 제품 지원은 구분한다.

`PlaywrightComputer`는 Python Playwright를 직접 import한다. **Playwright MCP를 쓴다는 근거는 없다.** PC 경로의 PyAutoGUI는 데스크톱 세션이 필요하지만 Web의 Playwright headless 경로까지 데스크톱 세션이 필요하다는 뜻은 아니다. [PC runner](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/computer_use/run_gui_owl_1_5_for_pc.py).

### 3.3 SDK·런타임·라이선스

안정적인 제품용 SDK/진행 callback API는 검토한 실기기·Web 경로에서 확인하지 못했다. Python 함수·클래스는 있으나 sibling import, private loop, args 구조에 의존한다. CLI subprocess는 기술 검증에는 쓸 수 있지만 stdout 파싱만으로 한도·행동 승인·취소를 강제하기 어렵다. 추천은 **SHA를 고정한 작은 연동 패치 + 별도 runner subprocess**이며 공개 SDK가 있다고 표현하지 않는다.

Android는 호스트 ADB, USB debugging 권한, 승인한 입력 방식이 필요하다. README는 Windows `adb.exe`를 안내한다. ADB Keyboard는 CJK 입력을 의도하지만 한글/특수문자·IME 복구는 실기기 검증 전이다. Web은 Python·Chromium·Playwright 및 requirements의 OpenAI, 이미지/HTML 처리 패키지 등이 필요하다. 최소 Python/전체 dependency lock은 이 경로에서 확정하지 못했으며 플랫폼 기준 Python 3.11을 제안한 뒤 호환 spike에서 확정한다. GPU는 외부 모델 API 호출만 한다면 로컬 워커의 필수 전제가 아니다.

MobileAgent root 코드는 MIT이다. 하위 AndroidWorld 등은 별도 라이선스가 있으며 모델 weights·ADB Keyboard·클라우드 서비스 약관은 root MIT로 포괄되지 않는다. 이번 MVP는 AndroidWorld를 포함하지 않는다. [root LICENSE](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/LICENSE).

## 4. CUAWright: 세 가지 Web 실행 경로

### 4.1 스크립트 생성

`src/cuawright/webwright/run/cli.py:run_one`이 config를 합성하고 model/env/agent를 생성한 뒤 `env.prepare`, `agent.run`, finally `env.close`를 호출한다. Python에서 import 가능한 함수가 있지만 서비스용 장기 안정 SDK 계약으로 문서화되었다고 단정하지 않는다. CLI도 `cuawright-web` 또는 모듈 경로로 노출된다.

`base.yaml`의 `local_workspace` 환경은 모델이 bash 명령으로 Playwright 코드를 작성·실행하도록 한다. `final_script.py`, `plan.md`, `final_runs/`, screenshot·log를 남기도록 지시한다. 기본 browser mode는 Browserbase이고 `browser_mode=local`을 선택해야 로컬 Chromium이다. `/bin/bash` 기본값이므로 Windows native에서 그대로 동작한다고 가정하지 않는다. Linux VM 또는 별도 OS 검증이 필요하다.

script가 생성돼도 탐색·디버깅·`image_qa`·`self_reflection`·컨텍스트 요약에는 모델 호출이 들어갈 수 있다. 생성 파일 자체가 helper 호출·API 호출을 담았는지 검사해야 무모델 실행 여부를 알 수 있다. [run_one](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/run/cli.py#L32-L136), [base 설정](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/config/base.yaml), [local workspace](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/environments/local_workspace.py).

### 4.2 실시간 실행

실시간에도 서로 다른 경로가 있다.

- `local_browser.yaml`은 live Playwright page/context에 모델의 async `python_code`를 실행한다. 독립 최종 script 생성과 artifact self-reflection은 사용하지 않는다. 기본 `local_cdp`는 기존 브라우저·프로필에 연결하므로 테스트 격리에 부적합할 수 있다. 플랫폼에서는 `local_launch`와 새 context로 덮어써야 한다. 저장한 screenshot 경로는 관찰에 나오지만 이미지가 기본적으로 모델에 첨부되는 것은 아니다.
- `best_default_judge_json_persistent_cli.yaml`의 README 실시간 예시는 Browserbase cloud session을 사용한다. API key/project ID가 필요하다. 이를 로컬 실행의 필수 요구로 일반화하지 않는다.
- `persistent_browser.yaml`은 별도 로컬 Chromium subprocess를 유지하며 shell 명령들이 CDP로 재연결한다. 종료 시 해당 세션을 release해야 한다. 이 역시 script/workspace 계열이고 `local_browser`와 다르다.

`LocalBrowserEnvironment._run_python_code`는 `exec`로 모델 코드를 실행한다. process 분리·timeout만으로 안전한 sandbox가 되지 않는다. Web만 제어하도록 프롬프트에 쓰는 것은 파일·네트워크 권한 통제가 아니다. [local_browser 설정](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/config/local_browser.yaml#L1-L87), [실행/캡처 코드](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/environments/local_browser.py#L432-L502), [persistent 로컬 설정](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/config/persistent_browser.yaml).

### 4.3 Skill Factory

별도 optional distribution `cuawright-skill-factory==0.2.0`이다. 학습·코드 일반화·replay 검증·추천 routing을 base runtime과 구분한다.

| 기능 | 실제 코드 | 모델 호출 해석 |
|---|---|---|
| 실행 기록을 skill로 변환/검증 | `skill_factory/update.py`, `learn.py`, gate와 replay 절차 | 생성·판정은 모델 비용 발생 가능 |
| library 추천 | `tools/skill_use.py:recommend` → retrieve, decide, promote/fill | 기본 retrieve·decide·fill은 `llm_json` 호출. route 전체가 0 token이라는 의미가 아님 |
| 직접 코드 실행 | `execute.py:run_skill(source_path, params, *, start_url='', output_schema=None, timeout=240)` | 함수 자체는 모델 없이 `python skill.py taskspec.json` subprocess 실행 |
| 자동 route/fallback | `route.py:route(..., run_skill_fn, agent_fn, on_decision)` | `run` 실패 또는 adapt/skip이면 agent. fallback은 모델 비용 발생 가능 |
| 결과 gate | shape·비어 있지 않은 답 검사, 가능한 경우 gold 비교 | 잘못된 값이 올바른 shape로 나와도 통과 가능. QA oracle을 대체하지 못함 |

근거: [직접 실행](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py#L1-L66), [route](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/route.py#L137-L173), [recommend](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/tools/skill_use.py#L58-L111), [retrieve](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/retrieve.py), [decide](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/decide.py), [fill](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/fill.py), [gate](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/gate.py).

**우리 플랫폼에서 무모델 재실행으로 표시할 조건**: 승인한 script/hash와 dependency lock을 직접 선택하고, 매개변수를 확정하며, 모델 helper·SDK·fallback을 제거/차단하고, 모델 자격증명을 주입하지 않고, 외부 모델 endpoint 접근을 차단한 상태에서 새 실행의 모든 필수 검증을 결정적 코드로 수행할 것. 추천·시각 판정에 모델을 쓰면 순수 무모델 모드가 아니다. 직접 `run_skill`을 사용하는 것만으로 내용 정확성은 보장되지 않는다.

### 4.4 증거·모델·OS·라이선스

`DefaultAgent.run`은 step마다 `save`하고 `trajectory.json`과 debug artifact에 행동·관찰·응답 정보를 남긴다. 공개 `query/execute_actions/serialize/save`는 연동 지점이지만 제품용 이벤트 callback은 별도 개발이다. `local_browser`는 screenshot·ARIA·console을 반환한다. script 경로는 instrumentation이 코드/프롬프트 준수에 의존하므로 screenshot 누락을 플랫폼이 탐지해야 한다. [DefaultAgent](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/agents/default.py#L394-L451), [browser evidence 유틸](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/utils/browser_evidence.py).

OpenAI·Anthropic·OpenRouter backend가 공개되어 있다. 검토한 OpenAI backend는 Responses 형식과 run_command 또는 JSON schema 응답 모드를 갖는다. OpenAI 호환 Chat Completions 서버가 Responses까지 지원한다고 가정하면 안 된다. usage 변환이 일부 누락 값을 0으로 정규화할 수 있어 플랫폼은 원본 usage 존재 여부를 별도 보존해야 한다. nested image_qa/self_reflection·summary·Skill Factory 호출까지 합산해야 한다. [OpenAI backend](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/models/openai_model.py#L172-L201).

브라우저 패키지는 Python ≥3.10, Playwright ≥1.45 등이고 desktop extra는 Python 3.12+ 및 별도 VM 준비가 필요하다. 이번 제품은 CUAWright desktop/OSWorld를 사용하지 않는다. local_browser는 headless 코드 설정을 갖는다. headed 모드·실제 CDP 브라우저는 사용자 세션이 필요하다. Linux bash workspace 경로와 native Windows live 경로의 지원 수준을 나눠 실측해야 한다.

브라우저 runtime은 MIT, imported desktop runtime은 Apache-2.0이며 패키지는 `MIT AND Apache-2.0`이다. 전체를 단순 MIT라고 기록하지 않는다. [LICENSE](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/LICENSE), [NOTICE](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/NOTICE).

## 5. 기능 상태표와 반복 실행 모드

| 기능 | Mobile-Agent Web | Mobile-Agent Android | CUAWright Web |
|---|---|---|---|
| 실제 실행 경로 | 확인, 연동 패치 필요 | 확인, 연동 패치 필요 | 확인, 모드 선택·격리 필요 |
| 매 실행 AI 판단 | 확인 | 확인 | 확인 |
| 승인 단계 고정·단계별 정책 강제 | 별도 개발 | 별도 개발 | 별도 개발 |
| 결정적 QA assertion 집계 | 별도 개발 | 별도 개발 | 일반 코드로 가능, 플랫폼 집계는 별도 |
| AI 시각 검증 | 연구 judge 확인 | 단순 USB runner의 독립 verifier 미확인 | image_qa/self_reflection 확인, live local에는 기본 비활성 |
| 화면 캡처 | 확인 | 확인 | 확인, 모드별 수집 방식 다름 |
| 진행 정형 이벤트/실시간 취소 | 별도 개발 | 별도 개발 | 별도 개발 |
| usage·비용 완전 집계 | 별도 개발 | wrapper 응답 활용 + 별도 개발 | 일부 usage 확인, 전체 호출 통합 별도 |
| 일반 코드 무모델 재생 | 검토 경로에서 확인 못함 | 검토 경로에서 확인 못함 | 조건부 확인, 생성·추천·검증 비용과 분리 |
| Android USB 제어 | 해당 없음 | 확인 | 검토한 Web 코드에 없음 |
| 사람 승인·불변 버전·회귀 비교 | 별도 개발 | 별도 개발 | 별도 개발 |

반복 모드 구분:

1. **매번 AI 탐색**: 세 경로 모두 가능. 매번 모델 호출, 목표 달성 경로가 달라질 수 있음.
2. **단계 고정 + 탐색/일부 검증 AI**: 플랫폼이 승인 단계별 실행·금지 경로·검증을 강제하는 별도 모드. **추천 MVP**. Mobile-Agent의 단일 긴 task 루프를 그대로 반복하는 것과 다름.
3. **일반 코드 + AI 0회**: CUAWright 산출물에 대해 조건부 가능. 승인·독립 replay·dependency 고정·격리·현재 assertion은 별도 기능 비용. Mobile-Agent에도 있다고 가정하지 않음.
4. **산출물/로케이터 재사용 + 실패 시 AI**: CUAWright Skill Factory가 부분 지원하지만 추천·parameter 추론도 모델을 쓸 수 있음. 플랫폼은 승인한 코드를 먼저 직접 선택하는 방식이 더 명확하다. 과거 PASS 결과를 현재 PASS로 재사용하는 방식은 채택하지 않음.

계획 cache는 탐색 지침, locator cache는 현재 요소 조회 힌트, 고정 좌표는 특정 화면의 위치, 화면 재탐색은 현재 화면 모델 판단, QA 검증은 현재 기대 결과 검사다. 서로 대체하지 않는다. source/target version이 바뀐 cache는 폐기하거나 재검토한다.

## 6. A/B 구성 비교와 추천 근거

수치 점수 대신 확인된 연동 작업을 비교한다. 성공률·비용 절감률은 측정 전이다.

| 기준 | A: Web·Android Mobile-Agent | B: Web CUAWright + Android Mobile-Agent |
|---|---|---|
| 초기 연동 | Python 중심, 두 경로 별도 패치. Web 정적 불일치 해결 필요 | Android 작업에 더해 Web의 코드 실행 격리·모드/설정 결합 필요 |
| QA 검증 | 두 경로에 공통 플랫폼 validator 필요 | Web assertion을 코드로 표현하기 좋지만 생성 결과를 신뢰할 수 없어 동일 validator 책임 필요 |
| 증거 | PNG·action log 재사용, final capture·event 추가 | trajectory/ARIA/console 재사용 장점. script instrumentation 누락 처리 필요 |
| 반복 비용 | 매 실행 AI 호출 지속 | 승인 코드 직접 실행 시 낮출 여지. live/route 자체가 항상 무모델은 아님 |
| 유지보수 | 한 저장소이나 Web/Android 내부 프로토콜은 다름 | 두 저장소·모델 프로토콜·실행 방식·보안 패치 관리 |
| 모델 종속 | Android GUI-Owl 행동 형식 의존, Web SoM prompt 의존 | Web coding model·Responses 등 backend 의존, Android는 동일 |
| 격리 | 구조화 행동 allowlist를 통제하기 상대적으로 쉬움 | shell/exec Python은 제한 계정·VM와 egress 통제가 먼저 필요 |
| 코드 재사용 | 공통 정책·모델 계측 재사용, 일반 코드 replay 근거 없음 | Web script/Skill Factory 활용 가능. Android까지 같은 기능이 되지는 않음 |

**설계 판단: A를 1차 추천한다.** 첫 제품의 목표는 Windows+USB 한 대에서 Web·Android 실행·검증·사람 승인을 완성하는 것이다. 코드 생성·재생까지 동시에 넣는 B는 추가 시스템 경계가 크다. A는 더 저렴하거나 성공률이 높다고 입증된 선택이 아니다. Mobile-Agent Web의 호환성 spike가 선행 조건이며, 해결 비용이 승인된 기술 검증 한도를 넘으면 B의 `local_browser/local_launch` 대안을 재검토한다. 이때도 임의 Python 격리 비용을 포함한다. 코드 재생이 첫 출시 필수로 바뀌면 B를 다시 결정한다. 두 엔진 사용은 필수가 아니다. Midscene 등 제3안은 두 후보의 구체적 탈락이 아직 확인되지 않아 조사 범위를 넓히지 않았다.

## 7. 보조 설계 근거와 남은 확인

FastAPI는 관리 API와 서버 렌더링 진입점으로 선택한다. 긴 실행은 요청 프로세스의 background task가 아니라 별도 워커 책임으로 설계한다. HTMX는 HTML 부분 갱신으로 프런트 복잡도를 낮추기 위한 선택이다. SQLite WAL은 같은 호스트의 로컬 저장에 한정하고, 원격 워커는 HTTP로만 관리 API에 연결한다. BrowserContext는 쿠키·스토리지 격리에 활용한다. 이들은 제품 설계 선택이며 upstream 엔진 API가 아니다. [FastAPI background task 주의점](https://fastapi.tiangolo.com/tutorial/background-tasks/), [HTMX 공식 문서](https://htmx.org/docs/), [SQLite WAL 제약](https://www.sqlite.org/wal.html), [Playwright context 격리](https://playwright.dev/python/docs/browser-contexts).

미확인 항목: 지정 PC·기기·앱의 실제 동작, API 계정의 모델 접근권/화면 반출 정책, GUI-Owl 모델별 endpoint/이미지/좌표 호환, 정확한 dependency lock, tag 목록, 한글 IME 복구, 고DPI/회전/iframe, 파일 입출력/새 탭 시나리오, 캡처 금지 화면, 모든 하위 호출의 usage 제공 여부. 이들은 구현 계획 P0의 종료 조건 또는 후속 capability gate로 남긴다. 벤치마크나 README의 실행 시간·zero token·성공률은 우리 서비스의 보장값으로 사용하지 않았다.
