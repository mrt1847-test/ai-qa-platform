# Next Actions

Updated: **2026-10-31 (Asia/Seoul)** — v0.7의 158개 상세 작업을 한 번에 하나씩 실행하기 위한 큐를 추가했다. **Current와 실행 우선순위는 이 파일만 관리한다.**

이 파일은 실행 요청을 받았을 때의 진입점이다. 상세 범위/완료 기준은 해당 작업 카드, 선행 관계/상태는 TASK_INDEX, 전체 진행률은 WORK_PROGRESS가 소유한다. 이번 큐 작성으로 제품 작업을 시작하거나 완료 처리하지 않는다.

## Current

**W01-01 — 공개 원본과 출력·쓰기 경계 목록.** 상태: `not_started`. 다음 후보: **W01-02**.

- 범위·완료 기준: [활성 작업서의 W01-01](docs/execution/01-foundation-probes.md#w01-01) 절 하나.
- 필요한 공통 계약: [CONTRACTS](docs/execution/CONTRACTS.md)의 **C00 / C01 / C05 / C07**만.
- 직접 선행: 없음. 기존 공개 코드 조사와 지정 SHA를 바탕으로 실제 파일/함수/출력·쓰기/행동 경계를 확인한다.
- 완료 인계: `docs/validation/tasks/W01-01.md`에 실제 결과/검증/제공 interface/제약을 기록한다. 아직 존재하거나 통과한 근거가 아니다.
- 시작 시 현재 branch/commit·dirty 파일·적용되는 저장소 지침을 확인하고, 기존 변경을 보존한다.

현재 제품 작업은 **0/158**, 상위 W는 **0/32**다. 기존 `prototype/`는 v0.5 모의 샘플이며 실제 DB/engine/격리/replay 구현으로 세지 않는다. 문서 검증 통과를 실제 기기/모델/제품 시험 통과로 해석하지 않는다.

## Next

아래는 가까운 후보8개다. **지금 모두 실행 가능한 목록이 아니다.** 앞선 작업의 실제 완료 근거와 직접 선행이 충족된 때만 Current로 올린다.

| 순서 | ID | 목표 | 직접 선행 |
|---|---|---|---|
| 1 | [W01-02](docs/execution/01-foundation-probes.md#w01-02) | 같은 PC VM과 신뢰 driver 통신 탐색 | W01-01 |
| 2 | [W01-03](docs/execution/01-foundation-probes.md#w01-03) | Web authoring 산출물의 계측 IPC 변환 탐색 | W01-02 |
| 3 | [W01-04](docs/execution/01-foundation-probes.md#w01-04) | Web 직접 replay 가능성·채택 판정 | W01-03 |
| 4 | [W02-01](docs/execution/01-foundation-probes.md#w02-01) | 지정 USB 기기 관찰·serial 경계 | W01-04 |
| 5 | [W02-02](docs/execution/01-foundation-probes.md#w02-02) | 좌표 변환·tap/swipe/back 탐색 | W02-01 |
| 6 | [W02-03](docs/execution/01-foundation-probes.md#w02-03) | 한글·비밀 참조 입력·IME 복구 | W02-02 |
| 7 | [W02-04](docs/execution/01-foundation-probes.md#w02-04) | Android authoring trace·replay 지원표 | W02-03 |
| 8 | [W03-01](docs/execution/01-foundation-probes.md#w03-01) | 역할별 모델 binding 호환 판정 | W02-04 |

나머지 작업은 [상세 작업 색인](docs/execution/TASK_INDEX.json)에서 큐 갱신에 필요한 ID/직접 선행/상태만 조회한다. JSON 전체를 대화 context에 출력하지 않는다. 카드/영역 문서의 배열 순서나 ID 숫자를 실행 순서로 간주하지 않는다.

큐를 보충할 때는 기존 Next의 우선순위를 유지하되 선행이 충족된 작업을 먼저 선택한다. 후보가 없으면 미완료 작업 중 직접 선행과 실제 인계가 준비된 작업을 찾아 선택 이유를 Current에 짧게 남긴다. W06-10→W06-02, W23-01→W09-04, W16-05→W29/W30→W16-07의 첫 사용/통합 선행도 유지한다.

## 보존할 진행 상태와 외부 대기

완료된 제품 작업과 외부 대기 기록은 아직 없다. 실제 구현 뒤 재개에 꼭 필요한 제약만 여기에 남긴다. 완료 이력은 큐에 누적하지 않고 각 작업 인계/진행표에서 관리한다.

- 미완료/검증 중이면 Current를 유지하고 재개 지점을 실제 인계에 기록한다.
- 외부 장비/키/정책 등으로 차단되면 해당 ID·차단 원인·재개 조건·영향받는 후속 ID·인계 경로를 이 절에 남긴다. 추측으로 PASS/완료 처리하지 않는다.
- 선행을 공유하지 않는 기존 계획의 준비된 작업이 있으면 그 ID를 Current로 올릴 수 있다. 차단 항목은 이 절에 남기며, 독립 작업도 없으면 차단된 Current를 유지한다.
- 이미 완료된 구현/근거는 재사용한다. 변경 영향이나 실제 결함 없이 완료 작업을 다시 만들거나 일괄 미완료로 되돌리지 않는다.

## 매 실행의 최소 입력과 종료

1. 이 파일 → Current 카드 한 절 → 지정 CONTRACTS 절 → 직접 선행의 인계 중 interface/검증/제약만 읽는다. 관련 현재 코드와 저장소 지침을 확인한다. 과거 감사/보관본/전체 설계를 연쇄로 읽지 않는다.
2. Current 하나를 구현·검증한다. 카드 밖 작업은 해당 담당 ID에 남긴다. UI는 실제 조작/상태/API 저장 연결, DB는 실제 제약/통합, 기기·격리는 필요한 실제 환경 증거로 판정한다. 명령이 성공했어도 필수 검사가 SKIP/모의/미실행이면 완료가 아니다.
3. `docs/validation/tasks/<ID>.md`에 변경 파일·실제 검사/결과·interface·남은 제한·재개/다음 조건을 남긴다. 자세한 형식이 필요할 때만 [HANDOFF의 완료 인계](docs/execution/HANDOFF.md#완료-인계-파일)를 읽는다. 비밀값/hidden reasoning 원문을 기록하지 않는다.
4. 완료하면 카드 체크·[TASK_INDEX](docs/execution/TASK_INDEX.json)의 해당 상태·[WORK_PROGRESS](WORK_PROGRESS.md)의 수치를 함께 갱신한다. 그 W의 상세 작업 전부와 통합 조건이 끝났을 때만 부모 W를 완료한다.
5. 이 파일에서 완료된 Current를 제거하고 선행이 충족된 다음 미완료를 Current로 이동한다. **ID·상태·작업서 링크·필수 계약 절·직접 선행·인계 경로·다음 후보·Updated를 함께 교체**하고 Next는 가까운 후보8개 이내로 보충한다. 새 Current를 선택했다고 그 작업을 시작한 것으로 표시하지 않는다.
6. 미완료면 Current를 유지하고 실제 재개 지점/차단 조건을 갱신한다. 최종 보고에는 수행 ID/결과/미완료·갱신한 Current/다음 후보만 간결히 적는다. 한 실행이 끝나면 멈추고 다음 Current의 자동 실행은 사용자가 연속 실행을 요청한 경우에만 한다.
7. API/DB/도메인/사용자 계약이 바뀌면 소유 spec·공통 계약·소비 카드·추적표를 같은 변경에서 맞춘다. 새 결함은 중복을 확인해 범위/선행/완료 기준을 가진 수정 단위로 편성한다. 영향받은 완료 작업만 재개한다.
8. 사용자 DB 초기화·이력 삭제·새 인프라/권한·모델 구매/예산 확대·배포는 Current 요청의 범위와 기존 사용자 허용을 확인한다. 범위를 넘는 조작을 임의로 수행하지 않는다. 실제 quota/rate limit은 기록하고 설정을 몰래 재설정해 우회하지 않는다.

## Cursor에 전달할 한 문장

```text
NEXT_ACTION.md를 읽고 Current 하나만 작업해줘. 지정된 작업 카드와 필요한 계약/선행 인계만 읽고 구현·검증한 뒤, 결과 인계와 진행 상태를 저장하고 NEXT_ACTION.md의 Current/Next를 갱신해줘. 미완료면 Current를 유지하고 재개 조건을 남겨줘.
```
