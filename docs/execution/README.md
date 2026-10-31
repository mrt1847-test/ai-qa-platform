# 작은 컨텍스트 모델을 위한 실행 작업서 v0.7

기준일: **2026-10-31** · 제품 설계: **v0.6 + 이번 보완 계약** · 제품 구현: **미착수**.
[상위 진행표](../../WORK_PROGRESS.md) · [설계](../../DESIGN.md) · [기존 T 계획](../../IMPLEMENTATION_PLAN.md).

기존 32개 W는 상위 기능 묶음이다. 실제 모델에게는 **158개 상세 작업 중 한 ID만** 맡긴다.
이전 채팅이나 전체 설계 문서를 기억한다는 가정으로 작성하지 않는다.
새 기능 추가보다 담당 누락·불명확한 계약·선행 충돌을 찾아 보완하는 것이 이번 개정의 목적이다.

**매 실행의 진입점과 Current/우선순위는 [NEXT_ACTION](../../NEXT_ACTION.md) 하나다.** 이 README/WORK_PROGRESS/TASK_INDEX는 범위·상태·선행을 제공하며 별도 실행 큐를 만들지 않는다.

## 1. 문서 역할과 읽는 순서

| 문서 | 읽는 때 | 역할 |
|---|---|---|
| [NEXT_ACTION](../../NEXT_ACTION.md) | 매 시작/종료 | Current 하나·가까운 후보·최소 입력·종료 후 큐 갱신 |
| [WORK_PROGRESS](../../WORK_PROGRESS.md) | 관리자/진행 갱신 | 32개 W와 영역별 진행·통합 검수 |
| 이 README | 첫 시작 | 작업 선택·상태·완료 방법 |
| [CONTRACTS](CONTRACTS.md) | 매 작업의 지정 절만 | 공통 DTO/API/상태/한도·보완 결정 |
| 아래 영역별 작업서 | 담당 카드만 | 선행 ID·변경 파일·계약·행동·시험·완료 |
| [HANDOFF](HANDOFF.md) | 매 시작/종료 | 모델에 전달할 최소 자료·구현 인계 양식 |
| [UI_COVERAGE](UI_COVERAGE.md) | UI 작업/검수 | 16화면+공통의94개 조작·상태 묶음 담당 |
| [COVERAGE](COVERAGE.md) | 영역 종료/최종 검수 | P0 32개/P1 3개·UI21/DATA22/실행10 대응 |
| [REVIEW](REVIEW.md) | 계약 변경/최종 검수 | 발견한 누락/모순·보완·남은 실제 gate |
| [VALIDATION](VALIDATION.md) | 문서 확인 | ID/선행/원문/담당/링크/예시의 실제 문서 검사 결과 |
| [TASK_INDEX.json](TASK_INDEX.json) | 작업 선택/자동 대조 | 158개 ID·선행·파일·계약·검증 기대·상태의 문서 색인 |

**상태 원본:** 각 카드의 완료 체크와 `docs/validation/tasks/{ID}.md`의 실제 근거다.
TASK_INDEX의 status와 root 요약도 같은 작업 종료 시 함께 갱신한다. Current/Next는 NEXT_ACTION에만 둔다. JSON은 제품 실행 configuration이 아니다.
작업자가 전체 14개 영역을 읽거나 JSON 전체를 context에 넣을 필요는 없다.

## 2. 영역별 작업서

| 영역 | 상위 W | 상세 작업 | 현재 완료 |
|---|---|---:|---:|
| [A · 공개 코드·모델·연결 탐색](01-foundation-probes.md) | W01 W02 W03 | 11 | 0 |
| [B-1 · 권한·케이스·TC·환경·data](02a-assets-and-scope.md) | W04 W05 | 10 | 0 |
| [B-2 · 자원·REC·job·증거·장기 facts schema](02b-job-evidence-schema.md) | W06 | 10 | 0 |
| [C · 세션·작업 큐·중단](03-worker-and-sessions.md) | W07 W08 W09 | 13 | 0 |
| [D-1 · 프로젝트·케이스·설정·선택 TC UI](04a-case-management-ui.md) | W10 | 11 | 0 |
| [D-2 · 환경·기기·앱·data·launcher UI](04b-environments-and-launcher.md) | W11 W12 | 11 | 0 |
| [E-1 · 행동·증거·spool·모델 계측](05a-action-evidence-and-models.md) | W13 W14 W15 | 12 | 0 |
| [E-2 · 녹화 입력·진행·저장·재녹화](05b-recording-workflow.md) | W16 | 8 | 0 |
| [F · 승인 package·모델 없는 재생](06-replay-packages.md) | W29 W30 | 10 | 0 |
| [G · 시범·사후 검토·승인](07-trial-and-review.md) | W17 W18 W19 | 13 | 0 |
| [H-1 · 선택 셀프힐링·제안](08a-self-healing.md) | W31 | 6 | 0 |
| [H-2 · 정식·선택·묶음·취소·재실행](08b-execution-and-suites.md) | W20 W21 W22 | 13 | 0 |
| [I · 결과·분석·내보내기](09-results-and-analytics.md) | W23 W24 W25 | 13 | 0 |
| [J · 보관·장애·비용·최종 동선](10-retention-and-release-gates.md) | W26 W27 W32 W28 | 17 | 0 |
| 합계 | W01–W32 | **158** | **0** |

큰 순서는 A→B→C→D→E→F→G→H→I→J다. **실제 선행은 카드의 leaf ID만 권위가 있다.**
예외: W29/W30은 W16-05의 sealed source로 시작하고, W16-07은 W29-06/W30-04 뒤 finish에 compiler를 통합한다.
그래서 W16 전체 완료를 W29의 선행으로 걸면 안 된다. W10-11은 ID상 뒤지만 W10-08 다음에 실행한다.
결과 산식 kernel W23-01은 W06-06 뒤·W09-04의 첫 사용 전에 구현한다. W06-10은 resource 기본 schema라 W06-02보다 먼저다. 숫자를 단순 정렬해 시키지 않는다.

처음 실행할 작업은 **[W01-01](01-foundation-probes.md#w01-01)**다. 새 작업은 모든 선행 ID가 완료/근거 보유인 것에서 고른다.
원본의 제품 코드는 아직 없으므로 파일 경로/시험은 앞으로 만들 산출물이다.

## 3. 모델에게 한 번에 전달할 범위

1. NEXT_ACTION의 Current를 선택한다. 추가 요청서가 필요할 때만 [HANDOFF의 요청 템플릿](HANDOFF.md#요청-템플릿)에 해당 ID와 현재 저장소 revision을 적는다.
2. 해당 카드 전체 + 지정 CONTRACTS 절 + 직접 선행 작업의 interface/검증/제약 인계만 제공한다.
3. 관련 현재 코드·실제 저장소 지침을 읽게 한다. 존재하는 코드를 읽지 않고 계획대로 덮어쓰게 하지 않는다.
4. 목표는 한 기능의 독립 검증 가능한 변경이다. 카드 밖의 다음 기능·리팩터링·설치/배포를 자동 확장하지 않는다.
5. 작업 팩이 모델 context의 절반을 넘으면 관련 계약 절을 줄여 별첨하거나 이 카드만 추가 분할한다. 설계 결정을 생략하거나 중요 제약을 요약에서 지워서는 안 된다.

영역별 문서는 관리용 묶음이다. 한 영역 전체를 한 요청으로 맡기는 문서가 아니다.
모델 전용 skill/기억/플러그인은 필수 조건이 아니다. 사용하는 실행 환경의 지침은 별도로 준수한다.

## 4. 카드의 검증 예시를 해석하는 법

각 카드의 `observed`는 **시험 전제의 실제 API 응답/DB 조회/driver journal/파일/process 증거에서 얻은 검증용 projection**이다.
제품 DTO에 그 검사 key를 모두 넣으라는 뜻이 아니고, expected 상수를 observed로 복사해서도 안 된다.
지정 시험 함수는 여러 입력을 parameterize할 수 있다. 시간/한도는 fake clock으로 경계 검사하고, 실제 VM/USB/capture/차단 증명은 별도 live 근거를 남긴다.
합격 projection뿐 아니라 전제에 나열한 거부/충돌 입력도 각각 재현해야 한다.
카드의 contract에 처음 등장하는 지역 DTO는 그 카드가 정의·검사하고 receipt에 schema를 남긴다. 공통 DTO는 CONTRACTS를 따른다. 후속 작업이 추측해 다른 필드를 만들면 안 된다.

## 5. 진행·완료·변경

상태는 `not_started / in_progress / verifying / complete / blocked`다. blocked는 이유·필요 장비/키/결정·영향 ID를 기록한다.
한 단계의 smoke test만으로 뒤 단계의 UI·실행·승인까지 완료 처리하지 않는다.
read-only shell/tab 완료와 그 안의 실제 기능 완료는 담당 ID가 다르다.
실제 구현 요청이 있기 전에는 모두 미착수이며, 이 문서 작성/정합성 점검은 제품 진행률에 포함하지 않는다.

- 상세 진행률: **완료0 / 158**.
- 상위 진행률: **완료0 / 32 W**. 해당 W의 상세 전부와 통합 조건이 충족된 때만 체크한다.
- 기능 누락 발견 시 기존 카드 안에 숨기지 말고 새 ID/선행/UI·요구 매핑/기대를 먼저 보완한다. 분모 변경을 기록한다.
- 요구 변경 시 root 설계와 계약/카드/추적표를 함께 바꾸고, 이미 완료한 영향 작업은 재개한다.
- 커밋/PR/배포는 실제 구현 시 사용자의 지시와 저장소 지침을 따른다. 문서가 자동 실행 승인은 아니다.
