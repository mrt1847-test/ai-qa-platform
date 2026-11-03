# 기술 조사 — Web·Android AI QA 플랫폼

> **2026-11-02 배치 확정:** [중앙 관리·실행 PC 규범](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md)이 실행 위치/수명의 우선 규범이다. 관리 서버·DB·증거는 실행 PC와 분리한다. 초기 실행 자원은 현재 PC이며 추가 PC/선택 cloud adapter로 확장한다. 접속 PC는 웹만 사용한다. 실행 PC offline에도 서버 저장본 조회/승인은 가능하고 재녹화/테스트는 불가하다. 실제 분리 배포·단절 감지/원격 실행의 완료는 별도 근거가 필요하다.

공개 코드 조사일: **2026-10-30**, UI 개정일: **2026-10-31 (Asia/Seoul)**. 문서 v0.6. 실행 정책 개정/일부 고정 소스 재확인: 2026-10-31. 상태: 공개 소스 정적 검토 완료, 실행 검증 전. 중심 설계는 [DESIGN.md](DESIGN.md), 화면 명세는 [UI_SPEC.md](UI_SPEC.md), 후속 작업은 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)를 따른다.

현행 제품 결정은 [실행 상세](docs/superpowers/specs/2026-10-31-replay-and-self-healing-design.md)의 **CUAWright Web authoring/승인 code replay + Mobile-Agent Android authoring/플랫폼 action replay**, 선택 verifier·기본OFF bounded healing이다. [v0.5 조사](docs/history/v0.5/RESEARCH.md)의 A안/매 실행 AI 기본은 이전 결정이다. 아래 upstream 사실과 플랫폼 추가 개발을 구분한다.

## 1. 조사 범위와 신뢰 수준

사용자가 첨부 프롬프트를 작업 지시로 지정했다. 그중 조사·설계·계획 작성만 수행했다. 제품 코드, 의존성 설치, 모델 호출, 서비스 실행, 기기 조작, 클라우드 생성·배포는 수행하지 않았다. 회사 비공개 플랫폼의 기술은 추정하지 않았다.

최초 조사 당시 작업 저장소는 `.git`만 있는 빈 저장소였으며 `master`에 커밋이 없다. 작업 폴더와 상위 경로에서 적용할 `AGENTS.md`를 찾지 못했다. 기존 설계·코드와 충돌하거나 덮어쓴 파일이 없다.

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

`base.yaml`의 `local_workspace` 환경은 모델이 bash 명령으로 Playwright 코드를 작성·실행하도록 한다. `final_script.py`, `plan.md`, `final_runs/`, screenshot·log를 남기도록 지시한다. 재확인한 같은 SHA의 base.yaml은 `browser_mode: local`이다. Browserbase 설정을 선택하는 경로에서는 별도 key/project ID가 필요하며 이를 로컬 실행의 필수 요구로 일반화하지 않는다. v0.5의 base 기본 Browserbase 표기는 정정한다. `/bin/bash` 기본값이므로 Windows native에서 그대로 동작한다고 가정하지 않는다. Linux VM 또는 별도 OS 검증이 필요하다.

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
2. **단계 고정 + 탐색/일부 검증 AI**: 플랫폼이 승인 단계별 실행·금지 경로·검증을 강제하는 별도 모드. **v0.5의 기본안이며 v0.6에서는 대체**. Mobile-Agent의 단일 긴 task 루프를 그대로 반복하는 것과 다름.
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

**v0.6 설계 판단: B의 Web CUAWright + Android Mobile-Agent authoring을 채택하고 양쪽 모두 플랫폼의 recorded_replay를 기본 실행 경로로 만든다.** 사용자가 월1회3,000 TC의 반복 호출 비용을 줄이는 목적을 명확히 했으므로 승인 code/action 재생을 MVP 필수로 옮긴다. 기존 A 선택은 초기 구현 범위 최소화를 위한 과거 판단이며 두 구성의 실제 비용/성공률을 입증한 결과가 아니었다.

CUAWright의 code 생성/직접 실행 경로를 활용하되 매 회귀마다 자동 recommend/agent fallback을 호출하지 않는다. source script→제한 IPC script/동작 mapping·현재 QA·권한/네트워크가 분리된 driver/로컬 VM·키 미주입은 플랫폼 개발/실측 gate다. Android의 원본 model loop 대신 structured plan runner도 별도 개발한다. 선택 verifier와 bounded healer는 역할/한도를 통제하고 제품 expected/path 위반·이미 처리됐을지 모르는 action은 치유로 우회하지 않는다. 전체 출시는 양 플랫폼 replay/격리/증거/판정 gate를 모두 만족해야 한다.

## 7. 보조 설계 근거와 남은 확인

FastAPI는 관리 API와 서버 렌더링 진입점으로 선택한다. 긴 실행은 요청 프로세스의 background task가 아니라 별도 워커 책임으로 설계한다. HTMX는 HTML 부분 갱신으로 프런트 복잡도를 낮추기 위한 선택이다. SQLite WAL은 같은 호스트의 로컬 저장에 한정하고, 원격 워커는 HTTP로만 관리 API에 연결한다. BrowserContext는 쿠키·스토리지 격리에 활용한다. 이들은 제품 설계 선택이며 upstream 엔진 API가 아니다. [FastAPI background task 주의점](https://fastapi.tiangolo.com/tutorial/background-tasks/), [HTMX 공식 문서](https://htmx.org/docs/), [SQLite WAL 제약](https://www.sqlite.org/wal.html), [Playwright context 격리](https://playwright.dev/python/docs/browser-contexts).

미확인 항목: 지정 PC·기기·앱의 실제 동작, API 계정의 모델 접근권/화면 반출 정책, GUI-Owl 모델별 endpoint/이미지/좌표 호환, 정확한 dependency lock, tag 목록, 한글 IME 복구, 고DPI/회전/iframe, 파일 입출력/새 탭 시나리오, 캡처 금지 화면, 모든 하위 호출의 usage 제공 여부. 이들은 구현 계획 P0의 종료 조건 또는 후속 capability gate로 남긴다. 벤치마크나 README의 실행 시간·zero token·성공률은 우리 서비스의 보장값으로 사용하지 않았다.

## 8. v0.2 추가 요구의 조사·개발 경계

추가 프롬프트는 관리 UI/회귀 묶음·APK 빌드·실행 환경 adapter·로컬 운영 수명을 구체화했다. MobileAgent/CUAWright의 출처 SHA는 §2의 기존 조사 기준을 유지한다. 이번 개정에서 HEAD가 새로 검증됐다고 주장하지 않으며, UI/묶음/APK 기능이 해당 engine에 존재하는 것으로 소급하지 않는다. [v0.1 조사 보관본](docs/history/v0.1/RESEARCH.md)과 비교 가능하다.

| 추가 영역 | 사실/기능 상태 | 반영 위치 |
|---|---|---|
| UI CRUD·검색/복제·반려·회귀 묶음·export | 플랫폼 별도 개발. 공개 engine demo/trajectory viewer는 이 관리 제품을 대체하지 않음 | DESIGN §8–9, UI_SPEC, 계획 T2/T3/T7/T8 |
| agent/environment adapter 분리 | 제안 플랫폼 경계. upstream에 이 인터페이스가 있다는 주장이 아님 | DESIGN §8.1 |
| 설치된 package 선택·명시 APK 설치 | ADB가 앱 설치/기기 통신을 제공함. build registry·lease·승인 policy·hash 검증은 별도 개발 | DESIGN §8.6, 계획 T3 |
| APK metadata | Android SDK apkanalyzer 공식 명세에서 package/version/minSdk·파일 목록 분석 확인. ABI/서명/업데이트 호환 전체 판정은 추가 검사·실기기 검증 필요 | 계획 T0/T1/T3 |
| Windows/WSL/컨테이너 | Windows 실동작도 미검증. WSL USB 전달·ADB server 경계·GUI 접근을 자동 호환으로 가정하지 않음 | DESIGN §3, 계획 P0 |
| 원격 브라우저/device farm | 엔진 프로토콜·ADB/제어 API·가속·session 제약이 미확인. Appium 지원만으로 호환성 확정 불가 | DESIGN §8.7, 계획 T11 |
| 탭 종료와 PC 종료/절전 | UI 탭과 worker process 수명 분리는 플랫폼 별도 개발. PC가 멈춘 동안 실행 지속/즉시 감지를 보장하지 않음 | DESIGN §3·13, 계획 T8/T9 |

2026-10-30 추가 확인한 공식 1차 자료: [Android apkanalyzer](https://developer.android.com/tools/apkanalyzer)는 SDK Command-Line Tools에 포함되며 앱 ID·버전·manifest 최소 SDK·파일 정보를 조회할 수 있다. [Android ADB](https://developer.android.com/tools/adb)는 호스트 client/server와 기기 daemon 구조, USB debugging 승인과 앱 설치 명령을 설명한다. 따라서 브라우저 프런트엔드가 ADB를 직접 실행하는 설계로 연결하지 않는다. 관리 API→인증 worker→지정 기기 제어 경계를 사용한다.

앱 분석 도구/서명 검사 도구의 실제 Windows 경로·버전, QA APK의 minSdk/ABI·설치/업데이트 동작은 실행하지 않아 미확인이다. APK 파일 업로드/검사·설치, SDK 설치·기기 조작·모델 API 호출은 이번 개정에서 수행하지 않았다. 이 절의 로컬 브라우저·USB 가정은 이전 조사 범위다. 최신 목표는 cloud browser/device farm이며 공급자 자격과 모델 API 접근권은 서비스 측에서 따로 관리한다. 실제 호환성/공급자 능력은 CF-01에서 공식 자료와 고정 source로 다시 확인한다.

## 9. v0.3 UI·녹화 보관 요구 검토 — 이전 결정 기록

2026-10-31 첨부 `AI_QA_UI_design.md`와 후속 사용자 설명으로 UI를 재설계했다. **녹화 동작별 PNG/로그는 먼저 저장하고, 녹화 완료·보관 뒤 사람이 저장본을 검토하여 AUT version을 승인한다.** 녹화 중 action별 승인을 받는 기능이나 승인이 저장 선행 조건인 구조가 아니다. TC/AUT/REC/RUN/ITEM 분리와 15개 화면·7개 wireframe·보고서/분모 계약은 UI_SPEC, 당시 구현 준비는 T0–T11이었으며 현행은 T0–T14와 W01–W32를 따른다.

공개 engine에는 이 플랫폼의 TC/케이스 registry·원본 REC 보관·action별 전후 캡처/정제 로그 보장·완료 후 review/approval·공통 RUN report가 이미 있다고 확인한 바 없다. 검토한 Mobile-Agent의 pre-step PNG/history/stdout은 자료가 될 수 있으나, 각 tap/swipe/type/back 직전/직후 capture와 log/event의 신뢰 경계는 **별도 개발·실행 검증 필요**다. 녹화라는 UI 명칭으로 무모델 replay나 수동 입력 capture 지원을 가정하지 않는다.

v0.3은 기존 SHA의 source 검토를 재사용하며 새 HEAD/모델 호환성/수동 녹화 기능을 추가 확인했다고 주장하지 않는다. 공개 코드 설치·실행·모델 호출 없이 문서만 수정했다. [v0.2 조사](docs/history/v0.2/RESEARCH.md)는 보관했다. 중단·누락 기록도 저장하되 저장장치 장애 시 수집 못 한 파일을 저장 완료라고 표시하지 않으며, 보관/승인/QA 판정을 각각 구분한다.

## 10. v0.4 케이스 통합·선택 TC 결정

2026-10-31 사용자가 검증 내용과 녹화 기록을 같은 케이스에서 관리하고 TC는 별도로 필요할 때만 사용하도록 확정했다. 이에 v0.3의 필수 주 TC·TC version 일치·current/historical 영향 gate를 제거했다. **디바이스/테스트 브라우저 선택→필요 정보→케이스 자연어 검증 입력→AI 녹화→동작별 기록 선저장→완료 후 검토/승인**이 기본 동선이다.

케이스 version은 원문·검증 정의·실행 설정·실제 절차/binding·증거 ref를 함께 가진다. REC/RUN/ITEM·사용량/artifact는 물리적으로 나누되 케이스의 조회/승인/재실행 단위는 하나다. 선택 TC 참조는 nullable metadata이며 TC가 없거나 변경/보관되어도 케이스를 차단·자동수정하지 않는다. 명시 내용 가져오기/diff 수락으로 case.definition이 바뀐 경우에만 새 case version·재승인한다.

이것은 플랫폼 제품/데이터 모델 결정이며 Mobile-Agent/CUAWright의 검증된 SDK 기능이 아니다. 기존 upstream SHA·실기기/모델·동작별 capture hook의 미확인 사항은 그대로 유지한다. 추가 공개 코드 조회/제품 실행 없이 UI_SPEC·DESIGN·IMPLEMENTATION_PLAN 계약을 개정했다. [v0.3 조사](docs/history/v0.3/RESEARCH.md)는 보관했다.

## 11. v0.5 저장·승인·재녹화·누적 분석 점검

2026-10-31 기존 설계를 점검했다. 불변 버전/원본 선저장 방향은 있었으나 DB 제약·원자 승인/pin·재녹화 교체·부분 기록의 완성 판정·복구 receipt·장기 분석/보관이 충분히 구체적이지 않았다. [DATA_DESIGN.md](DATA_DESIGN.md)에 소속 composite FK·UNIQUE/CHECK·manifest별 멱등 materialization·source/trial evidence membership·승인/default/pin 원자성·전체 재녹화 branch·누적 최소 facts·commit cursor/usage ledger·보관/backup 규범을 추가했다. [v0.4 조사](docs/history/v0.4/RESEARCH.md)는 보관했다.

이번에 재확인한 공식 근거와 제안의 구분:

| 공식 자료에서 확인한 사실 | 플랫폼 설계 판단 |
|---|---|
| SQLite FK는 연결별 활성화가 필요하며 composite FK를 지원 | project/case·같은 attempt 관계를 FK로 강제하고 migration/API 부정 시험을 둠. review의 exact REC/ITEM lineage는 별도 transaction 검사 |
| 여러 read transaction과 동시에 하나의 write transaction | API만 DB writer, 짧은 CAS/claim/승인 transaction, 모델 호출/파일 전송은 밖에서 수행 |
| unique partial index 지원, WHERE에 다른 table/subquery 참조 불가 | nullable REC/ITEM owner의 유일성은 partial index, 승인 적합성/active protection은 transaction으로 검사 |
| Online Backup API는 실행 중인 DB의 일관 snapshot을 제공 | DB snapshot이 참조한 artifact manifest/hash·임시 보호·복원 검사를 별도로 묶음 |

출처: [SQLite FK](https://sqlite.org/foreignkeys.html), [transaction](https://sqlite.org/lang_transaction.html), [partial index](https://sqlite.org/partialindex.html), [online backup](https://sqlite.org/backup.html). SQLite 보장이 파일 저장소/외부 클릭까지 확장되는 것은 아니므로 파일 staging/ready/reconcile·GC 경합·외부 행동의 불명 결과 정책은 플랫폼 별도 개발이다.

읽기 전용 설계 검토에서 provenance ref와 삭제 방지 protection 분리, 불변 core와 만료 payload 분리, 같은 case의 다른 실행 근거 혼입 차단, series/strict cohort 구분, 장기 commit cursor 재현성도 보완했다. 이것은 문서 검토 결과이며 실제 migration/DB 장애·부하·백업복원 시험의 합격 근거는 아니다. Mobile-Agent/CUAWright 조사 SHA는 §2를 유지하고 새 HEAD/동작 호환성을 추가 검증했다고 주장하지 않는다. 제품 코드·DB 생성·설치·모델/기기 실행·배포는 수행하지 않았다.

## 12. v0.6 재생 우선·선택 검증·셀프힐링 결정

사용자가 확정한 흐름은 AI agent로 녹화하고, 테스트는 녹화된 code/동작/조건 고정 좌표를 재생하며, 필요한 검증에만 AI를 사용하고 예외에서는 self-healing ON/OFF에 따라 국소 AI 복구를 허용하는 것이다. 핵심 정책은 [실행 상세](docs/superpowers/specs/2026-10-31-replay-and-self-healing-design.md), 저장은 DATA_DESIGN, UI는 UI_SPEC, 진행 순서는 WORK_PROGRESS의32개 W 단위를 따른다.

| 근거/경계 | 해석 |
|---|---|
| Mobile-Agent Android 원본은 매 loop capture→모델→action dispatch | 그대로 재실행하면 actor 호출이 반복되므로 recorder로 사용하고 deterministic action runner를 별도 개발 |
| CUAWright execute.py는 Python skill 직접 실행, route.py는 추천/실패 시 agent 경로 | exact 승인 package를 직접 지정. script 안의 hidden model 호출·fallback을 차단해야 actor0이라고 표시 가능 |
| CUAWright base.yaml은 local_workspace·shell /bin/bash·browser_mode local | 이전 로컬 배치 제안의 근거. 최신 cloud 배치에서는 실제 browser/context hook과 원격 protocol·서비스 측 격리/driver 수명/cancel·캡처를 CF-01에서 다시 대조 |
| code 생성/skill result shape가 실제 검증 정답을 보장하지 않음 | 코드 실행 완료와 QA PASS 분리·현재 oracle/근거·OFF clean trial·사후 사람 승인 필요 |

이번에 고정 SHA의 관련 코드를 재확인했다. [Mobile-Agent Android loop](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/mobile_use/run_gui_owl_1_5_for_mobile.py#L169-L213), [CUAWright 직접 실행](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py), [route/fallback](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/route.py#L137-L160), [base 설정](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/config/base.yaml). HEAD/새 release·실행 성공을 검증한 것은 아니다.

월3,000 TC는1data×1환경×1회 가정이며 모델/제공자·이미지/이력·청구 출력·cache·retry·치유 빈도로 비용이 달라진다. OpenAI의 경우 이미지도 입력 token으로 과금되고 가격은 모델/처리 옵션별로 다르다. [공식 이미지 과금](https://developers.openai.com/api/docs/guides/images-vision), [공식 가격표](https://developers.openai.com/api/docs/pricing). 특정 모델의 앞선 대화 계산은 가정치이며 GUI 행동/검증 호환·정확성 추천이 아니다. W32에서 대표30–50 TC/각구성3회 제안 표본으로 authoring/verification/healing/maintenance·시간·저장량·오판을 측정한 뒤 예산을 정한다.

제품 코드·샘플 기능·설치·실제 모델/기기 실행·DB 시험·배포는 이번 개정에서 수행하지 않는다. 기존 prototype 확인은 v0.5 모의 UI 근거로만 남긴다.
