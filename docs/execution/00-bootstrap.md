# 0 · 최소 실행 기반 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료4 / 4**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W00-01](#w00-01) | 없음 | 패키지·최소 의존성·lock·pytest 실행 기반 | complete |
| [W00-02](#w00-02) | [W00-01](00-bootstrap.md#w00-01) | FastAPI 앱 factory·설정·liveness API | complete |
| [W00-03](#w00-03) | [W00-02](00-bootstrap.md#w00-02) | Jinja2 기본 페이지·layout·static 연결 | complete |
| [W00-04](#w00-04) | [W00-03](00-bootstrap.md#w00-03) | 서버 시작·종료 smoke와 첫 실행 안내 | complete |

<a id="w00-01"></a>

## W00-01 — 패키지·최소 의존성·lock·pytest 실행 기반

- [x] **W00-01 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W00-01.md`.
- **직접 선행:** 없음. 기존 source/현재 코드만 확인.
- **읽기:** CONTRACTS C00 / C01 / C13 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R21.
- **검증 등급:** `bootstrap`. 환경: `local_python`.
- **변경 파일:** `pyproject.toml`, `requirements.lock`, `.gitignore`, `src/aiqa/__init__.py`, `tests/conftest.py`, `tests/unit/test_bootstrap.py`. 시험: `tests/unit/test_bootstrap.py`.
- **입출력 계약:** `distribution aiqa; import aiqa; python -m pytest tests/unit/test_bootstrap.py::test_w00_01`
- **구현·화면·예외:** 기존 src/aiqa·tests·공개 원본과 완료 근거를 읽고 재사용한다. Python 3.11 기준 src-layout editable 설치와 pytest 탐색을 구성한다. runtime은 FastAPI/Uvicorn/Jinja2, dev는 pytest/httpx에 필요한 최소 의존성만 고정하고 재현 가능한 requirements.lock(전체 전이 버전 constraints)을 만든다. SDK/VM/ADB/DB 서비스는 여기서 설치하지 않는다. tests/conftest.py의 기존 sys.path 보정은 editable import가 된 뒤 필요한 차이만 정리한다. lock 작성 도구/명령·Python/OS·재현 명령을 인계에 남긴다.
- **검증 전제:** 격리된 개발 환경에 python -m pip install -e ".[dev]" -c requirements.lock 후 pip check·pytest --collect-only를 확인한다. 저장소 밖 cwd에서 importlib.metadata.version('aiqa')와 import aiqa를 확인하고 기존 W01-01 시험도 선택 실행한다. W01-02는 차단 시험이므로 전체 suite green으로 위장하지 않는다.
- **작업 순서:** `test_w00_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/unit/test_bootstrap.py::test_w00_01 tests/integration/test_w01.py::test_w01_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "installed_import_outside_repo": True,
  "dependency_check_ok": True,
  "pytest_collects": True,
  "existing_w01_01_passes": True,
  "global_environment_required": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w00-02"></a>

## W00-02 — FastAPI 앱 factory·설정·liveness API

- [x] **W00-02 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W00-02.md`.
- **직접 선행:** [W00-01](00-bootstrap.md#w00-01)
- **읽기:** CONTRACTS C00 / C01 / C13 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R14, R26.
- **검증 등급:** `bootstrap`. 환경: `local_python`.
- **변경 파일:** `src/aiqa/api/__init__.py`, `src/aiqa/api/app.py`, `src/aiqa/config.py`, `tests/integration/test_bootstrap_http.py`. 시험: `tests/integration/test_bootstrap_http.py`.
- **입출력 계약:** `load_settings(env: Mapping[str,str] | None = None) -> AppSettings; create_app(settings: AppSettings | None = None) -> FastAPI; GET /api/v1/health -> {status:'ok',component:'api'}`
- **구현·화면·예외:** 공통 create_app factory 한 개와 AIQA_HOST(127.0.0.1 고정)/AIQA_PORT(기본8000)/runtime root 설정을 만든다. runtime root 기본은 LOCALAPPDATA/AIQA이며 import나 health 조회로 DB·기기·모델 client를 만들지 않는다. health는 API liveness만 뜻하고 엔진 준비/QA PASS가 아니다. 업무 mutation/가짜 project API는 만들지 않는다. W04는 이 factory에 실제 저장/인증을 확장하고 두 번째 앱을 만들지 않는다.
- **검증 전제:** 키/VM/ADB/DB 없이 factory 생성→실제 ASGI 요청 health200·올바른 body를 확인한다. 비루프백 host/잘못된 port 거부, 프로젝트 API 미구현404, 반복 factory 생성의 global 상태 누출과 외부 client 초기화0을 확인한다.
- **작업 순서:** `test_w00_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_bootstrap_http.py::test_w00_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "health_status": 200,
  "body": {
    "status": "ok",
    "component": "api"
  },
  "business_endpoint_status": 404,
  "external_clients_created": 0,
  "non_loopback_rejected": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w00-03"></a>

## W00-03 — Jinja2 기본 페이지·layout·static 연결

- [x] **W00-03 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W00-03.md`.
- **직접 선행:** [W00-02](00-bootstrap.md#w00-02)
- **읽기:** CONTRACTS C00 / C01 / C13 / C14 + 직접 선행 receipt의 interface/제약. 추적: R21, R26, R27.
- **검증 등급:** `bootstrap`. 환경: `local_python`.
- **변경 파일:** `src/aiqa/web/__init__.py`, `src/aiqa/web/routes.py`, `src/aiqa/web/templates/base.html`, `src/aiqa/web/templates/bootstrap.html`, `src/aiqa/web/static/app.css`, `src/aiqa/api/app.py`, `pyproject.toml`, `tests/acceptance/test_bootstrap_page.py`. 시험: `tests/acceptance/test_bootstrap_page.py`.
- **입출력 계약:** `GET / -> HTML bootstrap page; /static/app.css -> CSS; render_bootstrap(request: Request) -> Response`
- **구현·화면·예외:** 제품 서버가 Jinja2 기본 페이지와 CSS를 실제 제공하게 하고 package-data에 template/static을 포함한다. 화면은 AI QA 기본 실행 환경 안내와 실제 API liveness만 표시한다. 기기·모델·프로젝트·녹화·승인은 미구성으로 설명하고 가짜 성공/대시보드 숫자/작동하는 척하는 버튼을 넣지 않는다. prototype/localStorage 코드를 붙이지 않는다. W10이 이 layout을 확장한다.
- **검증 전제:** 저장소 root와 다른 cwd에서 /의 HTML/title과 /static/app.css의 status/content-type을 확인한다. API 오류가 있으면 연결 오류를 표시하며 녹화/PASS/승인 fake 값은 없어야 한다. 기본 페이지를 실제 browser로 열어 CSS 적용을 확인한다.
- **작업 순서:** `test_w00_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_bootstrap_page.py::test_w00_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "page_status": 200,
  "css_status": 200,
  "templates_work_outside_repo": True,
  "fake_business_results": 0,
  "browser_page_verified": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w00-04"></a>

## W00-04 — 서버 시작·종료 smoke와 첫 실행 안내

- [x] **W00-04 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W00-04.md`.
- **직접 선행:** [W00-03](00-bootstrap.md#w00-03)
- **읽기:** CONTRACTS C00 / C01 / C13 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R16, R21, R26.
- **검증 등급:** `bootstrap`. 환경: `local_python`.
- **변경 파일:** `tests/acceptance/test_bootstrap_startup.py`, `README.md`, `docs/validation/bootstrap.md`. 시험: `tests/acceptance/test_bootstrap_startup.py`.
- **입출력 계약:** `python -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000; BootstrapSmokeReport`
- **구현·화면·예외:** 격리 개발 환경에서 한 명령으로 서버 시작→실제 HTTP health/page/static 확인→종료/port 해제를 검증한다. 테스트는 빈 port를 명시해 관리하고 타 process를 이름으로 종료하지 않는다. README에 환경 준비·lock 설치·실행/중지·기본 검사·차단 live 시험 분리를 기록한다. 일상 launcher/process 관리 기능은 W12이며 여기서 중복 구현하지 않는다. DB/worker/에이전트/설치·배포 기능으로 확장하지 않는다.
- **검증 전제:** 저장소 밖 cwd에서 subprocess 서버를 시작해 loopback HTTP로 관찰하고 명시 종료 뒤 해당 port/process 해제를 확인한다. 새 bootstrap 검사들과 기존 W01-01을 선택 실행한다. 모델 키/VM/USB 없는 환경에서 실제 browser 진입을 확인하고 W01-02 차단 상태는 유지한다.
- **작업 순서:** `test_w00_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/unit/test_bootstrap.py tests/integration/test_bootstrap_http.py tests/acceptance/test_bootstrap_page.py tests/acceptance/test_bootstrap_startup.py tests/integration/test_w01.py::test_w01_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "real_http_health": True,
  "real_page_and_css": True,
  "owned_process_stopped": True,
  "port_released": True,
  "vm_or_api_key_required": False,
  "existing_block_preserved": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
