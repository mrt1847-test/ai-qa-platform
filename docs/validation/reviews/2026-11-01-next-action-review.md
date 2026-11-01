# NEXT_ACTION 검토와 Android 개발 경로

2026-11-01 · 기준 `master`/UI 통합 HEAD `3db8a58`.

## 판정

기존163개 색인에는 complete126, blocked1, not_started36이 있다. 직접 선행만 끝난 미완료 항목은 W01-02와 W29-05이며 둘 다 Linux VM을 요구한다. 완료 항목의 인계 누락과 미완료 직접 선행은 없다. 따라서 기존 색인만 계산한 “준비된 새 core 없음”은 맞지만, 이를 제품 개발 종료로 해석하면 안 된다.

## 확인한 누락

1. `src/aiqa/web/context.py`의 묶음/수행/리포트 메뉴 href가 None이다. 관련 API와 조회 화면이 있어도 사용자가 메뉴로 들어갈 수 없다. VM 없이 연결·빈 상태·권한·탐색을 보완할 수 있다.
2. W21-01/02/03은 core 완료지만 `suites.html`에는 생성/복제/보관 UI가 없고 `suite_editor.html`에는 entry 추가/삭제/순서/저장 제어가 없다. 해당 시험은 직접 HTTP mutation 뒤 읽기 화면 문구를 검사하므로 실제 사용자 편집을 증명하지 않는다. 기존 API 근거를 보존하고 UI 부족분을 추가 작업으로 편성해야 한다.
3. `launcher.py:main`의 worker는 sleep 루프다. claim/ACK/lease 서비스는 있으나 시작한 프로세스가 이를 소비하는 실행 연결이 없다. native 작업과 분리할 수 있는 worker 수명/소비 연결을 별도로 추적해야 한다.
4. W02-01은 Web 탐색 W01-04, W03-01은 Android 탐색 W02-04에 직렬 연결되어 있다. 플랫폼별 개발·관찰까지 이 순서를 강제할 기술 근거가 부족하다. 원래 USB/양 플랫폼 live gate를 지우는 대신 에뮬레이터 개발 경로를 별도로 추가한다.
5. `probe_web_isolation`은 현재 호스트 근거를 읽고도 항상 supported=False를 반환하며 hyper-v만 허용한다. 기존 환경 기록의 Windows Home 제약도 있어 “VM이 생기면 재개”만으로 해결되지 않는다. 지원 backend 결정·실제 prepare/probe/destroy 구현이 남아 있다. Android WHPX 사용 가능은 Web script 격리 합격과 다르다.

이 검토로 기존126개를 모두 취소하거나 기존 테스트를 다시 구현하지 않는다. 부분 API 완료·사용자 UI 완료·실제 엔진 통합을 분리하고 확인된 부족분만 추가한다.

## 실제 Android 개발 환경 확인

사용자가 에뮬레이터 직접 구동을 지시했다. 설치된 공식 SDK/API36 이미지를 재사용해 별도 `AIQA_API36` AVD를 workspace의 ignored `.review-work/android/avd`에 만들었다. 기존 AVD 사용자 데이터와 USB 기기는 조작하지 않았다.

- 가속: 실제 일반 로컬 실행의 `emulator -accel-check`가 WHPX usable/exit0. 샌드박스 안의 실패와 구분한다.
- serial `emulator-5580`, Android16/API36, 새 전용 AVD. 모델 호출0.
- 최초1080×2400/software/2048MB에서 System UI·Settings ANR가 발생했다. 첫 `actions/` 결과는 명령/관찰 기록이며 정상 동작 근거가 아니다.
- GPU host,720×1600,density280,RAM1536MB,2cores로 조정했다. 호스트16GB RAM에서 조회 당시 여유가 약1GB라 RAM 증설 대신 렌더링 부담을 낮췄다. 다른 사용자 프로세스는 종료하지 않았다.
- 재시도 `verified-actions/manifest.json`의4개 스텝은 실제 UI 계층으로 기대 화면에 도달했다. 전후 PNG8장과 계층4개, 로그를 남겼다. tap 좌표는 당시 `Network & internet`의 실제 bounds에서 계산했다. 자동 QA 결과/승인과 제품 녹화 통합은 아직 아니다.

[개발 실행·증거](../android-emulator/README.md) · [다음 보완 카드](../../execution/11-development-follow-ups.md) · [보완 색인](../../execution/DEV_FOLLOW_UP_INDEX.json).
