# Android 에뮬레이터 개발 환경

2026-11-01 · 실제 AVD `AIQA_API36` / `emulator-5580` / Android16 API36.

설치된 SDK·system image를 재사용한다. `tools/validation/start_android_emulator.ps1`은 전용 AVD만 workspace `.review-work/android/avd`에 만들며 설치·기존 AVD 초기화는 하지 않는다. 현재 background/headless로 실행 중이다. `-ShowWindow`는 새 기동 시 창을 연다. 이미 실행 중이면 중복 기동하지 않으며 기존 인스턴스를 임의 종료하지 않는다.

## 실행

저장소 루트에서 기존 Python 환경을 사용한다. SDK 위치가 다르면 시작 스크립트의 `-SdkRoot`, Python 도구의 `--adb`를 지정한다.

```powershell
& tools/validation/start_android_emulator.ps1
adb -s emulator-5580 shell getprop sys.boot_completed
# 위 값이1인 뒤:
python tools/validation/probe_android_emulator.py --adb "$env:LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" --serial emulator-5580 --out .review-work/android/observation
python tools/validation/exercise_android_emulator.py --adb "$env:LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" --serial emulator-5580 --out .review-work/android/actions-new
# 작업 종료 시 이 전용 인스턴스만:
adb -s emulator-5580 emu kill
```

첫 관찰/동작 도구는 emulator serial과 정확한 AVD 이름을 검사한다. USB 기기는 거절한다. 동작 도구는 이 전용 AVD의 기본 Settings 앱만 사용하며 모델·로그인·사용자 앱 설치는 하지 않는다. 제품의 lease/정제/권한 경로를 대신하는 운영용 runner가 아니다.

## 확인한 결과

- SDK/ADB와 WHPX 가속 사용 가능, 별도 AVD 부팅·ADB 연결·실제 PNG 캡처 확인.
- 초기 software/1080×2400/RAM2048MB 프로필은 ANR가 있었다. [초기 관찰](2026-11-01/settings/observation.png), 초기 [동작 기록](2026-11-01/actions/manifest.json)은 정상 동작으로 판정하지 않는다.
- 최종 GPU host/720×1600/density280/RAM1536MB/2core에서 [4개 동작의 실제 화면 확인](2026-11-01/verified-actions/manifest.json)과 [스텝 로그](2026-11-01/verified-actions/actions.jsonl)를 저장했다. 각 동작의 PNG와 XML도 같은 폴더에 있다.
- tap→네트워크 상세, back→설정 첫 화면, swipe→아래 설정 항목, back→런처를 UI 계층으로 확인했다. 명령 반환만으로 성공을 판단하지 않았다.
- AI/model 호출0. 이는 기기 제어 개발 시험이며 제품 QA 판정과 사람 승인은 수행하지 않았다.

Android emulator는 Android 개발·자동화의 실제 대상이지만 USB 연결/물리 기기의 IME·제조사별 geometry·FLAG_SECURE·단절 특성 검증을 대신하지 않는다. W02/W07/W30 등의 원래 실제 수용은 보존한다. 다음은 전용 관찰을 제품 inventory와 trusted action 경로에 연결하는 AD 작업이다.
