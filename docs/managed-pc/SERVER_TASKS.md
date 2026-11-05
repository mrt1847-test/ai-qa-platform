# 독립 관리 서버 구현 계획

> [경계와 공통 검증 규칙](RUNTIME_BOUNDARIES.md) · [직접 선행 및 환경 색인](IMPLEMENTATION_TASKS.json) · [공통 계약](../execution/CONTRACTS.md). NEXT_ACTION의 Current 절 하나만 실행한다. TDD로 실패 조건을 확인하고 기능을 연결한 뒤 같은 검사를 반복한다. 선행 인계와 구현의 필드명이 다르면 계약을 먼저 대조한다. 카드의 파일은 기존 파일과 생성 예정 파일을 함께 지정한다.

<a id="rx-16"></a>
## RX-16 · 관리 서버 프로필과 HTTPS 경계

**입력** PC-04 및 C00/C01/C11. **환경** `local_python`.

**파일** `src/aiqa/config.py`, `src/aiqa/launcher.py`, `src/aiqa/api/app.py`, `src/aiqa/api/auth.py`, `tests/integration/test_rx_16.py`.

- [x] 공개 HTTP·위조 Forwarded·불일치 Origin·개발 nonce를 거절하고 Secure cookie·CSRF를 유지한다. 서버는 워커 DB 접근 권한을 열지 않는다.
- [x] server 프로필을 별도 진입점으로 열고 reverse proxy의 명시된 신뢰 주소와 public origin을 검사한다. 개발용 loopback 로그인과 bootstrap nonce는 hosted 프로필에서 차단한다.
- [x] `python -m pytest -q tests/integration/test_rx_16.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-16.md`에 검증 등급·명령·결과와 프로필 설정·trusted proxy·cookie 계약를 남긴다.

<a id="rx-17"></a>
## RX-17 · 관리 서버 로그인과 프로젝트 권한

**입력** RX-16 및 C00/C01/C08/C11. **환경** `local_python`.

**파일** `src/aiqa/api/auth.py`, `src/aiqa/domain/projects.py`, `src/aiqa/web/routes.py`, `src/aiqa/security/oidc.py`, `tests/integration/test_rx_17.py`.

- [x] state/nonce/issuer/audience·재사용 code·교차 프로젝트 UUID·권한 회수 후 조회와 승인 거절. 테스트 IdP fixture 사용.
- [x] OIDC authorization code+PKCE 로그인으로 issuer/subject를 로컬 사용자에 연결한다. API와 UI의 프로젝트 조회·증거 다운로드·승인·워커 관리에서 저장된 membership 및 역할을 검사한다.
- [x] `python -m pytest -q tests/integration/test_rx_17.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-17.md`에 검증 등급·명령·결과와 인증 콜백·멤버십과 역할별 route 표를 남긴다.

<a id="rx-18"></a>
## RX-18 · 서버 영속 artifact와 조회 권한

**입력** RX-16 및 C00/C01/C03/C05/C08. **환경** `local_python`.

**파일** `src/aiqa/store/artifacts.py`, `src/aiqa/store/artifact_ingest.py`, `src/aiqa/api/artifacts.py`, `src/aiqa/config.py`, `tests/integration/test_rx_18.py`.

- [x] 중간 파일·해시 불일치·경로 탈출·타 프로젝트 읽기 거절, 서버 재시작 후 바이트와 digest 동일.
- [x] API 소유 영속 디스크에 digest 검증을 마친 바이트를 원자적으로 게시한다. worker PC가 없어도 프로젝트 권한을 검사해 다운로드한다.
- [x] `python -m pytest -q tests/integration/test_rx_18.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-18.md`에 검증 등급·명령·결과와 디스크 레이아웃·commit 순서·보존 책임를 남긴다.

<a id="rx-19"></a>
## RX-19 · 서버 전용 비밀 해석

**입력** RX-16 및 C00/C01/C06. **환경** `local_python`.

**파일** `src/aiqa/security/secrets.py`, `src/aiqa/config.py`, `src/aiqa/api/app.py`, `tests/integration/test_rx_19.py`.

- [x] 다른 계정·없는 참조·키 교체 시 안전한 실패, worker DTO와 로그·백업에서 원문 0건. 실제 서비스 재부팅은 RX-21.
- [x] 관리 서버 서비스 계정용 secret resolver를 서버 프로필에 주입한다. 초기 Windows Credential Manager 사용을 검증하고 DB와 백업에는 참조만 둔다.
- [x] `python -m pytest -q tests/integration/test_rx_19.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-19.md`에 검증 등급·명령·결과와 서비스 계정 조건·회전·로그 실패 방식를 남긴다.

<a id="rx-20"></a>
## RX-20 · DB와 artifact 백업·복원

**입력** RX-17 · RX-18 · RX-19 및 C00/C01/C03/C08/C10. **환경** `local_python`.

**파일** `src/aiqa/store/backup.py`, `src/aiqa/api/backups.py`, `src/aiqa/config.py`, `tests/integration/test_rx_20.py`.

- [x] 누락 blob·깨진 DB·중단 backup·다른 store 복원 거절. 복원된 저장본 승인 가능, 오래된 worker의 자동 실행 0회.
- [x] 서버 SQLite 일관 snapshot과 artifact manifest를 한 세대로 묶고 복원 전 무결성을 확인한다. 격리 경로에서 검증한 뒤 활성화하고 worker presence와 실행 lease는 기존 안전 계약대로 초기화한다.
- [x] `python -m pytest -q tests/integration/test_rx_20.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-20.md`에 검증 등급·명령·결과와 백업 세대·복원 순서·복구 전환 절차를 남긴다.

<a id="rx-21"></a>
## RX-21 · 별도 관리 호스트 수용

**입력** RX-08 · RX-20 · RX-28 · RX-37 · RX-41 · RX-59 및 C00/C01/C03/C04/C08. **환경** `local_python` · `independent_server` · `tls_domain` · `oidc_tenant` · `second_client` · `deployment_authorized`.

**파일** `docs/managed-pc/HOST_RUNBOOK.md`, `docs/validation/tasks/RX-21.md`.

- [ ] CA 실패·멤버십 없는 계정·worker의 관리 DB 접근 거절, 서비스 재부팅 뒤 credential 해석·저장본 조회·격리 restore 성공.
- [ ] 승인된 독립 관리 호스트에서 별도 서비스 계정으로 API·DB·artifact·HTTPS·OIDC를 구동한다. worker 등록/폐기와 별도 운영 세션의 로그인/로그아웃을 확인한다. worker는 outbound로 연결하고 다른 접속 PC는 브라우저로 로그인한다.
- [ ] `Test-NetConnection <관리 DNS> -Port 443`, `curl.exe --fail --proto =https https://<관리 DNS>/api/v1/health`, 브라우저 로그인과 복구 runbook을 실행한다.
- [ ] `docs/validation/tasks/RX-21.md`에 검증 등급·명령·결과와 설정 이름만 기록한 runbook·복원과 재기동 증거를 남긴다.

<a id="rx-28"></a>
## RX-28 · 실행 PC 등록과 폐기 화면

**입력** RX-02 · RX-17 · PC-03 및 C00/C01/C03/C11. **환경** `local_python` · `local_browser`.

**파일** `src/aiqa/web/routes.py`, `src/aiqa/web/templates/environments.html`, `src/aiqa/web/static/pc_availability.js`, `src/aiqa/api/resources.py`, `tests/acceptance/test_rx_28.py`.

- [x] 비관리자는 제어 없음, 키보드 발급/취소/폐기, 만료·오류·offline에서 입력 보존, 폐기 직후 실행 버튼 비활성 및 API 차단.
- [x] 프로젝트 권한이 있는 사용자에게 등록 코드 발급·복사와 worker 폐기 확인을 제공한다. PC 상태와 저장 관찰을 유지하고 접속 PC에 설치가 필요한 것처럼 표현하지 않는다.
- [x] `python -m pytest -q tests/acceptance/test_rx_28.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-28.md`에 검증 등급·명령·결과와 등록 흐름 UI 캡처·권한·오류 화면를 남긴다.
