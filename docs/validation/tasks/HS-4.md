# HS-4 Fly·OIDC 인계

- 코드 상태: **complete — 계정 없이 준비할 코드/설정/모의 통합**.
- 실환경 상태: **not_started — 실제 Linux 이미지 빌드, Fly 배포, 운영 IdP/DB/Storage 접속 미실행**.
- 기준: master `3525226`; [구현 계획](../../superpowers/plans/2026-11-25-hosted-runtime.md), [운영 절차](../../managed-pc/FLY_HOSTED_RUNBOOK.md), [사용자 체크리스트](../../managed-pc/HOSTED_SETUP_CHECKLIST.md).

## 제공 interface

`python -m aiqa.hosted.preflight`는 설정 이름만으로 오류를 보고하고 오프라인 검사만 한다. hosted entry는 Postgres/private Storage/고정 receipt key/OIDC/TLS/승인 proxy를 요구한다. 실제 migration과 기존 queue reconciliation 후 API 한 프로세스를 `0.0.0.0:8000`에 실행한다. Windows launcher/worker는 시작하지 않는다. 알 수 없는 이전 runner는 lost/quarantine을 유지하고 native 동작을 자동 재실행하지 않는다.

Dockerfile은 Python3.12 slim/nonroot이며 runtime data/비밀을 build context에서 제외한다. 서버에서 필요한 pinned Mobile-Agent protocol 원본과 manifest/license만 포함한다. Fly manifest는 머신 하나/자동정지 OFF, TCP liveness, Uvicorn의 별도 proxy 처리를 OFF로 둔다. 비밀 없는 `proxy_probe`와 별도 manifest는 새 앱의 실제 socket peer를 관찰하기 위한 진단이다. 정상 API의 HTTPS gate를 열지 않는다. 관찰 뒤 정상 config로 교체하고 exact peer를 설정한다.

OIDC는 실제 discovery/code exchange/JWKS/RS256 ID token 검증을 한다. PKCE·nonce·issuer/audience/azp/시간/알고리즘을 검증하고 browser-bound Secure state cookie로 다른 브라우저의 state 복사를 거절한다. HTTP/JWT 작업 중 SQL writer/event loop를 점유하지 않는다. finalize에서 state/nonce/권한/만료를 다시 확인한다. 모의 IdP injection은 테스트용으로 유지하며 운영 인증을 모의 HMAC으로 통과시키지 않는다.

`aiqa.hosted.bootstrap`은 서버 shell에서 첫 프로젝트/admin/검증된 OIDC subject를 원자적으로 생성한다. 재시도는 멱등이며 기존 identity/admin을 덮어쓰지 않는다. 추가 구성원 관리 UI/CLI는 아직 제공하지 않는다. hosted 설정 화면은 배포된 모델 키의 참조만 연결하고 원문 write는 거절한다.

## 검사와 검토 범위

`test_hs4_hosted_runtime.py`, `test_hs4_oidc_browser.py`, `test_hs4_oidc_jwt.py`, `test_hosted_portability.py`와 기존 RX16/17/37/41/59를 사용했다. 합성 RSA IdP/ASGI, first-admin rollback, worker env, 제한 peer 관찰, protocol packaging, slow IdP 중 heartbeat/독립 writer, copied-state GET/POST 거절, finalize 중 권한 변경을 확인했다. 이전 집중 실행은 86 passed; 통합 회귀 최종 집계는 구현 계획 ledger에 기록한다.

fresh review에서 Linux winreg import, OIDC browser correlation/느린 HTTP, endpoint trailing slash, hosted dependency, worker allowlist와 모델 TLS 설정 결함을 수정했다. Windows registry/DLL을 숨긴 자식 검사와 정적 Docker/source 검사는 **실제 Linux 이미지 빌드가 아니다**. 이 PC에는 Docker/설치된 WSL 배포판이 없어 runbook에 재현 명령을 남겼다. 실제 계정/키/유료 호출은 사용하지 않았다.

패키지 검사: isolated build tool로 `pip wheel --no-deps --no-build-isolation`을 실행했고, 생성 wheel에 SQL/JSON snapshot, hosted entry/OIDC 모듈, settings template/JS가 들어 있음을 확인했다. 이는 Linux 이미지 빌드/실제 cloud boot 검사와 별개다.

## 정확한 재개 조건

사용자가 Fly/Supabase/OIDC 계정을 준비하면 runbook 1→2a→2b→3절을 진행한다. 실제 Linux import/protocol load, Postgres TLS/role, private bucket, observed proxy의 HTTPS, 운영 callback/Secure cookie를 확인해 이 파일에 환경·시각·증거를 추가한다. 단위 검사나 TCP health를 이 수용의 PASS로 바꾸지 않는다. HS-2/3/4 코드를 다시 구현할 필요는 없다.
