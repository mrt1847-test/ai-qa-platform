# Next Actions

> UI 개선은 [단위별 결과](docs/validation/ux/README.md)를 참고한다. 최신 master의 아래 실행 순서와 완료 수를 보존하며 UI 검증으로 native gate를 올리지 않는다.

Updated: **2026-11-01 (Asia/Seoul)** — W27-04를 완료했다. W29-05는 VM이 아직이라 Current가 아니다. W29-03은 VM 선행이 아직이라 Current가 아니다. W19-04는 W16-04·W17-04와 실제 환경이 아직이라 Current가 아니다. Next 표의 1~8은 선행 또는 실제 환경이 끝나지 않았다. 색인에서 선행이 끝나고 local_python만 필요한 core는 남아 있지 않다. W32-02는 W22-04, W31-07, W27-03이 끝나기 전에는 Current가 아니다. W27-01은 W22-04와 실제 VM·기기·모델 환경이 끝나기 전에는 Current가 아니다. 완료126/163·상위6/33. 실행 우선순위는 이 파일만 관리하며 완료 이력은 WORK_PROGRESS/작업 인계에 둔다.

상세 범위/검증 등급은 카드·지정 계약, 직접 선행/상태/환경 메모는 TASK_INDEX, 전체 진행은 WORK_PROGRESS가 소유한다.
큐 문서만 고친 것으로 제품 작업을 완료 처리하지 않는다.

## Current

**준비된 Current 없음.** 선행이 끝나고 local_python만 필요한 core는 남아 있지 않다. W29-05는 Linux VM이 있어야 다시 고를 수 있다. W32-02는 W22-04, W31-07, W27-03이 끝나기 전에는 준비되지 않는다. W27-01은 W22-04와 실제 VM·기기·모델 환경이 끝나기 전에는 준비되지 않는다.

- 재개: VM이 생기면 [W29-05](docs/execution/06-replay-packages.md#w29-05)를 다시 평가한다. Next 표의 선행이 끝나면 그 행을 Current로 올린다.
- 완료된 직전 작업: [W27-04](docs/execution/10-retention-and-release-gates.md#w27-04). 인계는 [W27-04](docs/validation/tasks/W27-04.md).
- 이 상태는 새 구현 착수가 아니다. VM/agent 설치와 모델 호출은 하지 않는다.

완료126/163·상위6/33과 개별 근거는 [WORK_PROGRESS](WORK_PROGRESS.md)를 따른다. 완료 표기는 새 결함의 수정을 금지한다는 뜻이 아니다. [이번 계약 보완 결과](docs/validation/reviews/2026-11-01-remediation-result.md)의 마지막 한계/인계 절을 함께 따른다. 같은 보완을 다시 구현하지 않는다.

## Next

가까운 후보8개다. 모든 직접 선행이 complete이고 인계가 존재하는 후보만 Current로 올린다.

| 순서 | ID | 목표 | 직접 선행 |
|---|---|---|---|
| 1 | [W11-04](docs/execution/04b-environments-and-launcher.md#w11-04) | 설치 앱 선택과 metadata inspect | W11-03, W07-03 |
| 2 | [W11-06](docs/execution/04b-environments-and-launcher.md#w11-06) | 명시 설치·reset 영향과 사후 관찰 | W11-04, W11-05, W07-03 |
| 3 | [W15-04](docs/execution/05a-action-evidence-and-models.md#w15-04) | 모델 연결 검사·비용·무키 replay 안내 UI | W15-03, W03-01 |
| 4 | [W16-02](docs/execution/05b-recording-workflow.md#w16-02) | 자연어 구조화 관리 job·diff 수락 | W16-01, W15-04 |
| 5 | [W16-04](docs/execution/05b-recording-workflow.md#w16-04) | authoring loop·실시간 action timeline·메모 | W16-03, W01-03, W02-04, W07-02, W07-03, W13-04, W15-04, W14-03 |
| 6 | [W16-07](docs/execution/05b-recording-workflow.md#w16-07) | finish 컴파일 통합·복구/재컴파일 새 버전 | W16-06, W29-06, W30-04, W16-04 |
| 7 | [W29-03](docs/execution/06-replay-packages.md#w29-03) | trusted driver IPC·lease·capture dispatch | W29-02, W07-02, W01-02, W13-04 |
| 8 | [W27-01](docs/execution/10-retention-and-release-gates.md#w27-01) | 중복·늦은 event·finish·복구 경합 matrix | W26-05, W22-04 |

외부 환경 탐색보다 준비된 bootstrap/core를 우선한다. 이 표가 끝나거나 전부 막혔다고 전체 진행을 중단하지 않는다.
[TASK_INDEX](docs/execution/TASK_INDEX.json)를 로컬 코드로 조회해 ID/선행/상태/환경/등급의 **후보 요약만** 확인한다. 전체 JSON/과거 audit를 context에 넣지 않는다.

## 외부 대기와 보존할 경계

| 대상 | 상태·재개 조건 | 막히는 범위 |
|---|---|---|
| W01-02 | blocked. 같은 PC VM의 실제 script/driver 격리 검증 가능 시 [인계](docs/validation/tasks/W01-02.md)에서 재개 | 해당 Web native 가지와 실제 통합 gate |
| 민감 캡처 | 픽셀 정제 coverage 제공자 연결 전 차단. [수정 결과](docs/validation/reviews/2026-11-01-remediation-result.md#다음-작업자가-지킬-한계) 참고 | 민감 화면의 실제 authoring/증거 전송. 독립 broker/core는 계속 |

진짜 선행을 삭제하거나 fixture로 live gate를 대신하지 않는다. 기존 완료 이력과 수정 상세는 인계/진행표에서 필요한 ID만 읽으며 큐에 누적하지 않는다.

## 차단되었을 때 다음 작업 선택

1. 코드로 고칠 수 있는 현재 결함은 범위 안에서 고친다. 외부 환경/권한/입력 때문에 못 하면 blocked로 기록한다.
2. 차단 ID·원인·재개 조건·영향 ID·인계 경로를 위 외부 대기에 남기고 카드/TASK_INDEX 상태를 맞춘다. blocked를 complete로 바꾸지 않는다.
3. Next에서 **미완료·blocked 아님·모든 직접 선행 complete+인계 보유·알려진 unavailable 환경 요구 없음**인 후보를 고른다.
4. Next에 준비 후보가 없으면 전체 색인에서 같은 조건으로 bootstrap→core→환경 준비된 integration 순으로 조회한다. 숫자가 앞선 blocked를 계속 Current에 두지 않는다.
5. 준비된 독립 ID를 Current로 이동하고 선택 이유를 짧게 적는다. 차단 항목은 대기에 유지한다. 후보도 없을 때만 필요한 재개 조건을 보고한다.
6. 다른 작업이 외부 차단을 사실상 소비한다면 진짜 선행을 지우지 않는다. core 계약 구현과 live 검증은 카드의 등급/담당에 따라 분리한다.
7. 환경 변경/새 근거가 있을 때만 해당 가지를 재평가한다. 실제 VM/USB/AI 검증·격리·QA 기준을 생략해 완료하지 않는다.

## 매 실행의 최소 입력과 종료

1. 이 파일→Current 카드→지정 CONTRACTS 절→직접 선행 인계의 interface/검증/제약만 읽는다. 관련 현재 코드/저장소 지침을 확인한다.
2. Current 하나를 구현·검증한다. `bootstrap/core_contract`는 실제 local app/API/DB/파일/브라우저로 검사하고 외부 관찰 fixture를 실제 native 근거로 기록하지 않는다. live/final은 해당 실제 evidence가 필수다.
3. `docs/validation/tasks/<ID>.md`에 변경 파일·제공 interface·명령/결과·검증 등급/fixture 여부·미완료/재개 조건을 기록한다. 필요 시 [인계 형식](docs/execution/HANDOFF.md#완료-인계-파일)만 읽는다.
4. 카드 체크·TASK_INDEX·[WORK_PROGRESS](WORK_PROGRESS.md)를 맞춘다. 부모 W는 소속 leaf뿐 아니라 parent_gate_tasks/원래 통합 조건이 끝나야 완료다.
5. 완료면 다음 준비 후보로 이동한다. 미완료지만 외부 차단이 아니면 Current/재개 지점을 유지한다. 외부 차단이면 위 규칙으로 **다음 독립 후보로 전환**한다.
6. Current를 바꿀 때 ID/상태/카드 링크/필수 계약/선행/인계/다음 후보/Updated를 함께 갱신하고 Next는8개 이내로 보충한다. 새 Current 선택은 착수/완료가 아니다.
7. 한 실행 후 멈추며 사용자가 연속 실행을 요청한 경우만 다음 Current를 이어간다. 최종 보고는 수행ID/결과/차단·재개조건/갱신 Current/다음 후보를 간결히 적는다.
8. 계약 변경/새 결함은 소유 spec·카드/소비자·추적표를 맞추고 영향받은 완료 항목만 재개한다. 사용자 DB 초기화·이력 삭제·새 인프라/권한/구매/배포를 범위 밖에서 임의 수행하지 않는다.

[독립 진행/선행 변경 상세](docs/execution/SCHEDULING.md). 제품 경로에 fake adapter/가짜 PASS를 넣거나 live gate를 건너뛰지 않는다.

## Cursor에 전달할 한 문장

```text
NEXT_ACTION.md의 Current 하나를 구현·검증하고 인계와 큐를 갱신해줘. 외부 차단이면 근거/재개 조건을 남긴 뒤, 선행이 충족된 독립 후보로 Current를 바꿔줘. bootstrap/core 검증과 실제 VM·기기·모델 검증을 구분하고 완료 기록은 보존해줘.
```
