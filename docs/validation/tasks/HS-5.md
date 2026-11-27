# HS-5 outbound PC 워커 인계

- 코드 상태: **complete — 기존 worker의 hosted 접속 entry/env 격리/실행 안내**.
- 실환경 상태: **not_started — 배포된 Fly 주소에 현재 PC 등록 미실행**.
- 선행: HS-4 실제 서버/첫 admin. [운영 절차 4절](../../managed-pc/FLY_HOSTED_RUNBOOK.md#4-android-워커-등록).

`python -m aiqa.hosted.worker`, `deploy/run-worker.ps1`/`.sh`, `deploy/worker.env.example`을 제공한다. 기존 outbound HTTPS worker client와 목적별 enrollment/heartbeat/claim/native handler를 재사용한다. API Docker 이미지가 emulator를 실행하지 않는다. 현재 PC에 SDK/AVD를 두고 들어오는 포트 없이 서버로 접속한다.

새 자식 환경은 OS 실행/Android SDK/명시 worker 값만 허용한다. project/serial/AVD/video/model-mode/기존 approved pin과 선택 Web guest 전용 값은 전달하지만, 서버 DB/Storage/OIDC/모델/receipt 비밀과 알 수 없는 AIQA 설정은 제거한다. worker TLS OFF는 시작 전에 거절한다. token은 기존 purpose/project 범위와 만료·취소 계약을 따른다.

환경 allowlist와 실제 worker 진입점의 전달 값은 `test_hs4_hosted_runtime.py`에서 합성 검사했다. 기존 Android handler/claim 및 Linux 없는 portability 검사는 실제 Fly 접속/AVD 성공이 아니다. 모델/ADB 실호출은 하지 않았다.

HS-4 서버가 준비되면 현재 PC에서 AVD 시작→검증된 serial→목적별 code 교환→run-worker→서버 online/resource readiness를 확인한다. 재접속만으로 중단 동작을 자동 실행하지 않는다. 실제 성공·실패·환경을 이 인계에 추가한다. Web guest 실환경 수용은 기존 RX-22/24이며 이 Android 카드의 완료로 대신하지 않는다.
