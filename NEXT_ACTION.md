# Next Actions

> UI 개선은 [단위별 결과](docs/validation/ux/README.md)를 참고한다. 최신 master의 아래 실행 순서와 완료 수를 보존하며 UI 검증으로 native gate를 올리지 않는다.

Updated: **2026-11-02 (Asia/Seoul)** — AD-01 읽기 관찰 제공자를 구현·검증했다. 실제 전용 AVD의 상태·회전·PNG와 absent serial을 확인하고 전체269개 시험이 통과했다(기존 Hyper-V 시험1개 제외). 모델/dispatch/제품 업로드0. 기존 W 완료126/163·상위6/33은 보존하며 별도 보완은1/7 완료다. Current는 AD-02다. 실행 순서는 이 파일만 관리한다.

상세 범위/검증 등급은 카드·지정 계약, 직접 선행/상태/환경 메모는 TASK_INDEX, 전체 진행은 WORK_PROGRESS가 소유한다.
큐 문서만 고친 것으로 제품 작업을 완료 처리하지 않는다.

## Current

**AD-02 — 실제 inventory·기기 선택 연결.** 다음: AD-03. 상태 `not_started`이며 Current 선택은 착수/완료가 아니다.

- 범위/완료 기준: [AD-02 카드](docs/execution/11-development-follow-ups.md#ad-02) 하나. 계약 C00/C01/C04/C05/C14와 직접 선행 [AD-01](docs/validation/tasks/AD-01.md)·W11-01의 interface/제약만 추가로 읽는다.
- 사용 환경: [구동 기록](docs/validation/android-emulator/README.md)의 전용 `AIQA_API36`/`emulator-5580`, API36. 매 실행 serial/AVD·부팅 상태를 확인한다. 기존 AVD 초기화·다른 기기 자동 전환은 하지 않는다.
- 제공자: `AndroidObservationProvider`의 metadata-only 관찰을 기존 인증 worker inventory로 보고해 실제 환경/녹화 선택에 표시한다. 원시 ADB/키/DB 파일을 브라우저에 넘기지 않는다. 캡처 typed owner/정제가 준비 안 됐으면 미리보기 누락 사유를 보여 주며 raw PNG를 업로드하지 않는다.
- 선행 완료 근거: AD-01 전체269 passed/기존 native1 excluded, 실제 관찰 ready와 absent serial offline. [관찰](docs/validation/android-emulator/2026-11-02/ad-01/observation.json)은 제품 녹화/QA 판정/사람 승인·USB 수용이 아니다.
- 기존 W126/163과 원래 live gate는 보존한다. 별도7개 보완 중AD-01만 complete이며 상태는 [DEV_FOLLOW_UP_INDEX](docs/execution/DEV_FOLLOW_UP_INDEX.json)를 따른다. 기존 API/core를 재사용한다.

## Next

| 순서 | ID | 목표 | 직접 선행·환경 |
|---|---|---|---|
| 1 | [AD-03](docs/execution/11-development-follow-ups.md#ad-03) | 결정적 동작·전후 증거 연결 | AD-02, W13-04, W14-03, W30-02 · emulator |
| 2 | [AD-04](docs/execution/11-development-follow-ups.md#ad-04) | 실제 worker job 소비·dispatch | AD-03, W08-05, W09-04 · emulator |
| 3 | [UX-01](docs/execution/11-development-follow-ups.md#ux-01) | 묶음·수행·리포트 탐색 복원 | W20-04, W21-01, W23-04 complete · local_python, 독립 준비 |
| 4 | [UX-02](docs/execution/11-development-follow-ups.md#ux-02) | 묶음 생성·복제·보관 UI | UX-01 · local_python |
| 5 | [UX-03](docs/execution/11-development-follow-ups.md#ux-03) | entry 편집·불변 revision UI | UX-02, W21-02, W21-03 · local_python |
| 6 | [W01-02](docs/execution/01-foundation-probes.md#w01-02) | Web 격리 backend·실제 거부 검증 | blocked, Linux VM/backend 준비 후만 재평가 |
| 7 | [W29-05](docs/execution/06-replay-packages.md#w29-05) | Web direct runner 실제 재생 | W29-04 complete, Linux VM/driver 실제 준비 필요 |

AD가 환경에 막히면 선행이 충족된 UX-01 같은 독립 항목으로 전환한다. 기존37개 미완료 W는 [TASK_INDEX](docs/execution/TASK_INDEX.json)의 직접 선행·환경을 유지하며, 준비되면 원래 카드로 재개한다. Android 개발이 Web VM 때문에 다시 대기하지 않게 한다. 원래 USB 실기기/양 플랫폼/모델 품질 gate는 에뮬레이터 결과로 올리지 않는다.

[검토 근거](docs/validation/reviews/2026-11-01-next-action-review.md). 전체 JSON과 과거 감사 문서를 연쇄로 읽지 말고 두 색인에서 후보 ID/선행/상태/환경 요약만 코드로 조회한다.

## 외부 대기와 보존할 경계

| 대상 | 상태·재개 조건 | 막히는 범위 |
|---|---|---|
| Android 개발 | 전용 AIQA_API36 구동·관찰·4개 동작 확인. 현재 emulator-5580. 미실행이면 시작 도구/부팅 확인 후 재개 | AD 개발 경로만 허용; 원래 USB live gate 대체 아님 |
| W01-02 | blocked. 같은 PC VM의 실제 script/driver 격리 검증 가능 시 [인계](docs/validation/tasks/W01-02.md)에서 재개 | 해당 Web native 가지와 실제 통합 gate |
| 민감 캡처 | 픽셀 정제 coverage 제공자 연결 전 차단. [수정 결과](docs/validation/reviews/2026-11-01-remediation-result.md#다음-작업자가-지킬-한계) 참고 | 민감 화면의 실제 authoring/증거 전송. 독립 broker/core는 계속 |

진짜 선행을 삭제하거나 fixture로 live gate를 대신하지 않는다. 기존 완료 이력과 수정 상세는 인계/진행표에서 필요한 ID만 읽으며 큐에 누적하지 않는다.

## 차단되었을 때 다음 작업 선택

1. 코드로 고칠 수 있는 현재 결함은 범위 안에서 고친다. 외부 환경/권한/입력 때문에 못 하면 blocked로 기록한다.
2. 차단 ID·원인·재개 조건·영향 ID·인계 경로를 위 외부 대기에 남기고 카드와 해당 색인(TASK_INDEX 또는 DEV_FOLLOW_UP_INDEX)의 상태를 맞춘다. blocked를 complete로 바꾸지 않는다.
3. Next에서 **미완료·blocked 아님·모든 직접 선행 complete+인계 보유·알려진 unavailable 환경 요구 없음**인 후보를 고른다.
4. Next에 준비 후보가 없으면 기존 TASK_INDEX와 DEV_FOLLOW_UP_INDEX를 합쳐 같은 조건으로 bootstrap→core→환경 준비된 integration 순으로 조회한다. 숫자가 앞선 blocked를 계속 Current에 두지 않는다.
5. 준비된 독립 ID를 Current로 이동하고 선택 이유를 짧게 적는다. 차단 항목은 대기에 유지한다. 후보도 없을 때만 필요한 재개 조건을 보고한다.
6. 다른 작업이 외부 차단을 사실상 소비한다면 진짜 선행을 지우지 않는다. core 계약 구현과 live 검증은 카드의 등급/담당에 따라 분리한다.
7. 환경 변경/새 근거가 있을 때만 해당 가지를 재평가한다. 실제 VM/USB/AI 검증·격리·QA 기준을 생략해 완료하지 않는다.

## 매 실행의 최소 입력과 종료

1. 이 파일→Current 카드→지정 CONTRACTS 절→직접 선행 인계의 interface/검증/제약만 읽는다. 관련 현재 코드/저장소 지침을 확인한다.
2. Current 하나를 구현·검증한다. `bootstrap/core_contract`는 실제 local app/API/DB/파일/브라우저로 검사하고 외부 관찰 fixture를 실제 native 근거로 기록하지 않는다. live/final은 해당 실제 evidence가 필수다.
3. `docs/validation/tasks/<ID>.md`에 변경 파일·제공 interface·명령/결과·검증 등급/fixture 여부·미완료/재개 조건을 기록한다. 필요 시 [인계 형식](docs/execution/HANDOFF.md#완료-인계-파일)만 읽는다.
4. 카드 체크·해당 색인(TASK_INDEX 또는 DEV_FOLLOW_UP_INDEX)·[WORK_PROGRESS](WORK_PROGRESS.md)를 맞춘다. 부모 W는 소속 leaf뿐 아니라 parent_gate_tasks/원래 통합 조건이 끝나야 완료다.
5. 완료면 다음 준비 후보로 이동한다. 미완료지만 외부 차단이 아니면 Current/재개 지점을 유지한다. 외부 차단이면 위 규칙으로 **다음 독립 후보로 전환**한다.
6. Current를 바꿀 때 ID/상태/카드 링크/필수 계약/선행/인계/다음 후보/Updated를 함께 갱신하고 Next는8개 이내로 보충한다. 새 Current 선택은 착수/완료가 아니다.
7. 한 실행 후 멈추며 사용자가 연속 실행을 요청한 경우만 다음 Current를 이어간다. 최종 보고는 수행ID/결과/차단·재개조건/갱신 Current/다음 후보를 간결히 적는다.
8. 계약 변경/새 결함은 소유 spec·카드/소비자·추적표를 맞추고 영향받은 완료 항목만 재개한다. 사용자 DB 초기화·이력 삭제·새 인프라/권한/구매/배포를 범위 밖에서 임의 수행하지 않는다.

[독립 진행/선행 변경 상세](docs/execution/SCHEDULING.md). 제품 경로에 fake adapter/가짜 PASS를 넣거나 live gate를 건너뛰지 않는다.

## Cursor에 전달할 한 문장

```text
NEXT_ACTION.md의 Current 하나를 구현·검증하고 인계와 큐를 갱신해줘. 외부 차단이면 근거/재개 조건을 남긴 뒤, 선행이 충족된 독립 후보로 Current를 바꿔줘. bootstrap/core 검증과 실제 VM·기기·모델 검증을 구분하고 완료 기록은 보존해줘.
```
