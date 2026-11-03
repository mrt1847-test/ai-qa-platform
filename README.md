# AI QA

AI QA 플랫폼의 로컬 개발 실행 안내입니다. 서비스 목표는 [중앙 관리/저장과 등록 실행 PC의 분리](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md)이며, 현재 loopback 앱은 중앙 운영 서비스/클라우드 연동 완료 상태가 아닙니다. 여기서는 Python 패키지를 설치하고 API 프로세스를 켜고 끄는 방법만 다룹니다. VM, USB 기기, 모델 키, DB, 일상 launcher는 이 안내의 범위가 아닙니다.

## 환경

Python 3.11이 필요합니다. 저장소 안에 가상환경을 만들고 그 인터프리터로 설치합니다. Windows에서는 `.\.venv\Scripts\python.exe` 입니다.

```text
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements.lock
.\.venv\Scripts\python.exe -m pip check
```

`requirements.lock`은 전이 의존성 버전을 고정합니다. 이 lock에 VM, ADB, 모델 SDK는 없습니다.

가상환경을 이미 활성화했다면 설치 명령은 `python -m pip install -e ".[dev]" -c requirements.lock`과 같습니다. 이 작업에서 설치를 다시 수행한 것은 아닙니다.

## 실행

저장소 루트에서 다음 한 명령으로 API를 띄웁니다. 바인드는 `127.0.0.1`만 허용됩니다.

가상환경을 켠 뒤에는 같은 명령을 `python -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000`으로 실행할 수 있습니다.

```text
.\.venv\Scripts\python.exe -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000/`를 열면 실행 환경과 API liveness를 확인할 수 있습니다. 관리 화면은 `http://127.0.0.1:8000/ui/projects`입니다. 프로젝트·케이스·검증 정의·설정·선택 TC를 관리할 수 있으며, 실제 기기 녹화·모델 실행·사후 승인 전체 흐름은 후속 작업입니다. 구현 범위는 [진행표](WORK_PROGRESS.md)와 [계약 보완 결과](docs/validation/reviews/2026-11-01-remediation-result.md)를 따릅니다.

런타임 데이터의 기본 위치는 `%LOCALAPPDATA%\AIQA`입니다. 앱 factory·health·초기 liveness 화면은 DB를 열지 않고, 관리 기능에 접근하면 별도 runtime 디렉터리와 DB/migration을 사용합니다. Source의 OneDrive 폴더에 runtime DB를 두지 않습니다.

## 중지

서버를 띄운 터미널에서 Ctrl+C 로 그 프로세스만 종료합니다. 포트 `8000`은 그 프로세스가 끝난 뒤 풀립니다. 다른 프로세스를 이름으로 종료하지 않습니다. 프로세스 상주와 탭 재접속을 관리하는 launcher는 아직 없습니다.

## 기본 확인

- `GET /api/v1/health` 는 `{"status":"ok","component":"api"}` 입니다. API 프로세스가 살아 있다는 뜻이며 QA 합격이나 엔진 준비가 아닙니다.
- `GET /` 는 기본 실행 환경 HTML입니다.
- `GET /static/app.css` 는 CSS입니다.

## 검사와 막힌 live 시험

설치 확인과 bootstrap 검사는 선택해서 실행합니다.

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_bootstrap.py tests/integration/test_bootstrap_http.py tests/acceptance/test_bootstrap_page.py tests/acceptance/test_bootstrap_startup.py tests/integration/test_w01.py::test_w01_01 -q
```

이 검사가 통과해도 VM, USB, 모델 검증이 끝난 것은 아닙니다. `W01-02`는 기존 로컬 제공자의 script/driver 격리 검증 전까지 blocked로 보존합니다. 사용자 PC의 VM 준비는 cloud 서비스 사용의 선행이 아니며, cloud 배치는 서비스 측 별도 격리/연동 수용이 필요합니다. 그 시험을 지우거나 skip하거나 성공으로 바꿔 전체 suite를 녹색으로 만들지 않습니다.
