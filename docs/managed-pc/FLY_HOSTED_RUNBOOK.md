# Fly 서버와 Android 워커 준비

2026-11-25. 이 파일의 명령은 운영자가 계정·키를 준비한 뒤 직접 실행하는 절차다. 이번 구현에서 계정 생성, 배포, 유료 호출은 하지 않았다. Docker/WSL 배포판이 없는 Windows 환경에서는 Linux 이미지 빌드 성공으로 기록하지 않는다. `preflight` 성공은 설정의 오프라인 검사이며 DB 접속·private bucket 정책·로그인·녹화 성공이 아니다.

서버는 API만 실행한다. 단일 Fly 머신은 유휴 시간에도 켜 두고, 상태는 Postgres와 private Storage에 둔다. `/tmp/aiqa`는 지워도 되는 캐시다. 기존 로컬 SQLite/DPAPI DB를 복사하거나 초기화하지 않는다. 워커는 서버로 HTTPS 연결만 열며 집 라우터의 포트를 열지 않는다.

## 현재 수용 전제

HS-2 Postgres와 HS-3 원격 artifact 배선을 함께 포함해야 한다. `AIQA_DATABASE_URL`이 없거나 TLS가 꺼져 있거나 `AIQA_ARTIFACT_BACKEND`가 `supabase`가 아니면 hosted entry가 시작을 거절한다. 기존 `aiqa.launcher start` 대신 `python -m aiqa.hosted.entry`를 쓴다. Uvicorn은 `0.0.0.0:8000`에 API 한 프로세스를 띄우며 자체 forwarded-header 처리를 끈다. 기존 HTTPS middleware가 실제 연결 peer와 `X-Forwarded-Proto: https`를 확인한다.

OIDC는 표준 authorization-code+PKCE, **RS256 ID token과 `client_secret_post`**를 지원한다. IdP에서 confidential client의 인증 방식을 `client_secret_post`로 등록하고 metadata에 이를 광고해야 한다. issuer discovery의 issuer/token endpoint가 설정과 정확히 같아야 하며 JWKS 주소는 승인된 issuer metadata에서만 읽는다. issuer 끝의 `/`도 보존한다. ID token audience는 client ID와 설정 audience를 포함해야 하며 미승인 추가 audience는 거절한다. 보통 ID token의 audience인 client ID를 두 설정에 동일하게 쓴다. nonce는 로그인 DB 상태와 대조한다. 서명 알고리즘을 토큰에서 선택하거나 JWT 검증을 해제하지 않는다. JWKS는 최대 32개/300초 캐시, unknown-kid 강제 갱신은 10초 간격으로 제한한다. 인증 응답은 256 KiB/토큰은 64 KiB로 제한하고 모든 HTTP는 TLS 확인·redirect 금지·10초 timeout을 쓴다. 실제 IdP 호환성은 배포 수용에서 확인한다. [OIDC Core ID Token Validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation), [PyJWT verification guidance](https://pyjwt.readthedocs.io/en/stable/api.html#jwt.decode) 기준이다.

## 1. 사용자 계정과 비밀

1. Fly.io 조직/앱, Supabase 프로젝트, 승인된 OIDC 앱을 준비한다. 하나의 유료 상시 Fly 머신을 선택한다. 자동 결제·구매·배포는 이 작업에서 하지 않았다.
2. Supabase의 새 운영 Postgres 연결 문자열과 private bucket `private-evidence`를 준비한다. DB TLS를 활성화하고 가능하면 `sslmode=verify-full` 및 올바른 신뢰 CA를 사용한다. 기존 로컬 DB는 옮기지 않는다. bucket 공개 접근은 끄고 서버 service key만 접근시킨다.
3. OIDC callback을 `https://<app>.fly.dev/api/v1/auth/oidc/callback`으로 등록한다. 운영자 계정의 정확한 issuer와 `sub`를 IdP 관리자 화면/검증된 토큰에서 확인한다. 이메일을 `sub`로 추측하지 않는다.
4. [HOSTED_SECRETS](HOSTED_SECRETS.md)의 방식으로 `AIQA_HOSTED_SECRETS_JSON`의 OIDC 항목과 고정 `AIQA_RECEIPT_HMAC_KEY`를 준비한다. receipt 키는 32 random bytes의 표준 base64이며 재배포/복원 때 보존한다. 모델 키 target은 첫 프로젝트 UUID를 받은 뒤 추가한다.

Fly secrets에 넣을 이름은 `AIQA_DATABASE_URL`, `AIQA_SUPABASE_URL`, `AIQA_SUPABASE_SERVICE_KEY`, `AIQA_HOSTED_SECRETS_JSON`, `AIQA_RECEIPT_HMAC_KEY`다. 값은 이미지, Docker ARG/ENV, fly.toml, 저장소, argv, 채팅, shell history에 쓰지 않는다. **아직 import/stage하지 않는다. 먼저 2절의 비밀 없는 proxy 관찰 배포를 완료한다.**

PowerShell 7.1 이상에서 아래는 저장소 밖의 권한 제한 폴더에 첫 비밀 파일을 실제로 만든다. 이미 있는 파일은 덮어쓰지 않으며 receipt 키는 최초 한 번만 생성한다. transcript/화면 녹화를 끄고 승인된 운영자 세션에서 실행한다. 원문은 `Read-Host -MaskInput`으로 입력하며 명령줄에 붙여 넣지 않는다.

```powershell
$secretDir = Join-Path $env:LOCALAPPDATA 'AIQA-Hosted-Operator'
$secretFile = Join-Path $secretDir 'fly-secrets.env'
if (Test-Path -LiteralPath $secretFile) { throw '기존 비밀 파일을 보존하세요' }
New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
$operatorIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls $secretDir /inheritance:r /grant:r "${operatorIdentity}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw '폴더 권한 제한 실패' }
$serverSecrets = [ordered]@{
  AIQA_DATABASE_URL = (Read-Host -MaskInput 'Postgres TLS connection URL')
  AIQA_SUPABASE_URL = (Read-Host -MaskInput 'Supabase project HTTPS URL')
  AIQA_SUPABASE_SERVICE_KEY = (Read-Host -MaskInput 'Supabase server service key')
  AIQA_HOSTED_SECRETS_JSON = (@{
    'AIQA/aiqa-server/oidc/client_secret' = (Read-Host -MaskInput 'OIDC client secret')
  } | ConvertTo-Json -Compress)
  AIQA_RECEIPT_HMAC_KEY = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
}
$secretLines = foreach ($name in $serverSecrets.Keys) {
  $value = [string]$serverSecrets[$name]
  if ($value.Length -eq 0 -or $value.Contains("`n") -or $value.Contains("`r")) { throw '비밀은 비어 있지 않은 한 줄이어야 합니다' }
  "${name}=$value"
}
[IO.File]::WriteAllLines($secretFile, [string[]]$secretLines, [Text.UTF8Encoding]::new($false))
$serverSecrets = $null; $secretLines = $null; $value = $null
```

파일은 **한 줄에 `NAME=VALUE`**, `export`/값 바깥 따옴표 없이 UTF-8로 쓴다. `AIQA_HOSTED_SECRETS_JSON`은 중괄호와 JSON 문자열 따옴표를 포함한 compact JSON 한 줄이다. `=`가 포함된 URL/base64 값은 그대로 둔다. 이 파일은 Fly stdin용이고, 위 다섯 이름만으로는 Docker의 전체 hosted 설정 파일이 되지 않는다. receipt 키와 각 revision의 키는 승인된 비밀 보관소에도 복구 가능하게 보존한다.

## 2. 이미지와 Fly 구성

저장소 루트에서 PowerShell로 앱을 생성하고 두 설정 파일을 준비한다. 이 명령부터는 사용자가 실행할 실제 유료 인프라 작업이다. Fly CLI 설치/로그인을 먼저 완료하고 `<...>`를 본인 값으로 바꾼다. `fly apps create`는 설정 파일을 만들지 않으므로 저장소 예제를 명시 복사한다.

```powershell
fly auth login
$appName = '<globally-unique-app-name>'
fly apps create $appName --org '<your-org-slug>'
Copy-Item -LiteralPath fly.toml.example -Destination fly.toml
Copy-Item -LiteralPath deploy/fly-proxy-probe.toml.example -Destination fly.proxy-probe.toml
```

두 파일의 `app`을 `$appName` 값으로, `primary_region`을 같은 선택 지역으로 편집한다. 정상 `fly.toml`에는 origin/OIDC를 채우되 proxy placeholder는 다음 관찰 뒤에 채운다. `AIQA_HOST`는 설정하지 않는다. `AIQA_PORT=8000`과 Fly internal_port를 일치시킨다. [앱 생성](https://fly.io/docs/flyctl/apps-create/), [Fly public services](https://fly.io/docs/networking/services/) 기준이다.

### 2a. 비밀 없는 첫 배포에서 실제 socket peer 관찰

정상 entry는 신뢰 peer를 필수로 요구한다. 이 선행 조건은 **동일 앱/지역/서비스의 임시 진단 프로세스**로 해결한다. `fly.proxy-probe.toml`에는 환경 비밀·OIDC·DB·migration·health check가 없고, `app` 프로세스만 `aiqa.hosted.proxy_probe`로 실행한다. 진단은 `0.0.0.0:8000`의 kernel socket peer IP 최근 64개만 `/tmp/aiqa-proxy-peers.json`에 저장한다. HTTP 요청의 path/header/body를 읽지 않으며 어떤 경로에도 고정 빈 503만 응답한다. API·인증·DB를 import하지 않는다. 정상 API의 HTTPS 정책은 바뀌지 않는다. [Fly process command](https://fly.io/docs/launch/processes/)는 이미지 CMD를 대체한다.

**새 앱에서만 실행한다.** `fly secrets list`가 staged를 포함해 비어 있어야 한다. 기존 운영 앱을 진단으로 재배포하지 않는다. 다음 명령 전에 1절 파일을 Fly에 import하지 않는다. 모듈도 알려진 서버 secret/OIDC 환경이 있으면 시작을 거절한다.

```powershell
fly secrets list --app $appName
fly config validate --config fly.proxy-probe.toml
fly deploy --config fly.proxy-probe.toml --ha=false
fly status --app $appName
fly ips list --app $appName
```

첫 `fly deploy`는 HTTP/HTTPS 서비스의 public IP를 자동 준비한다. `fly ips list`에 해당 IP가 없다면 `fly ips allocate-v4 --shared --app $appName`, IPv6가 필요하면 `fly ips allocate-v6 --app $appName`를 실행한다. 머신이 하나인지 확인하고 `fly ssh console --app $appName`으로 들어간다. SSH 안에서 다음을 실행한다. 첫 요청 전 파일이 없다는 응답은 정상이다.

```sh
cat /tmp/aiqa-proxy-peers.json
```

다른 PowerShell 창에서 인증 cookie/token 없이 외부 HTTPS 요청을 여러 번 보낸다. 다른 인터넷 회선에서도 반복한다. 503은 이 단계의 의도한 응답이다.

```powershell
1..3 | ForEach-Object { curl.exe --http1.1 --no-keepalive -sS -o NUL -w '%{http_code}\n' "https://$appName.fly.dev/proxy-observation" }
```

SSH에서 파일을 다시 읽어 외부 요청 때 추가된 peer만 확인한다. 요청을 보내지 않을 때도 IP가 계속 추가되거나 요청 시점과 대응이 불명확하면 그 주소를 신뢰하지 말고 Fly 지원으로 경로를 확인한다. browser/header의 `Fly-Client-IP`, `X-Forwarded-For`, 앱의 public/6PN 주소는 socket peer 대용이 아니다. 확인한 peer를 정상 `fly.toml`의 `AIQA_TRUSTED_PROXIES`에 **각 IP `/32` 또는 `/128`**, 여러 개면 쉼표 구분으로 넣는다. 임의 subnet이나 고정 예시를 추측하지 않는다.

진단 배포를 계속 운영하지 않는다. 확인 뒤 바로 다음 정상 배포로 대체한다. 준비를 중단하면 `fly machine stop <diagnostic-machine-id> --app $appName`으로 진단 머신을 정지한다. 실패한 관찰을 wildcard 허용으로 우회하지 않는다. Fly는 socket peer의 고정 주소를 계약하지 않으므로 이 관찰은 현재 경로의 수용 자료이며 주소 변경 때 정상 API가 거절하면 운영자가 지원과 함께 확인·갱신한다. 최소 IPv4 /24 또는 IPv6 /96보다 넓은 CIDR, `*`, 전체 private network는 preflight가 거절한다.

Docker 사용 가능한 Linux/CI에서 먼저 실행한다. 전체 환경 변수는 `deploy/hosted.env.example`을 저장소 밖에 복사해 구성한다. Fly secrets import용 5줄 파일과 달리 아래 Docker 검사에는 공개 설정도 함께 필요하다:

```sh
docker build --pull -t aiqa-hosted:check .
docker run --rm --entrypoint python aiqa-hosted:check -c 'import aiqa.api.app, aiqa.hosted.entry; from aiqa.adapters.mobile_agent_upstream import load_protocol; load_protocol(); print("linux imports and pinned protocol ok")'
docker run --rm --env-file /secure/path/hosted.env aiqa-hosted:check python -m aiqa.hosted.preflight
```

위 `/secure/path/hosted.env`는 Linux/CI 운영자가 별도로 만드는 파일이며 저장소 제공 파일이 아니다. `fly.toml`의 `[env]` 항목을 `NAME=VALUE` 한 줄씩 옮기고 1절 다섯 비밀 줄을 더해 전체 설정을 만든다. TOML 섹션/주석/바깥 따옴표는 넣지 않는다. 이미지에는 source, migrations, pyproject와 **pinned Mobile-Agent manifest/원본 3개 Python 파일/LICENSE**만 복사하며 계정 비밀은 런타임에 주입한다. Docker smoke는 Fly peer 경로를 증명하지 않는다.

실제 기동은 위와 같은 env-file에서 DB/Storage/IdP가 준비된 뒤 실행한다. 호스트에 공개 포트를 먼저 열지 말고 `docker run --rm -p 127.0.0.1:8000:8000 --env-file /secure/path/hosted.env aiqa-hosted:check`로 시작한다. HTTP health 요청도 hosted proxy 정책을 따른다. Fly 서비스의 TCP liveness가 통과해도 로그인/worker/모델 준비가 증명되지 않는다.

### 2b. 정상 API로 전환하고 비밀 주입

관찰/설정을 마친 뒤 **정상 `fly.toml`**로 전환한다. 같은 `app` process group의 Docker 기본 CMD가 정상 entry를 실행한다. `fly.proxy-probe.toml`을 정상 배포에 쓰지 않는다. 아래는 1절에서 실제 만든 `$secretFile`과 `$appName`을 같은 PowerShell 세션에서 사용한다. `--stage`는 현재 진단 머신을 즉시 재시작하지 않으며 다음 정상 배포에만 적용한다. [Fly secrets import](https://fly.io/docs/flyctl/secrets-import/) 기준이다.

```powershell
fly config validate --config fly.toml
Get-Content -LiteralPath $secretFile | fly secrets import --app $appName --stage
if ($LASTEXITCODE -ne 0) { throw '비밀 등록 실패' }
fly deploy --config fly.toml --ha=false
fly scale count 1 --app $appName
fly status --app $appName
fly checks list --app $appName
```

`--ha=false`로 첫 배포의 추가 머신 생성을 막고, 상태에서 머신이 정확히 하나인지 확인한다. manifest는 `auto_stop_machines="off"`, `auto_start_machines=false`다. `min_machines_running=1`만으로 자동 정지를 막을 수 있는 것으로 해석하지 않는다. [Fly configuration](https://fly.io/docs/reference/configuration/), [autostop](https://fly.io/docs/launch/autostop-autostart/), [machine count](https://fly.io/docs/flyctl/scale-count/), [secrets import](https://fly.io/docs/flyctl/secrets-import/) 기준이다.

기동은 migration을 수행한 뒤 기존 queue reconciliation을 한 트랜잭션으로 실행한다. remote worker의 현재 incarnation/lease/presence가 일치할 때만 유지한다. 알 수 없는 이전 native runner는 새 hosted fence로 증명하지 않고 lost/quarantine으로 남긴다. queued는 보존하며 중단 동작을 자동 재생하지 않는다. lease/quarantine을 SQL로 지워 재실행시키지 않는다. DB migration lock은 HS-2 backend가 담당한다. 별도 release machine은 만들지 않는다.

예제의 512 MiB 메모리는 작은 기능 확인을 위한 시작 설정이며 처리 용량을 검증한 값이 아니다. APK API의 500 MiB는 입력 상한이지 이 머신에서 처리 가능하다는 보장이 아니다. 현재 JSON/base64 업로드와 원격 readback은 파일 크기보다 많은 메모리를 사용한다. 큰 APK를 사용하기 전에 실제 파일 크기로 peak memory를 측정하고 머신 메모리/앱 업로드 정책을 조정한다. resumable/streaming transfer는 아직 제공하지 않는다.

## 3. 첫 프로젝트와 관리자

운영자만 Fly 서버 shell에서 실행한다. `--subject`는 위에서 검증한 본인 OIDC `sub`다. 이 CLI에는 key 원문 인수가 없고 HTTP 진입점도 없다. 서버 운영자 권한 자체가 신뢰 경계다.

```sh
fly ssh console --app <app>
python -B -m aiqa.hosted.preflight
python -B -m aiqa.hosted.bootstrap --subject '<verified-sub>' --project-key android --project-name 'Android QA' --target android
```

출력의 `project_id`, `actor_id`를 보관한다. project/domain audit, OIDC identity, 활성 admin membership은 같은 트랜잭션으로 생성한다. 동일 인수의 재실행은 멱등이다. 기존 프로젝트에 다른 identity를 덮어씌우거나 admin으로 승격하지 않는다. 현재 초기화 CLI는 첫 프로젝트·첫 관리자만 지원한다. 추가 구성원 관리 UI/CLI는 제공하지 않으며, 임의 SQL로 권한을 부여하는 절차를 이 안내의 완료로 처리하지 않는다. `https://<app>.fly.dev/ui/login?project_id=<project-id>`에서 실제 IdP 로그인과 Secure cookie를 검증한다.

모델 key target에 이 project UUID와 새 ref UUID/revision=1을 넣는다. 새 ref UUID는 PowerShell `[guid]::NewGuid().ToString()`으로 만든다. 권한 제한 폴더의 `fly-secrets.env`를 편집해 기존 `AIQA_HOSTED_SECRETS_JSON` 한 줄에 [정확한 target 형식](HOSTED_SECRETS.md)을 추가하고 OIDC 항목·receipt 키·다른 revision은 보존한다. 2b의 stdin import `--stage`와 **정상 config** deploy를 다시 수행한다. [기존 서버 CLI](HOSTED_SECRETS.md)의 `aiqa.security.provision_hosted_secret`으로 metadata를 등록한 후 **설정 화면에서 등록된 키 참조로 모델 연결**을 만든다. 모델 이름/역할 authoring/endpoint를 확인하며 원문 키 입력 폼은 hosted에서 사용하지 않는다. 이 설정 단계는 모델 호출을 하지 않는다. 녹화 저장→사람 승인, replay AI0와 healing 기본 OFF를 유지한다.

## 4. Android 워커 등록

워커 PC의 별도 사용자/session에 현재 코드와 필요한 Android/mobile-agent 의존성, 승인된 Android SDK/AVD를 준비한다. emulator를 직접 시작하고 `adb devices`, AVD 이름/serial을 확인한다. `deploy/worker.env.example`의 비밀이 아닌 값만 해당 session의 환경 변수로 넣는다. worker는 Python 패키지와 repo의 pinned tools/vendor 자원이 필요한 기존 실행 경로를 재사용하므로 API Docker 이미지를 worker로 쓰지 않는다.

예를 들어 Python 3.12가 설치된 Windows 워커에서 저장소 루트로 이동한 뒤 실행한다. placeholder는 현재 PC에서 확인한 값으로 바꾼다. 예제 env 파일은 설명용이며 PowerShell이 자동으로 읽지 않는다. 아래처럼 명시 `$env:`로 설정한다.

```powershell
$workerVenv = Join-Path $env:LOCALAPPDATA 'AIQA-Worker\venv'
py -3.12 -m venv $workerVenv
$workerPython = Join-Path $workerVenv 'Scripts\python.exe'
& $workerPython -m pip install -e '.[mobile-agent,android-video]'
if ($LASTEXITCODE -ne 0) { throw '워커 의존성 설치 실패' }
$env:AIQA_MANAGEMENT_BASE_URL = 'https://<app>.fly.dev'
$env:AIQA_WORKER_PROJECT_ID = '<bootstrap-project-UUID>'
$env:AIQA_WORKER_VERIFY_TLS = 'true'
$env:AIQA_WORKER_MODEL_MODE = 'operational'
$env:AIQA_WORKER_RUNTIME_ROOT = (Join-Path $env:LOCALAPPDATA 'AIQA-Worker\runtime')
$env:AIQA_ADB_PATH = '<absolute-Android-SDK-path>\platform-tools\adb.exe'
$env:AIQA_ANDROID_SERIAL = '<verified-serial>'
$env:AIQA_ANDROID_AVD = '<verified-avd-name>'
$env:AIQA_ANDROID_VIDEO = '1'
& $env:AIQA_ADB_PATH devices
```

로그인한 admin의 worker 설정에서 worker UUID와 목적을 정해 15분 유효 일회용 enrollment code를 발급한다. 기본 목적은 `recording`, 승인 재생 때에는 `trial` 또는 `regression` 목적의 credential을 별도로 발급한다. 한 bearer는 한 project/purpose에만 쓴다. 기존 `POST /api/v1/projects/<p>/worker-enrollment-codes`는 admin session+Origin+CSRF+Idempotency-Key를 요구한다. code를 워커 PC에서 아래처럼 교환한다(출력하지 않는다):

```powershell
$workerId = '<the-issued-worker-UUID>'
$code = Read-Host -MaskInput '일회용 등록 코드'
$body = @{ code = $code; worker_id = $workerId } | ConvertTo-Json -Compress
$reply = Invoke-RestMethod -Method Post -Uri "$env:AIQA_MANAGEMENT_BASE_URL/api/v1/worker/enrollments/exchange" -ContentType 'application/json' -Headers @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() } -Body $body
$env:AIQA_WORKER_TOKEN = $reply.token
$code = $null; $body = $null; $reply = $null
./deploy/run-worker.ps1 -Python $workerPython
```

`Read-Host -MaskInput`은 PowerShell 7.1 이상을 사용한다. token은 기존 계약상 기본 24시간이며 만료/취소 때 새 code를 발급한다. token이나 enrollment response를 로그/스크린샷/파일에 남기지 않는다. 분실한 응답을 성공으로 가정하지 말고 admin에서 해당 worker credential을 취소하고 새 code를 발급한다. 이 세션을 닫으면 token 환경값도 없어진다.

runner는 OS 실행에 필요한 환경과 명시 worker 설정만 새 자식에 넘긴다. DB/storage/OIDC/model/receipt 비밀과 알 수 없는 `AIQA_*`는 넘기지 않는다. Android의 project/adb/serial/AVD/video/model-mode와 기존 optional approved-plan/digest 값은 보존한다. 승인 패키지의 claim이 우선하며 env pin은 기존 fallback뿐이다. 별도 Web guest 작업에는 `AIQA_WEB_GUEST_ENDPOINT`, `AIQA_WEB_GUEST_PEER_TOKEN`, `AIQA_WEB_APPROVED_ORIGIN`, 선택 `AIQA_WEB_GUEST_PROOF_SECRET`/`AIQA_WORKER_APPROVED_REVISION`도 허용한다. 이 값은 worker↔자신의 guest 전용이며 서버 비밀이 아니다. 현재 Web 조립 경로는 Android inventory 변수를 비우고 model mode `fixture` 또는 미설정일 때만 선택된다. 이 Android runbook은 Web 운영 녹화를 지원한다고 주장하지 않는다.

녹화용 token으로 시범/정식 재생을 접수할 수 있는 것으로 가정하지 않는다. 녹화 작업이 끝나고 자원이 반환된 뒤 worker를 중지하고, admin에서 같은 worker UUID에 필요한 `trial` 또는 `regression` 목적의 새 code를 발급한다. 위 교환 명령으로 해당 session의 token을 바꾸고 worker를 다시 실행한다. 각 목적의 권한은 기존 서버 정책을 유지한다.

API 기동과 worker 기동은 분리되며 worker는 DB grant를 받지 않는다. 서버 worker 목록에서 online, 해당 serial/AVD/resource가 준비된 것을 확인한 다음 사용자가 새 녹화/재생을 명시 실행한다. 재접속은 이전 native 동작을 자동 재실행하지 않는다.

## 5. 실제 수용 체크

- 다른 네트워크 브라우저에서 운영 IdP 로그인/프로젝트 접근을 확인한다. 임의 forwarded header/직접 HTTP는 거절되는지 확인한다.
- worker가 online일 때 작은 녹화를 실행하고 PNG/로그의 서버 ACK와 private Storage object/metadata가 일치하는지 확인한다. 저장본 검토와 기존 시범/검증 조건을 충족한 뒤 사람이 승인해 테스트용으로 승격한다. 같은 승인 package의 저장 action만 재생하며 actor 모델 호출이 0인지 확인한다.
- worker PC를 끈 뒤 서버 `/tmp/aiqa` 캐시를 비운 재시작에서도 저장된 근거/승인본을 조회한다. 이 단계에서 삭제할 경로를 운영자가 직접 확인하고 관리 DB/원격 bucket을 지우지 않는다.
- worker 재연결 후 중단 작업의 native 자동 재실행이 없고 명시 새 실행만 진행되는지 확인한다. unknown/quarantine은 기존 정리 확인 절차를 따른다.
- 위 결과를 실제 환경/시각/명령과 함께 HS-4/5/6에 기록한다. 단위·모의 ASGI 검사만으로 실사용 PASS를 기록하지 않는다.

Postgres 연결은 [POSTGRES_STORE](POSTGRES_STORE.md)의 직접/session pooler 조건을 따른다. transaction pooler는 이 adapter의 세션 설정을 보장하지 않으므로 지원하지 않는다.
