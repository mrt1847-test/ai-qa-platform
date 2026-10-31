# 작은 컨텍스트 모델을 위한 실행 작업서 v0.8

기준일: **2026-11-01** · 제품 설계: **v0.6 + 보완 계약** · 현재: **완료53/163**, W00·W04·W05·W06·W08·W10 상위 완료, W01-02 외부 차단 보존.
[Current 큐](../../NEXT_ACTION.md) · [상위 진행표](../../WORK_PROGRESS.md) · [선행/차단 수정](SCHEDULING.md).

**프로젝트 실행 뼈대4개를 먼저 만든다.** 기존 source 조사/부분 probe 코드는 재사용한다.
33개 상위 W 아래163개 leaf 중 한 개씩 맡기며, VM 차단이 독립 DB/큐/관리 UI까지 막지 않게 한다.

## 1. 읽는 순서와 소유

| 문서 | 언제 | 역할 |
|---|---|---|
| [NEXT_ACTION](../../NEXT_ACTION.md) | 매 시작/종료 | Current/Next·차단 대기·독립 후보 선택 |
| 담당 영역 카드 | 매 작업 | 파일·선행·scope·검증·완료 |
| [CONTRACTS](CONTRACTS.md) | 카드 지정 절만 | C00–C14, C13뼈대/C14차단·검증 등급 |
| [HANDOFF](HANDOFF.md) | 인계 형식이 필요할 때 | 실제 결과/미완료/재개 기록 |
| [TASK_INDEX](TASK_INDEX.json) | 후보/상태 조회 | 직접 선행·환경·검증 등급·부모 gate |
| [WORK_PROGRESS](../../WORK_PROGRESS.md) | 진행 갱신 | 33W/영역별 요약·상위 통합 검수 |
| [UI_COVERAGE](UI_COVERAGE.md) / [COVERAGE](COVERAGE.md) | 구현/영역 검수 | UI94/요구R35/규범53개 담당 |
| [SCHEDULING](SCHEDULING.md) | 순서·차단 확인 | 뼈대 추가/의존 수정·기존 근거 보존 |
| [REVIEW](REVIEW.md) / [VALIDATION](VALIDATION.md) | 문서 확인 | 보완/문서 정합성 결과 |

카드/인계/TASK_INDEX 상태·진행표·Current를 함께 맞춘다. 전체 JSON/다른 영역의 전체 원문/이전 채팅을 한 context에 넣지 않는다.

## 2. 영역별 작업서

| 영역 | W | 상세 | 완료 |
|---|---|---:|---:|
| [0 · 최소 실행 기반](00-bootstrap.md) | W00 | 4 | 4 |
| [A · 공개 코드·모델·연결 탐색](01-foundation-probes.md) | W01 W02 W03 | 11 | 1 |
| [B-1 · 권한·케이스·TC·환경·data](02a-assets-and-scope.md) | W04 W05 | 10 | 10 |
| [B-2 · 자원·REC·job·증거·장기 facts schema](02b-job-evidence-schema.md) | W06 | 10 | 10 |
| [C · 세션·작업 큐·중단](03-worker-and-sessions.md) | W07 W08 W09 | 13 | 9 |
| [D-1 · 프로젝트·케이스·설정·선택 TC UI](04a-case-management-ui.md) | W10 | 11 | 11 |
| [D-2 · 환경·기기·앱·data·launcher UI](04b-environments-and-launcher.md) | W11 W12 | 11 | 0 |
| [E-1 · 행동·증거·spool·모델 계측](05a-action-evidence-and-models.md) | W13 W14 W15 | 12 | 8 |
| [E-2 · 녹화 입력·진행·저장·재녹화](05b-recording-workflow.md) | W16 | 8 | 0 |
| [F · 승인 package·모델 없는 재생](06-replay-packages.md) | W29 W30 | 10 | 0 |
| [G · 시범·사후 검토·승인](07-trial-and-review.md) | W17 W18 W19 | 13 | 0 |
| [H-1 · 선택 셀프힐링·제안](08a-self-healing.md) | W31 | 7 | 0 |
| [H-2 · 정식·선택·묶음·취소·재실행](08b-execution-and-suites.md) | W20 W21 W22 | 13 | 0 |
| [I · 결과·분석·내보내기](09-results-and-analytics.md) | W23 W24 W25 | 13 | 0 |
| [J · 보관·장애·비용·최종 동선](10-retention-and-release-gates.md) | W26 W27 W32 W28 | 17 | 0 |
| 합계 | W00–W32 | **163** | **53** |

첫 구현은 [W00-01](00-bootstrap.md#w00-01)→W00-02→W00-03→W00-04다.
그 뒤 준비된 core/환경 가지를 NEXT_ACTION이 선택한다. W01-01은 이미 완료되어 반복하지 않는다.
W01-02 VM 부재는 대기에 보존하고 W15-01부터의 model broker 경로를 진행한다. W11-01의 선행은 끝났고 이번 Current는 W15-01이다. W09-04는 W23-01이 끝나기 전에 Current가 되지 않는다.
실제 선행만 권위가 있으며 ID/영역 순서를 전체 직렬 gate로 쓰지 않는다.

## 3. 한 번의 입력과 실행

Current 카드 전체 + 지정 계약 절 + 직접 선행 인계의 interface/검증/제약 + 관련 현재 코드를 읽는다.
영역 전체를 한 번에 구현하라고 하지 않는다. 팩이 context 절반을 넘으면 참조를 더 좁히거나 해당 카드만 나누고 중요한 제약을 지우지 않는다.
W00은 현재 src/tests를 빈 scaffold로 덮지 않고 필요한 차이만 만든다.
외부 차단이면 C14/큐 규칙에 따라 대기 기록을 남기고 준비된 독립 Current로 전환한다.

## 4. 카드의 검증 예시를 해석하는 법

`observed`는 해당 scope의 실제 API/DB/파일/process/브라우저 결과에서 얻는 검사 projection이다.
기대 상수를 복사하거나 그 검사 key를 제품 DTO에 모두 넣는 뜻이 아니다.
core는 tests 전용 외부 입력 fixture를 쓸 수 있지만 native/model 실행 근거로 쓰지 않는다.
production의 없는 adapter/키/근거는 unavailable/BLOCKED/unknown으로 표시하고 fake 성공으로 대체하지 않는다.
실제 수용은 카드의 live_acceptance_tasks 및 live/final gate를 따른다.
동일상태의 parent는 소속 leaf+parent_gate_tasks/상위 통합 조건이 모두 충족돼야 완료다.

## 5. 상태와 보존

상태는 not_started/in_progress/verifying/complete/blocked다.
완료는 인계와 필수 scope 검사 근거가 있어야 한다. 외부 차단은 다음 독립 작업을 막지 않지만 진짜 소비자의 선행도 충족시키지 않는다.
현재 W00-01–04와 W00 상위, W01-01, W04-01–04와 W04 상위, W05-01부터 W05-06과 W05 상위, W06-01, W06-10, W06-02부터 W06-09와 W06 상위, W07-01, W08-01부터 W08-05와 W08 상위, W09-01부터 W09-03, W10-01부터 W10-03은 complete다. W01-02 blocked와 기존 code/인계는 보존한다. 추가 live gate는 아직 미착수다.
문서 변경을 제품 진척으로 세지 않는다. 새 구현에서 scope·계약이 바뀌면 소비자/추적표/진행률을 함께 수정한다.
