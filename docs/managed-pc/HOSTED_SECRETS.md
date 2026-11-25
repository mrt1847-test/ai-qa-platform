# Hosted 비밀 설정과 참조 등록

HS-1 코드 계약, 2026-11-25. 대상 배치는 [Fly.io · Supabase · 워커 PC](../superpowers/specs/2026-11-20-render-supabase-worker-design.md)다. 이 문서는 배포 작업을 실행하지 않는다. Postgres 연결은 HS-2, Storage는 HS-3, 실제 Fly 설정/컨테이너/HTTPS는 HS-4에서 한다.

## 비밀의 소유 위치

| 프로필 | 모델/OIDC 원문 | 요청 영수증 보호키 |
|---|---|---|
| local | Windows Credential Manager | 기존 DB의 DPAPI 보호 envelope |
| hosted | 배포 플랫폼이 환경 변수로 주입 | 배포 플랫폼이 환경 변수로 주입한 고정 32-byte 키 |

hosted 기본 backend는 `EnvironmentSecretBackend`다. 테스트의 명시 backend 주입은 보존한다. 원문은 settings DTO·DB·백업 manifest·worker DTO에 추가하지 않는다. UI/API의 키 생성/교체는 `503 deployment_managed_secret`으로 거절한다. 환경 변수를 메모리에서 바꾸어 저장했다고 응답하지 않는다. 설정 페이지에서는 키 교체 선택을 숨기고 배포 관리 안내를 표시한다. 모델 연결의 이름/모델/역할과 key_ref는 기존 모델 binding API로 등록한다.

## 배포 환경 변수

`AIQA_HOSTED_SECRETS_JSON`은 아래와 같은 JSON object다. 예시의 `replace-...`는 형식 설명용이며 사용 가능한 키가 아니다. 실제 값은 플랫폼의 비밀 설정에서 주입하고 저장소·명령행 인수·채팅에 남기지 않는다.

```json
{
  "AIQA/aiqa-server/oidc/client_secret": "replace-with-idp-client-secret",
  "AIQA/aiqa-server/secret/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/1": "replace-with-model-key"
}
```

- account는 `AIQA_SECRET_ACCOUNT`와 정확히 일치한다(hosted 기본값 `aiqa-server`). 허용 account는 영문/숫자/`_.-`, 1~128자다.
- 모델 target의 project/ref는 소문자 표준 UUID, revision은 1~999999999다. 프로젝트·reference·revision을 모두 고정한다. 이름만으로 다른 프로젝트의 키를 찾지 않는다.
- 빈 값·비문자열·중복 JSON key·다른 account·잘못된 target·각 값 UTF-8 4096 bytes 초과를 거절한다. 전체 JSON은 256 KiB, 항목은 256개까지다. 설정 오류 메시지에 원문 JSON을 넣지 않는다.
- OIDC를 쓰지 않는 개발 fixture는 OIDC 항목을 생략할 수 있다. 설정된 OIDC secret이 없으면 로그인 runtime은 준비되지 않으며 liveness와 구별한다.
- 한 앱은 기동 시 환경 값을 snapshot으로 갖는다. 변경하려면 같은 배포 설정을 적용해 앱을 재시작한다. 모델 binding 변경은 별도로 명시 수행한다.

`AIQA_RECEIPT_HMAC_KEY`는 암호학적으로 생성한 **32 random bytes의 표준 base64**(44자)다. OIDC/모델 키와 별도이며 재시작·재배포·DB 복원에도 동일하게 보존한다. 값 생성/등록은 운영자가 배포 준비 시 수행한다. 예시 고정 키를 운영에 쓰지 않는다.

DB에는 키 원문 대신 version marker와 HMAC verifier만 저장한다. 키가 없거나 바뀌면 보호된 브라우저 변경/증거 upload는 `503 receipt_key_unavailable`로 실패하며 새 키를 만들거나 이전 영수증을 지우지 않는다. API health는 비밀 준비 상태를 뜻하지 않는다. 현재 자동 보호키 회전은 지원하지 않는다. 잘못된 키를 넣었다면 원래 배포 키를 복원한다.

로컬 DPAPI DB를 hosted로 열거나 hosted DB를 로컬 DPAPI로 여는 것은 거절한다. 기존 로컬 DB의 운영 이관은 이번 작업 범위가 아니다.

## 이미 배포한 모델 키의 metadata 등록

기존 hosted 프로젝트와 활성 `admin` 멤버가 준비되어 있어야 한다. 이 CLI는 프로젝트/사용자/권한을 만들거나 승격시키지 않는다. 서버 운영자만 서버의 승인된 환경에서 실행한다. 웹/worker에는 이 진입점을 열지 않는다.

```text
python -m aiqa.security.provision_hosted_secret --project-id <project-UUID> --actor-id <active-admin-UUID> --ref-id <ref-UUID> --revision 1 --name "녹화 모델 키"
```

키 원문 인수는 없다. 이미 배포된 exact target을 읽을 수 있는지 확인한 뒤 기존 `secret_refs`, audit, snapshot을 한 트랜잭션으로 남긴다. 출력은 project/ref/revision/availability뿐이다. 같은 revision/name의 재실행은 중복 기록을 만들지 않는다. admin 해제·다른 project·키 누락·건너뛴 revision·기존 이름 변경은 실패한다. 이름에는 키 원문을 쓰지 않는다.

등록된 ref는 인증된 기존 `GET /api/v1/projects/<project>/secret-refs`에서 선택 가능한 metadata로 보인다. 기존 `POST /api/v1/model-bindings`의 `key_ref`에 project/ref/revision을 연결한다. 모델의 endpoint/provider/role 등 기존 필수 필드는 유지한다. 이 단계는 모델 호출이 아니다. 기존 키 입력 폼을 통해 hosted 비밀 원문을 등록하지 않는다.

교체 시에는 기존 target을 보존한 채 같은 ref의 다음 revision을 배포하고, 같은 이름으로 CLI를 실행한 뒤 새 모델 binding revision에 연결한다. 과거 binding/승인본이 참조하는 revision의 키를 임의로 없애지 않는다. 삭제/폐기는 별도 운영 정책 작업이며 이 CLI는 수행하지 않는다.

## 검증 범위

합성 비밀·임시 DB·모의 IdP/ASGI로 import, account 분리, metadata 등록/회전, 브라우저 저장 및 재시작을 검사한다. Windows Credential Manager/DPAPI의 기존 로컬 회귀도 유지한다. Windows DLL을 제거한 자식 프로세스 검사는 이식성 회귀이며 실제 Linux/Fly 배포 성공으로 기록하지 않는다. 실제 Linux 컨테이너 기동/운영 IdP/배포 secret 재주입 수용은 HS-4의 남은 검증이다.
