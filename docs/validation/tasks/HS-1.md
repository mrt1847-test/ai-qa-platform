# HS-1 구현 인계

- 상태: complete (`core_contract` 코드/모의 통합 범위; 실제 hosted 배포 수용은 미실행)
- 기준 revision: `master e0c9aa8`. 기존 master worktree 사용; OneDrive의 다른 브랜치는 변경하지 않았다.
- 적용 계약: [Fly.io · Supabase · 워커 PC](../../superpowers/specs/2026-11-20-render-supabase-worker-design.md)의 HS-1. [세부 계획](../../superpowers/plans/2026-11-25-hosted-secrets.md), [운영 설정](../../managed-pc/HOSTED_SECRETS.md).

## 제공 interface와 실제 배선

- `aiqa.security.environment_secrets.EnvironmentSecretBackend(account, *, environ=None)`: `AIQA_HOSTED_SECRETS_JSON`의 exact account/project/ref/revision만 읽는다. 중복·잘못된 target/크기/값은 비밀을 포함하지 않는 오류로 거절한다. write/delete는 거절하며 환경을 수정하지 않는다.
- `build_server_secret_resolver(settings, backend=None)`: 기본 hosted는 위 backend, local은 Windows Credential Manager, 명시 테스트 backend는 그대로 사용한다. Windows DLL은 local backend를 실제로 사용할 때만 불러온다.
- `ServerSecretResolver.register_deployment_ref(actor, ref, name)`: 활성 프로젝트의 기존 admin만 이미 배포된 모델 키의 metadata를 등록한다. 같은 revision/name은 멱등이며 다음 revision만 회전한다. 구 ref는 보존한다. SQL에 원문은 저장하지 않는다.
- `python -m aiqa.security.provision_hosted_secret`: 서버 운영자 CLI. project/actor/ref/revision/name만 argv로 받는다. 기존 DB/membership를 사용하며 프로젝트·권한을 만들지 않는다. 기존 model binding API의 key_ref로 연결할 수 있다.
- `EnvironmentReceiptKey`와 `protected_body_digest(..., key_provider=...)`: hosted 앱마다 snapshot으로 주입한다. `StorageConfig`를 통해 browser mutation과 worker artifact upload에 연결했다. DB에는 marker/HMAC verifier만 넣고 키는 배포 설정에 둔다. local DPAPI 유지. 키 누락/교체/프로필 혼용은 새 키 생성 없이 거부한다.
- `secret_refs`와 프로젝트 settings 키 쓰기는 해당 앱의 resolver를 사용한다. hosted read-only 요청은 고정 `503 deployment_managed_secret`; 영수증 보호키 문제는 `503 receipt_key_unavailable`이다. 오류에 원문을 포함하지 않는다.
- local worker launcher는 두 hosted 비밀 환경 변수를 자식 환경에서 제거한다. 요청 rollback은 쓰기에 사용한 backend/account를 capture하여 해당 키를 정리한다.

DB migration 없음. 기존 secret ref/audit/snapshot 및 browser receipt key 표를 사용한다. 기존 로컬 DB의 운영 이관·초기화 없음.

## 검증과 검토

새 테스트: `tests/integration/test_hs1_hosted_secrets.py`, `test_hs1_receipt_keys.py`, `test_hs1_provisioning.py`. 합성 비밀·임시 DB·모의 IdP만 사용했다. provider/import RED 12개, receipt RED 8개, provisioning RED 7개를 확인한 뒤 구현했다. 실제 ASGI OIDC→model binding→저장→앱 재시작→같은 receipt 재사용→다른 body 409→hosted 키 입력 거절도 확인했다.

최종 fresh review에서 rollback context와 worker 자식 환경의 두 결함을 발견했다. 각각 먼저 실패 테스트로 재현하고 수정했다. 기존 settings UI 회귀의 AI0 안내 문구는 BASE에도 누락되어 있어 정책 설명을 복원했다. 기존 assertion을 약화하지 않았다.

최종 집중 회귀 명령:

```text
python -B -m pytest tests/integration/test_hs1_hosted_secrets.py tests/integration/test_hs1_receipt_keys.py tests/integration/test_hs1_provisioning.py tests/integration/test_ux_asset_save_receipts.py tests/integration/test_rx_19.py tests/integration/test_rx_37.py tests/integration/test_rx_11.py tests/integration/test_ma01_openai_factory.py tests/integration/test_ma04_engine_authority.py tests/acceptance/test_review_ui.py tests/integration/test_rx87_evidence_io.py tests/acceptance/test_ux_model_settings.py tests/acceptance/test_ux_secret_choices.py tests/integration/test_w04.py -q -p no:cacheprovider --tb=short
node --test tests/web/settings_editor.test.cjs
git diff --check
```

2026-11-25 최종 결과: **111 passed in 54.37s**, exit 0. JS **1 passed**, exit 0. `git diff --check` exit 0. 로그 `.review-work/hosted-secrets/pytest-final.log`(git ignored). 최종 검토 두 결함의 RED→GREEN을 포함한다.

실행은 master worktree의 `src`를 PYTHONPATH로 명시하고 기존 Python 가상환경을 재사용했다. 패키지를 설치하지 않았다. 첫 sandbox 실행은 Windows asyncio 내부 socketpair에서 정지했고 faulthandler로 위치를 확인했다. 해당 검사만 sandbox 밖에서 재실행했다. 전체 저장소 회귀를 실행하거나 기존 여섯 실패를 완료로 바꾸지 않았다.

## 검증 등급과 남은 범위

- 등급: `core_contract` + 모의 ASGI 통합. 실제 모델/IdP/배포 호출 0, 실제 API 키 조회 없음.
- Windows DLL 제거 자식 프로세스에서 앱 import/create/health를 확인했다. 실제 Linux 런타임 수용은 아니다. 이 PC에 Docker/설치된 WSL 배포판이 없어 Linux 컨테이너와 hosted boot/job reconciliation은 HS-4에 남긴다.
- 설정 화면은 실제 ASGI 렌더 결과와 기존 JS 단위 검사로 확인했다. 별도 브라우저 시각/키보드 수용은 수행하지 않았다.
- 모델·OIDC 비밀의 배포 저장과 기존 DB 참조 배선을 구현했다. 아직 관리 데이터는 SQLite, 증거 파일은 local artifact root다. hosted 운영 준비 완료로 해석하지 않는다.
- 다음 준비 카드: HS-2 Postgres 관리 데이터. HS-3 Storage, HS-4 실제 Linux/Fly/OIDC, HS-5/6 독립 worker/브라우저 수용은 각각 남는다. CLI actor-id의 신뢰 경계는 서버 운영자 접근이며 HTTP 인증을 새로 만든 것이 아니다.
- 보존: 녹화 저장 후 사람 승인, 기존 승인본 보존, 기본 replay AI0/healing OFF, 서버 원문 비밀의 worker 전송 금지. 이 카드에서 녹화/재생 엔진 동작은 바꾸지 않았다.
