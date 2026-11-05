# 한 PC에서 관리 서버와 실행 워커 검증

현재 PC에서는 관리 API와 워커를 **서로 다른 프로세스**로 띄운다. 관리 서버만 DB와 artifact 경로를 열고, 워커는 HTTPS 주소·신뢰할 CA·등록 토큰으로 접속한다. 실제 배치에서도 같은 접속 경계를 사용한다. 관리 API를 옮길 때는 API의 주소·TLS·저장 경로를 바꾸고, 실행 PC를 옮길 때는 워커에 등록 정보와 해당 PC의 기기 설정을 넣는다.

| 설정 주체 | 한 PC에서 확인할 값 | 나중에 분리할 때 바꿀 값 |
|---|---|---|
| 관리 API | loopback에 임시 포트, 임시 `AIQA_RUNTIME_ROOT`, 명시적 개발 TLS 인증서 | 별도 관리 호스트의 영속 저장 경로, hosted profile, proxy 공개 주소·TLS·IdP |
| 워커 | `AIQA_MANAGEMENT_BASE_URL`에 loopback HTTPS, `AIQA_WORKER_CA_BUNDLE`에 개발 CA, 테스트 등록 토큰 | 관리 호스트 HTTPS 주소, 해당 CA와 워커 전용 등록 토큰 |
| Android | `AIQA_WORKER_PROJECT_ID`, `AIQA_ADB_PATH`, `AIQA_ANDROID_SERIAL`, `AIQA_ANDROID_AVD` | 실행 PC의 ADB와 등록한 전용 기기 |
| 모델 | 로컬은 `AIQA_MODEL_PROVIDER_MODE=fixture` 또는 미설정. operational은 `BASE_URL`·CA를 명시. 워커는 `AIQA_WORKER_MODEL_MODE=operational`과 승인본 `AIQA_WORKER_APPROVED_*` | 승인된 HTTPS 주소·CA·secret ref는 RX-45, 워커 응답·승인 재생은 RX-46. 실제 상용 키·독립 호스트 최종 수용은 RX-23/24. 키는 관리 서버에만 저장 |

## 실행

`probe_same_pc_stage.py`는 인증서와 기기를 명시적으로 받는다. 테스트 인증서에는 `127.0.0.1` IP SAN이 있어야 한다. CA는 해당 실행에만 전달한다. 기본 포트는 자동으로 선택하며 필요하면 `--port`로 지정한다.

```powershell
.\.venv\Scripts\python.exe -B tools/validation/probe_same_pc_stage.py `
  --cert $cert --key $key --ca $ca --adb $adb `
  --serial emulator-5580 --avd AIQA_API36

.\.venv\Scripts\python.exe -B tools/validation/probe_same_pc_stage.py `
  --cert $cert --key $key --ca $ca --adb $adb `
  --serial emulator-5580 --avd AIQA_API36 --mode recording
```

기본 `--mode inventory`는 운영 데이터 경로와 환경 변수를 가져오지 않는다. 임시 프로젝트·등록 토큰·서버 DB를 만들고, 실제 HTTPS에서 워커 heartbeat와 Android 기기 목록을 기다린다. 이어 테스트 워커 프로세스만 종료하고 서버가 계속 응답하는 동안 워커 상태가 오프라인으로 바뀌는지 확인한다. 이 모드의 워커에는 실행 핸들러가 없다.

`--mode recording`은 `AIQA_WORKER_MODEL_MODE=fixture`로 실제 워커 진입점에 Android 녹화 핸들러를 붙인다. claim→ACK→전용 AVD Settings 동작→전후 PNG·로그 서버 저장→`approved=false` 검토 대기까지 확인한다. 운영 모델 키는 쓰지 않는다.

모의 HTTPS operational 응답→워커 `model-requests`→녹화 행동과 승인본 재생(actor 0)은 RX-46 통합 시험으로 사전 검증한다. 실제 운영 키·독립 호스트 최종 수용은 RX-23.

## 2026-11-04 실행 결과

임시 CA를 명시해 실제 loopback TLS 연결에 성공했다. API와 워커 PID는 서로 달랐고, 등록된 워커는 `AIQA_API36`의 `720×1600@0` 기기 정보를 서버에 저장했다. 워커 프로세스 종료 후 실제 heartbeat 만료를 기다려 온라인에서 오프라인으로 전환됐으며, 관리 API는 계속 200을 반환했다.

관리 API가 받는 inventory 상태는 기존 네 가지 값으로 제한된다. 실행 핸들러 없는 기동은 기기를 `offline`으로 보고하고, 워커 연결 상태는 heartbeat로 별도 판단한다. 검증용 토큰에는 기기 목록 보고에 필요한 `resource_probe` 범위를 줬다. 녹화와 기기 목록을 하나의 실행 워커에서 사용할 등록 범위는 RX-44의 실제 진입점 시험에 포함한다.

## 검증을 이어갈 기준

- RX-43은 로컬 ASGI fixture로 통과했다. 녹화 완료 시 서버 `artifact_objects`에 before/after PNG와 action.log가 ready+acked로 저장되고, `artifact_refs`·`actions`가 연결되며 디스크 바이트를 읽는다. 이벤트 hash만으로는 완료하지 않는다. 인계 [RX-43](../validation/tasks/RX-43.md).
- RX-44는 `--mode recording`으로 통과했다. 별도 API/워커 PID, TLS, `AIQA_API36` ready inventory, artifact 3·refs 3·actions 1, `finish_approved=false`/`verdict=null`, 워커 종료 후 API health 유지. 인계 [RX-44](../validation/tasks/RX-44.md).
- RX-46은 모의 HTTPS로 워커 operational authoring·승인본 재생을 통과했다. 인계 [RX-46](../validation/tasks/RX-46.md).
- 전원 차단 뒤에도 별도 호스트가 승인할 수 있는지, Web 생성 코드가 VM 밖의 파일·네트워크에 접근하지 못하는지, 실제 운영 키로 행동을 녹화할 수 있는지는 각각의 실환경 카드에서 수용한다.
