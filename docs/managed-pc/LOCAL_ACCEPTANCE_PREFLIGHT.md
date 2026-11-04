# 등록 PC 실환경 수용 전 점검

2026-11-04 (Asia/Seoul) · [실행 큐](../../NEXT_ACTION.md)

사용자가 별도 장비가 없으므로 현재 PC에서 가능한 검증부터 진행하라고 했다. 전용 에뮬레이터에서 실제 동작을 확인하고, 호스트 단절과 Web 격리가 필요한 최종 수용은 별도 상태로 유지한다.

## 실제 Android 기기 증거

- `adb -s emulator-5580 emu avd name` → `AIQA_API36`. boot 완료, 720×1600, 회전 0. Android 관찰 provider의 metadata-only는 `ready`, 캡처 없음.
- 전용 AVD에서 Android Settings 화면을 열고 `AndroidObservationProvider.observe(capture=True)`로 전 캡처를 얻었다. `AndroidDeterministicDriver.run`에서 추정 대상은 입력 0회, 동일 serial과 geometry의 승인 좌표로 스와이프 1회, 모델 호출·자동 재시도 0회를 확인했다.
- 동작 뒤 별도 관찰로 후 캡처를 얻었다. 전후 PNG와 로그가 임시 `EvidenceSpool`의 연속 2건으로 저장됐다. 전 PNG SHA-256 `6f759ec095b456a98ef7d9253d1a1da7ef06796caf5a3b1c874c571cbac52762`, 후 `c6109f933957178056be3ffc3431e65914bc19666923000d9f710b80adfb9f57`. 화면과 로그는 임시 경로에서 검증 후 정리했다.
- 검증 등급은 실제 ADB·driver 부분 시험이다. 녹화 모델, 서버 증거 ACK, 승인, 운영 키가 필요한 경로는 RX-23에 남긴다.
- RX-32 기동 보완은 프로세스 환경의 serial·AVD·boot ID를 읽고, 실행 핸들러가 없는 동안 기기를 실행 불가로 보고하며 claim을 보내지 않는다. 대상 시험 14개, 등록 PC·Android·UX 회귀 109개 통과.

## 수용 카드별 재개 범위

| 카드 | 현재 PC에서 확인한 범위 | 실환경 완료에 남은 조건 |
|---|---|---|
| RX-21 | hosted 설정·모의 IdP·임시 저장 및 복원 테스트. RX-41은 OperationalOidcClient·token endpoint fixture 완료 | 독립 호스트·접속 주소/TLS·실제 IdP·별도 접속 PC |
| RX-22 | Windows 11 Home, 하이퍼바이저 표시 True. Hyper-V VM 관리, VMware, VirtualBox, QEMU 명령·서비스를 찾지 못함 | 지원 VM과 전용 Web 대상에서 실제 격리 거부 시험 |
| RX-23 | 전용 AVD와 실제 ADB 스와이프·전후 증거 확인. RX-39는 로컬 ASGI·fixture로 claim→ACK→동작→증거 ACK→검토 대기 경로 완료 | 운영 서버에서 설정한 모델 키, 전용 AVD에서 등록부터 증거 ACK·검토·재생까지 검증 |
| RX-24 | Web fixture driver·IPC·승인 digest 검사. RX-42는 fixture guest·워커 증거 ACK 경로 완료 | RX-22의 실제 격리, 전용 Web 대상과 모델 연결 |
| RX-25 | 임시 환경에서 worker 없이 저장본 승인과 실행 차단 회귀 | 독립 호스트에서 실제 실행 PC 전원 종료 중 별도 접속 PC로 검증 |
| RX-26 | 임시 DB에서 미확정 dispatch, 늦은 ACK·정리 fence 회귀 | RX-38 및 실제 워커 통신 단절 전후 검증 |
| RX-27 | 임시 DB에서 lease·정리 fence 기본 회귀 | 서로 다른 등록 워커와 공유 테스트 자원에서 실제 경합 |
| RX-29 | 기존 정책의 replay actor 0·healing OFF fixture 검증 | RX-23/24의 실제 점유·토큰 표본. 측정 전 비용/처리량은 미확정 |
