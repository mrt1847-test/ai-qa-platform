# 환경 대기와 분리한 개발 보완

2026-11-01 · [검토 근거](../validation/reviews/2026-11-01-next-action-review.md) · [보완 색인](DEV_FOLLOW_UP_INDEX.json) · [실행 큐](../../NEXT_ACTION.md).

원래 W163개의 계약/완료126개/실제 수용을 보존한다. 아래7개는 기존 API/core 근거를 재사용해 확인된 구현·연결 부족분을 보완하는 별도 목록이다. 새로 완료한 W로 계산하지 않는다. Current는 NEXT_ACTION 하나가 정한다.

## 공통

- 에뮬레이터는 사용자가 승인한 개발 대상이다. [실제 구동 기록](../validation/android-emulator/README.md)을 먼저 보고 기존 `AIQA_API36`을 재사용한다. 모든 ADB 명령에 명시 serial, 인자 배열, timeout을 사용한다. 자동으로 다른 기기나 USB로 전환하지 않는다.
- Web VM와 USB 실기기 수용을 선행으로 묶지 않는다. 실제 USB/격리/모델·양 플랫폼 gate는 그대로 미완료다. 모델/새 앱 설치가 필요한 단계는 준비 조건을 확인하고 현재 기초 동작에 몰래 포함하지 않는다.
- 제품 파일을 test-only 도구의 직접 ADB 호출에 연결하지 않는다. 실제 product dispatch는 기존 control/lease/generation·journal·정제/증거 권한을 소비한다. 민감 캡처 제공자가 없으면 차단한다.
- 공통 계약 C00/C01/C04/C05/C14와 담당 범위만 읽는다. 실제 인계는 `docs/validation/tasks/<ID>.md`, 보완 색인/큐를 같이 갱신한다. 큰 작업이면 현재 카드의 미완료 하위 단계를 유지하며 다음 카드까지 수행하지 않는다.

<a id="ad-01"></a>
## AD-01 — 명시 serial Android 관찰 제공자

- 상태 not_started. 직접 선행 W07-01/W13-01 complete. 환경은 부팅된 프로젝트 전용 emulator+기존 Python이며 VM/모델 키가 필요 없다.
- 대상: `src/aiqa/environments/usb_android.py`의 기존 gate를 보존하고 별도 `src/aiqa/environments/android_observation.py`, `tests/integration/test_android_observation.py`에 관찰 어댑터를 추가한다. 공개 Mobile-Agent 원본은 참고하고 변경하지 않는다.
- 순서: (1) serial/AVD·상태·timeout 계약 (2) 실제 Android/API/geometry/rotation·capture 가능 상태 읽기 (3) PNG 내용/geometry 검증과 관찰 projection (4) 실제 전용 AVD와 offline/잘못된 serial·capture 실패 검사.
- 완료: import 시 ADB 초기화0; 지정 serial만 사용; unavailable/권한/부팅 미완료를 구분; 실제 PNG와 관찰 시각·geometry가 일치. 파일 저장은 개발 증거 경로만, 제품 업로드/dispatch/AI는 이 카드 범위 밖이다.
- 검사: 위 새 시험+기존 W13/W07 영향 범위. 에뮬레이터 실제1회와 실패 입력을 구분해 인계한다.

<a id="ad-02"></a>
## AD-02 — 실제 inventory·기기 선택 연결

- 상태 not_started. 직접 선행 AD-01/W11-01. 대상 `worker/resources.py`, 기존 inventory API 소비 지점, 환경/녹화 기기 선택과 관련 시험.
- 순서: (1) host worker identity+serial로 기존 물리 resource key 유지 (2) AD-01 관찰을 기존 InventoryReport로 보고 (3) 실제 에뮬레이터가 환경/녹화 선택에 표시 (4) 재조회 중복/종료 offline·다른 프로젝트 권한 확인.
- 완료: 에뮬레이터임을 표시하며 가짜 ready 없음. 원시 ADB/CDP/키를 브라우저에 넘기지 않음. 선택 UI의 실제 관찰 시각·상태가 일치한다. 캡처의 typed owner/정제가 준비되지 않은 미리보기는 누락 사유로 표시하며 임의 artifact owner를 허용하지 않는다. 실제 명령은 AD-03이다.

<a id="ad-03"></a>
## AD-03 — 저장 동작·전후 증거의 Android 실행 연결

- 상태 not_started. 직접 선행 AD-02/W13-04/W14-03/W30-02. 대상 기존 action phase/Android plan runner와 신뢰 Android dispatch adapter, 해당 시험.
- 순서: (1) tap/swipe/back만 기존 typed 명령에 연결 (2) 현재 geometry·lease·generation 재검사 (3) 전후 정제 PNG/log를 기존 REC/ITEM/attempt/action 증거에 연결 (4) 저장 plan 재실행에서 actor0, timeout 뒤 재전달0, offline/rotation/정제 없음 차단 확인.
- 완료: 테스트 전용 Settings 장면으로 실제 행동과 증거 수가 대응한다. AI를 호출하지 않으며 UI는 실제 저장된 증거만 조회한다. 비밀 입력·IME·앱 설치·FLAG_SECURE 실기기 수용을 완료하지 않는다.

<a id="ad-04"></a>
## AD-04 — 시작한 worker의 실제 job 소비 연결

- 상태 not_started. 직접 선행 AD-03/W08-05/W09-04. 대상 `launcher.py`의 sleep-only entrypoint와 기존 worker service/runner 경계, process 통합 시험.
- 순서: (1) 명시 설정/자격을 가진 worker 시작·종료 (2) 기존 claim→ACK→heartbeat→허용 purpose 라우팅 (3) AD-03 adapter dispatch와 finish (4) 재시작·중복 시작·lost·취소·정리 증거 확인.
- 완료: PID 존재와 실제 job 처리 상태를 분리한다. 기존 slot1/멱등/취소/QA 불변을 유지하고 새 로컬 fixture runtime에서 현재 에뮬레이터용 plan 하나를 처리한다. unsupported purpose는 dispatch 전 명시 차단하며 가짜 completed/PASS를 쓰지 않는다. 실제 AI 녹화 loop는 기존 W16 native/model 후속 범위다.

<a id="ux-01"></a>
## UX-01 — 실제 있는 화면으로 탐색 복원

- 상태 not_started. 선행 W20-04/W21-01/W23-04. 대상 `web/context.py`, 공통 navigation, 관련 페이지 shell·접근성 시험.
- 기존 묶음/수행/리포트 GET route로 메뉴를 연결하고 해당 section·breadcrumb·프로젝트 권한·빈 상태·키보드 진입을 검증한다. 페이지 조회로 실행/설치를 만들지 않는다. 준비 안 된 실행 접수는 기존 서버 gate를 유지한다. API·DB 재구현 없이 실제 브라우저로 세 경로에 도달하면 완료다.

<a id="ux-02"></a>
## UX-02 — 묶음 생성·복제·보관 UI

- 상태 not_started. 선행 UX-01. 대상 suites template·새 controller·공통 form/command·브라우저 회귀.
- 기존 API로 이름/설명/대상/담당/분류 입력→생성 ACK→목록, 복제/보관 명시 확인과 receipt, 422/409/응답 유실·입력 보존을 각각 구현한다. 실제 UI 조작으로 DB를 조회해 검증한다. 기존 suite revision과 수행을 변경하지 않는다. 생성·복제·보관 각 흐름을 구별해 인계한다.

<a id="ux-03"></a>
## UX-03 — 묶음 entry 편집 UI

- 상태 not_started. 선행 UX-02/W21-02/W21-03. 기존 suite domain/API를 소비하며 `suite_editor.html`·controller·관련 브라우저 시험을 보완한다.
- (1) 승인 케이스 검색과 entry 추가/삭제 (2) 순서·exact version/approval·data/env/reset/실패 정책 (3) 새 revision 저장과 409/미저장 보호 (4) 새 승인 제안의 선택 수락/거부를 하위 재개 지점으로 수행한다. 각 하위 흐름의 UI 조작·DB 불변 근거가 모두 있어야 완료다. API 호출 뒤 읽기 문구만 확인해서 완료하지 않는다.
