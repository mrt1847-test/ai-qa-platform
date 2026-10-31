# Bootstrap smoke

최소 API 프로세스의 시작과 종료 기록입니다. 네이티브 엔진, VM, USB, 모델 검증이 아닙니다.

## 명령

격리된 Python 3.11 환경에서 lock을 설치한 뒤, 서버는 이 프로세스 하나로 띄웁니다.

```text
python -m pip install -e ".[dev]" -c requirements.lock
python -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

시험은 빈 포트를 직접 고르고, 저장소 밖 cwd에서 같은 factory 명령을 실행합니다. 종료는 그 프로세스 핸들만 대상으로 하며 다른 프로세스를 이름으로 끝내지 않습니다. 종료 뒤 같은 포트에 다시 bind 되면 포트가 풀린 것입니다.

브라우저 진입은 그 loopback URL의 기본 페이지를 실제 브라우저로 여는 것입니다.

## BootstrapSmokeReport

| 필드 | 의미 |
|---|---|
| real_http_health | `GET /api/v1/health`가 200이고 `status`는 `ok`, `component`는 `api` |
| real_page_and_css | `GET /` HTML·title과 `GET /static/app.css`의 `text/css`, 그리고 실제 브라우저 DOM의 title |
| owned_process_stopped | 시험이 띄운 프로세스만 종료되고 더 이상 실행 중이 아님 |
| port_released | 그 포트에 다시 bind 할 수 있음 |
| vm_or_api_key_required | 이 smoke가 VM이나 모델 키를 요구하면 true. 최소 서버는 false |
| existing_block_preserved | `W01-02` 시험과 blocked 인계가 그대로이고 skip으로 바뀌지 않음 |

통과해도 `W01-02` live gate는 열리지 않습니다. 합성 fixture를 이 서버의 성공으로 기록하지 않습니다.

2026-11-01 00:03경 +09:00에 저장소 `.venv`의 Python 3.11.9로 bootstrap 검사 5건이 통과했다. 모델 키 없이 loopback 서버를 띄워 health, 페이지, CSS와 Chrome headless DOM, IDE 브라우저 진입을 확인한 뒤 그 프로세스만 종료하고 포트를 다시 bind 했다.
