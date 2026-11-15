# AI QA

Web과 Android의 테스트를 자연어로 녹화하고, 저장된 동작을 반복 실행하는 QA 플랫폼입니다. 녹화 기록과 실행 결과를 축적하고, 사람이 단계별 증거를 검토한 뒤 테스트에 사용할 버전을 승인하는 것을 목표로 합니다.

**현재 개발 중입니다.** 로컬 구현·모의 포트 검사·실제 기기 시험의 범위가 다릅니다. 전체 진행도는 [WORK_PROGRESS.md](WORK_PROGRESS.md), 지금 수행할 작업은 [NEXT_ACTION.md](NEXT_ACTION.md)를 확인하세요.

## 기본 동작

1. **녹화 준비:** Web 또는 Android 실행 자원과 대상 앱/URL을 선택하고, 필요한 설정과 검증 목표를 입력합니다. TC 연결은 선택 사항이며 검증 목표와 녹화 기록은 자동화 케이스에서 함께 관리합니다.
2. **AI 녹화:** 에이전트가 화면을 보고 동작을 선택합니다. 각 단계의 동작·전후 스크린샷·로그를 저장합니다.
3. **저장 후 검토:** 녹화 완료 후 저장본을 검토합니다. 승인을 받아야 녹화 기록이 저장되는 방식이 아닙니다. 재녹화는 기존 승인본을 보존하면서 새 후보를 만듭니다.
4. **승인본 실행:** 저장된 코드나 물리 동작을 기반으로 재생합니다. 기본 동작 재생에는 AI를 호출하지 않고, 필요한 검증과 정책상 허용된 예외 처리에서만 호출합니다.
5. **결과 확인:** 단계별 증거와 실행 결과를 확인하고 이력을 비교합니다. 셀프힐링은 ON/OFF와 호출 한도를 따르며, 실행 여부가 불명확한 동작을 임의로 재전송하지 않습니다.

## 실행 구조

목표 구성은 웹 관리 서비스와 등록된 실행 PC를 분리하는 형태입니다. 초기 실행 자원은 현재 PC이며, 추가 PC나 클라우드 실행 자원으로 확장할 수 있도록 설계합니다.

- **관리 서버:** 웹 UI/API, 프로젝트·케이스·버전, 작업 큐, 승인, 결과와 증거를 관리합니다.
- **실행 PC의 worker:** 서버에서 작업을 받아 Android 드라이버 또는 Web 실행 환경을 제어하고 증거를 전송합니다.
- **접속 브라우저:** 사용자가 관리 화면을 이용합니다. 사이트를 연 PC의 기기 제어권을 자동으로 얻는 구조가 아닙니다.

실행 PC가 꺼져 있어도 **관리 서버가 가동 중이고 필요한 증거가 서버에 저장·ACK된 경우** 저장본 조회·검토·승인이 가능합니다. 재녹화와 테스트 실행은 실행 자원이 연결돼 있어야 가능합니다. 관리 서버까지 같은 PC에서 껐다면 관리 화면도 사용할 수 없습니다.

상세 기준은 [중앙 관리·실행 PC 설계](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md)를 따릅니다.

## 현재 구현 및 검증 범위

기준일: 2026-11-15 (Asia/Seoul). 최신 상태는 진행 문서와 각 작업의 검증 기록을 우선합니다.

| 영역 | 현재 확인된 범위 |
| --- | --- |
| 관리 기능 | 프로젝트·케이스·설정·녹화 검토·승인·실행·결과 관리 코드와 UI가 있습니다. 실제 실행 가능 여부는 대상 자원·권한·필수 증거에 따라 달라집니다. |
| Android / Mobile-Agent | 고정한 공개 원본 main에 Luna를 연결한 로컬 시험에서 4개 동작을 녹화하고, 저장본을 AI 호출 0회로 재생했습니다. 단계별 화면·동작·로그·사용량을 보존했습니다. |
| 정상 제품 경로 연결 | 서버 OpenAI 포트·권한·사용량 저장과 원본 main의 별도 프로세스 실행을 구현했습니다. 서버 소유 대화/이력, 일반 녹화 handler, 증거 ACK·승인까지의 원본 에이전트 연결은 진행 중입니다. |
| Web / CUAWright | 공개 코드와 어댑터, 격리 실행·녹화·재생 연결 코드 및 모의 포트 검사가 있습니다. 실제 지원 VM에서의 전체 흐름 수용은 별도입니다. |
| 운영 환경 | 독립 서버·TLS·인증·실행 자원·장애 상황·비용/처리량의 실환경 수용이 남아 있습니다. |

실제 Mobile-Agent 시험은 [AI-LIVE-03](docs/validation/tasks/AI-LIVE-03.md), 정상 서버/worker 연결의 남은 구현은 [연결 작업서](docs/managed-pc/MOBILE_AGENT_SERVER_WIRING_TASKS.md)를 참고하세요. 로컬 시험 결과를 웹에서의 전체 녹화·사람 승인 완료로 해석하지 않습니다.

## 기술 구성

- Python 3.11 이상, FastAPI, Uvicorn
- Jinja2 템플릿, CSS, JavaScript 기반 웹 UI
- SQLite 기반 관리 데이터와 파일 기반 증거 저장소
- HTTPX 기반 서버/worker·모델 통신
- Android ADB 및 고정 Mobile-Agent 원본, Web CUAWright 어댑터

의존성 선언은 [pyproject.toml](pyproject.toml), 버전 제약은 [requirements.lock](requirements.lock)에 있습니다. Android SDK/ADB, 에뮬레이터와 Web 실행 환경은 별도로 준비해야 합니다.

## 로컬 개발 빠른 시작

아래 명령은 **Windows PowerShell, 저장소 루트** 기준입니다. 기본 UI/API를 시작하는 절차이며 기기 연결이나 유료 모델 호출을 자동 설정하지 않습니다.

### 1. 가상환경과 의존성 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements.lock
.\.venv\Scripts\python.exe -m pip check
```

`dev`에는 테스트 도구와 Mobile-Agent 이미지 처리에 필요한 Pillow가 포함됩니다. 기존 가상환경이 있다면 재사용할 수 있습니다.

### 2. API/UI 실행

```powershell
.\.venv\Scripts\python.exe -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

| 주소 | 용도 |
| --- | --- |
| <http://127.0.0.1:8000/> | 기본 실행 환경과 API 상태 확인 |
| <http://127.0.0.1:8000/ui/projects> | 프로젝트 관리 진입점 |
| <http://127.0.0.1:8000/api/v1/health> | API liveness 확인 |

관리 기능은 프로젝트·세션·권한 설정을 따릅니다. health 응답 `{"status":"ok","component":"api"}`는 API 프로세스가 살아 있다는 의미이며, 기기·모델 준비나 테스트 합격을 뜻하지 않습니다.

이 명령은 API 프로세스만 시작합니다. 등록 worker와 기기/VM은 별도로 준비합니다. 로컬 launcher와 환경 설정은 [환경·launcher 작업서](docs/execution/04b-environments-and-launcher.md), 현재 구현 경계는 [RUNTIME_BOUNDARIES.md](docs/managed-pc/RUNTIME_BOUNDARIES.md)를 참고하세요.

직접 실행한 서버를 중지하려면 해당 터미널에서 **Ctrl+C**를 누릅니다.

### 3. 데이터와 설정

런타임 데이터의 기본 위치는 `%LOCALAPPDATA%\AIQA`입니다. 관리 기능이 이 위치의 DB·증거 저장소를 사용하며, 소스 저장소나 OneDrive 동기화 폴더에 런타임 DB를 두지 않는 구성을 사용합니다.

별도 위치가 필요하면 서버를 시작하기 전에 지정합니다.

```powershell
$env:AIQA_RUNTIME_ROOT = Join-Path $env:LOCALAPPDATA "AIQA-dev"
```

설정은 프로세스 환경변수에서 읽습니다. 저장소 루트에 `.env` 파일을 만드는 것만으로 서버 설정이 자동 적용되지는 않습니다. 전체 항목은 [src/aiqa/config.py](src/aiqa/config.py)를 참고하세요.

기본 모델 provider는 `fixture`입니다. UI/API 기본 확인에는 AI API 키가 필요하지 않습니다. 실제 모델 녹화에는 서버 측 비밀 저장소와 프로젝트 모델 binding·권한·가격 정책 설정이 필요합니다. 키 원문은 worker, 생성 코드, README 또는 Git에 넣지 않습니다. [모델 요청 설정](docs/managed-pc/MODEL_REQUEST_CONFIGURATION.md)과 최신 [MA01](docs/validation/tasks/AI-LIVE-04-MA01.md)·[MA02](docs/validation/tasks/AI-LIVE-04-MA02.md) 구현 기록을 함께 확인하세요.

## 검사

기본 API/페이지 검사는 다음과 같이 실행할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_bootstrap.py tests/integration/test_bootstrap_http.py tests/acceptance/test_bootstrap_page.py -q
```

전체 검사는 다음 명령을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -B -m pytest
```

기존 전체 회귀에는 [알려진 실패 기준선](docs/validation/tasks/REGRESSION_BASELINE_2026-11-09.md)이 있습니다. 모의 포트 검사를 실제 기기·유료 API·운영 환경 검증과 구분하고, 변경한 영역에 맞는 검사를 수행합니다. 검증 기록은 [docs/validation](docs/validation)에 남깁니다.

## 저장소 구조

```text
src/aiqa/
  api/          API와 인증·권한 진입점
  web/          UI 템플릿과 정적 파일
  domain/       케이스·승인 등 도메인 규칙
  store/        DB·작업 큐·증거 저장
  worker/       등록 실행 PC의 작업 처리
  adapters/     Mobile-Agent·CUAWright 연결
  recording/    녹화와 저장 원본 처리
  replay/       저장 동작·승인본 재생
  models/       모델 포트·권한·사용량
third_party/    고정 공개 원본·출처·라이선스
patches/        공개 코드 변경 관리
prototype/      초기 인터랙티브 샘플 UI
tests/         단위·통합·수용·웹 검사
tools/         개발·실제 시험 보조 도구
docs/          작업서·계약·검증 근거
```

`prototype/`은 초기 화면 검토용 모의 샘플입니다. 제품 UI는 `src/aiqa/web/`에 있으며, 샘플 실행 방법은 [prototype/README.md](prototype/README.md)에 있습니다.

## 문서 안내

| 알고 싶은 내용 | 문서 |
| --- | --- |
| 다음에 구현할 작업 | [NEXT_ACTION.md](NEXT_ACTION.md) |
| 전체 진행도와 남은 범위 | [WORK_PROGRESS.md](WORK_PROGRESS.md) |
| 작업 단위·개발 절차 | [docs/execution/README.md](docs/execution/README.md) |
| API·DB·승인·실행 공통 계약 | [CONTRACTS.md](docs/execution/CONTRACTS.md) |
| 현재 관리 서버/실행 PC 구조 | [중앙 관리·실행 PC 설계](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md) |
| UI·데이터·초기 기술 설계 | [UI_SPEC.md](UI_SPEC.md) · [DATA_DESIGN.md](DATA_DESIGN.md) · [DESIGN.md](DESIGN.md) |
| 공개 코드 조사 | [RESEARCH.md](RESEARCH.md) |
| 원본 에이전트 연결의 현재 작업 | [MOBILE_AGENT_SERVER_WIRING_TASKS.md](docs/managed-pc/MOBILE_AGENT_SERVER_WIRING_TASKS.md) |

개발을 이어갈 때는 `NEXT_ACTION.md`의 Current와 해당 작업 카드·필요한 계약부터 읽습니다. 전체 설계 문서와 과거 이력을 매번 모두 읽을 필요는 없습니다.

## 공개 코드와 라이선스

Mobile-Agent와 CUAWright의 사용 범위·고정 버전·변경점은 해당 출처 기록을 따릅니다. 저장소에 포함된 공개 코드의 라이선스는 각각의 파일을 확인하세요.

- Mobile-Agent: [연동 안내](third_party/mobile_agent/README.md), [원본 라이선스](third_party/mobile_agent/upstream/LICENSE)
- CUAWright: [공개 원본](third_party/cuawright/upstream/README.md), [변경 관리](patches/cuawright/README.md)
