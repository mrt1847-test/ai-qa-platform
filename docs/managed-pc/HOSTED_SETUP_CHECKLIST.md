# Fly.io 배포를 시작할 때 사용자가 할 일

2026-11-27. 코드 구현 현황은 [WORK_PROGRESS](../../WORK_PROGRESS.md), 실행 순서는 [NEXT_ACTION](../../NEXT_ACTION.md)에서 관리한다. 이 문서는 계정과 실제 환경을 준비하는 체크리스트다. 상세 명령은 [Fly 운영 절차](FLY_HOSTED_RUNBOOK.md)의 순서대로 실행한다.

## 1. 먼저 준비할 세 가지

- [ ] **Supabase 프로젝트:** 새 hosted 데이터용 프로젝트를 만든다. Connect에서 직접 연결 또는 **session pooler** URL을 준비한다. transaction pooler는 지원하지 않는다. 비밀번호의 예약 문자는 URL encoding하고 TLS를 사용한다. 기존 로컬 DB는 올리지 않는다.
- [ ] **비공개 Storage bucket:** 같은 Supabase 프로젝트에 `private-evidence`를 private으로 만든다. 서버용 secret key 또는 legacy service_role key를 준비한다. 브라우저용 publishable/anon key를 사용하지 않는다. 업로드 MIME은 `application/octet-stream`, 파일 크기 정책은 사용할 증거/APK 크기에 맞춘다.
- [ ] **Fly.io와 OIDC:** Fly 조직/앱을 준비하고, 로그인 제공자에 confidential OIDC 앱을 등록한다. RS256 ID token, authorization-code+PKCE, `client_secret_post`가 필요하다. callback은 `https://<app>.fly.dev/api/v1/auth/oidc/callback`이다. client ID, issuer, authorize/token endpoint, client secret, 본인의 검증된 `sub`를 준비한다. 이메일을 `sub`로 추측하지 않는다.

값은 채팅이나 저장소에 보내지 않는다. PowerShell 7.1 이상의 마스킹 입력과 권한 제한 파일을 만드는 명령이 운영 절차 1절에 있다. 고정 receipt 보호키도 그 절차에서 최초 한 번 생성하고 보관한다.

## 2. 서버 배포

- [ ] Fly CLI를 설치하고 로그인한다. **Docker 문법을 먼저 학습할 필요는 없다.** 제공된 Dockerfile을 사용한다. 로컬 Docker가 있으면 Linux smoke 검사를 실행하고, 없으면 Fly 원격 빌드/배포에서 실제 Linux 검사를 수행한다. 현재 개발 PC에서는 실제 Linux 빌드를 검증하지 않았다.
- [ ] `fly.toml.example`과 `deploy/fly-proxy-probe.toml.example`을 복사한다. 앱/지역을 동일하게 하고 정상 설정에 공개 origin과 OIDC 정보를 채운다.
- [ ] **새 앱에 비밀을 넣기 전에** 비밀 없는 proxy 관찰 배포를 실행한다. 외부 HTTPS 요청과 대응하는 실제 socket peer를 확인해 정상 설정의 trusted proxies에 정확한 IP로 넣는다. 추측한 IP나 넓은 subnet을 넣지 않는다. 중단하면 진단 머신을 정지한다.
- [ ] 운영 절차의 stdin import로 비밀을 stage한 뒤 **정상 fly.toml**을 배포한다. 머신 하나와 자동 정지 OFF를 확인한다. TCP health 통과만으로 로그인/녹화 성공으로 판정하지 않는다.
- [ ] 서버 shell에서 `aiqa.hosted.preflight`, `aiqa.hosted.bootstrap`을 실행한다. 본인의 검증된 OIDC `sub`로 첫 프로젝트·admin을 만든다. 출력 UUID를 보관하고 실제 브라우저 로그인을 확인한다.

전체 Docker 환경 파일 예시는 [deploy/hosted.env.example](../../deploy/hosted.env.example), Fly 비밀 5줄 파일 생성은 운영 절차 1절이다. 두 파일은 목적이 다르며 자동으로 읽히지 않는다. DB 자세한 조건은 [POSTGRES_STORE](POSTGRES_STORE.md)를 따른다.

## 3. 모델과 현재 PC 워커

- [ ] 첫 프로젝트 UUID를 받은 뒤 [HOSTED_SECRETS](HOSTED_SECRETS.md)에 따라 모델 키를 서버 비밀에 추가하고 metadata를 등록한다. 설정 화면에서 **등록된 키 참조**로 authoring 모델을 연결한다. 기존 OIDC 항목·receipt 키·기존 revision은 보존한다. 실제 모델 호출 전에는 비용이 발생하지 않는다.
- [ ] 현재 PC의 Android SDK/AVD를 준비하고 emulator를 켠다. `adb devices`로 serial을 확인한다. 운영 절차 4절대로 worker용 가상환경과 환경 변수를 설정한다. DB/Storage/모델 원문 키를 worker에 넣지 않는다.
- [ ] 로그인한 admin이 목적별 일회용 enrollment code를 발급하고 PC에서 교환한다. `deploy/run-worker.ps1`로 실행한다. 코드와 token은 로그/채팅에 출력하지 않는다. 기본 token 만료는 24시간이므로 만료 후 재등록한다.

## 4. 실제 사용 확인

- [ ] 다른 네트워크 브라우저에서 로그인하고, 작은 AI 녹화의 동작별 PNG/로그가 서버에 저장되는지 확인한다. 저장 후 사람이 검토·승인해 테스트용으로 승격한다.
- [ ] 같은 승인 package를 healing OFF로 재생하고 actor 모델 호출 0을 확인한다. 검증/예외 healing 호출은 별도 정책이다.
- [ ] worker PC를 끄고 서버 캐시가 사라진 재시작에서도 이미 ACK된 녹화·근거 검토와 승인이 되는지 확인한다. 새 녹화/재생은 막혀야 한다. 재연결만으로 중단 동작을 자동 실행하지 않는다.
- [ ] 실제 환경·시각·결과를 HS-4/5/6 인계에 기록한다. Supabase DB와 Storage의 backup/복원 정책도 운영 전에 정한다. 기존 SQLite archive는 hosted backup을 제공하지 않는다.

계정 준비 뒤 재개할 작업은 **HS-4 실제 Linux/Fly/OIDC 수용 → HS-5 PC 등록 → HS-6 실제 녹화·승인·재생·PC offline 수용**이다. 이미 구현된 Postgres/Storage/entry 코드를 다시 만드는 순서가 아니다.
