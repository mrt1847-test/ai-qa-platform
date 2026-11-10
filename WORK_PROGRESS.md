# AI QA 플랫폼 작업 진행표 v0.8

> **등록 PC 전환:** [PC-01](docs/validation/tasks/PC-01.md)·[PC-02](docs/validation/tasks/PC-02.md)·[PC-03](docs/validation/tasks/PC-03.md)의 core와 [PC-04](docs/validation/tasks/PC-04.md)의 소스 조사·설계를 완료했다(전환 4/4). [등록 PC 구현과 실환경 수용](docs/managed-pc/IMPLEMENTATION_TASKS.json)은 별도 83/95이며 [NEXT_ACTION](NEXT_ACTION.md)에서 현재 작업을 확인한다. [RX-01](docs/validation/tasks/RX-01.md)~[RX-20](docs/validation/tasks/RX-20.md)·[RX-28](docs/validation/tasks/RX-28.md)·[RX-30](docs/validation/tasks/RX-30.md)~[RX-78](docs/validation/tasks/RX-78.md) 로컬/현재 PC 배선·제품 흐름 이력 보존. [기능 구현 RX-47~62](docs/managed-pc/PRODUCT_FLOW_TASKS.md)는 16/16, 실환경 수용 RX-21~27·RX-29는 0/8이다. [정상 진입점 보완 RX-63~71](docs/managed-pc/ENTRY_COMPLETION_TASKS.md)은 9/9이며 전체 기능 구현 트랙은 45/49다. [결과·자원 복귀·실제 driver RX-72~78](docs/managed-pc/RESULTS_AND_NATIVE_TASKS.md)은 7/7이다. [실행 준비 UI·회귀 보완 RX-79~91](docs/managed-pc/UI_EXECUTION_TASKS.md)은 9/13이다. 실제 외부 조건은 [ACCEPTANCE_RESUME](docs/validation/tasks/ACCEPTANCE_RESUME.md)에 보존한다.
> Android 개발/누락 UI 보완 7개는 [별도 카드](docs/execution/11-development-follow-ups.md)·[별도 색인](docs/execution/DEV_FOLLOW_UP_INDEX.json)을 따른다. AD-01·UX-01·UX-02·UX-03 완료(4/7)와 기존 W 완료 126/163을 보존한다. AD-02~04의 실제 등록 PC 적용은 [RX 매핑](docs/managed-pc/RUNTIME_BOUNDARIES.md#카드-선택과-기존-이력)에 있고 UX는 공유 제품 보완이다.

> UI 개선 및 병합 검증은 [결과](docs/validation/ux/README.md)를 참고한다. 아래 완료 수는 최신 master 작업 근거를 따르며 UI 변경으로 추가하지 않는다.

기준일: **2026-11-02 (Asia/Seoul)** · 기존 local baseline **완료126/163**, 상위6/33 W. 이 수는 cloud MVP 진행률이 아니다. [확정 배치](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md)·[PC 작업 계획](docs/superpowers/plans/2026-11-02-managed-pc-transition.md)에 따라 전환하며 cloud 실제 수용은 미검증이다.

**실행 진입점/Current는 [NEXT_ACTION](NEXT_ACTION.md) 하나다.**
[최소 기반4개](docs/execution/00-bootstrap.md)를 먼저 만들고 환경에 막히지 않는 독립 core 경로로 진행한다.
기존 상세 작업은 163개/15영역이다. 초기 전환은 [PC_EXECUTION_INDEX](docs/execution/PC_EXECUTION_INDEX.json)의 별도 4개, 원격 실행 구현·수용은 [RX 색인](docs/managed-pc/IMPLEMENTATION_TASKS.json)의 별도 95개로 추적한다.

[전체 실행 안내](docs/execution/README.md) · [공통 계약 C13/C14](docs/execution/CONTRACTS.md) · [선행/차단 수정](docs/execution/SCHEDULING.md) · [UI 추적](docs/execution/UI_COVERAGE.md) · [요구 추적](docs/execution/COVERAGE.md)

2026-11-01 검토 후 [R01~R20/V01 보완](docs/validation/reviews/2026-11-01-remediation-result.md)을 구현·검증했다. 기존 53개 완료의 결함 수정이다. 과거 VM/기기/모델 수용 gate를 보존한다.

## 1. 현재 상태

| 구분 | 상태 |
|---|---|
| 기존 source 조사 | W01-01 complete, [인계](docs/validation/tasks/W01-01.md)/코드 보존 |
| 외부 대기 | W01-02 blocked, [VM 근거](docs/validation/tasks/W01-02.md) 보존 |
| 제품 최소 앱 | W00 완료(상세4/4). 엔진·VM·USB 검증은 아님 |
| 상위 작업 | **완료6 / 33 W** |
| 상세 작업 | **완료126 / 163** |
| 실행 지시 대상 | [NEXT_ACTION Current](NEXT_ACTION.md#current) |
| 이후 후보 | [NEXT_ACTION Next](NEXT_ACTION.md#next) |
| 실제 engine/DB/회귀 합격 | source 조사와 구별, 해당 live/통합 gate 근거 필요 |

W00-01–04와 W00 상위, W04-01–04와 W04 상위, W05·W06·W08·W10 상위가 완료되어 있다. W01-01 완료 인계, W01-02 차단 인계, 원본 SOURCE는 유지한다.
[v0.7 변경 전 보관본](docs/history/v0.7-before-bootstrap/WORK_PROGRESS.md)에 기존 상태와 계획을 보관했다.

## 2. 영역과 진행

아래는 영역 요약이며 전체 직렬 순서가 아니다. W00부터 시작하고 직접 선행/환경이 준비된 후보를 큐가 선택한다.

| 영역 | W | 상세 수 | 완료 | 작업서 |
|---|---|---:|---:|---|
| 0 · 최소 실행 기반 | W00 | 4 | 4 | [0 · 최소 실행 기반](docs/execution/00-bootstrap.md) |
| A · 공개 코드·모델·연결 탐색 | W01 W02 W03 | 11 | 1 | [A · 공개 코드·모델·연결 탐색](docs/execution/01-foundation-probes.md) |
| B · 데이터·권한·불변 버전 | W04 W05 W06 | 20 | 20 | [B-1 · 권한·케이스·TC·환경·data](docs/execution/02a-assets-and-scope.md) / [B-2 · 자원·REC·job·증거·장기 facts schema](docs/execution/02b-job-evidence-schema.md) |
| C · 세션·작업 큐·중단 | W07 W08 W09 | 13 | 10 | [C · 세션·작업 큐·중단](docs/execution/03-worker-and-sessions.md) |
| D · 관리 화면·환경·설정 | W10 W11 W12 | 22 | 20 | [D-1 · 프로젝트·케이스·설정·선택 TC UI](docs/execution/04a-case-management-ui.md) / [D-2 · 환경·기기·앱·data·launcher UI](docs/execution/04b-environments-and-launcher.md) |
| E · AI 녹화·먼저 저장·증거 | W13 W14 W15 W16 | 20 | 16 | [E-1 · 행동·증거·spool·모델 계측](docs/execution/05a-action-evidence-and-models.md) / [E-2 · 녹화 입력·진행·저장·재녹화](docs/execution/05b-recording-workflow.md) |
| F · 승인 package·모델 없는 재생 | W29 W30 | 10 | 6 | [F · 승인 package·모델 없는 재생](docs/execution/06-replay-packages.md) |
| G · 시범·사후 검토·승인 | W17 W18 W19 | 13 | 11 | [G · 시범·사후 검토·승인](docs/execution/07-trial-and-review.md) |
| H · 선택 치유·정식·묶음 수행 | W31 W20 W21 W22 | 20 | 18 | [H-1 · 선택 셀프힐링·제안](docs/execution/08a-self-healing.md) / [H-2 · 정식·선택·묶음·취소·재실행](docs/execution/08b-execution-and-suites.md) |
| I · 결과·분석·내보내기 | W23 W24 W25 | 13 | 13 | [I · 결과·분석·내보내기](docs/execution/09-results-and-analytics.md) |
| J · 보관·장애·비용·최종 동선 | W26 W27 W32 W28 | 17 | 7 | [J · 보관·장애·비용·최종 동선](docs/execution/10-retention-and-release-gates.md) |
| 합계 | **33 W** | **163** | **126** | **15영역** |

`W00-01→02→03→04→W04-01`로 기본 앱과 DB/core를 진행할 수 있다.
W01-02 VM이 없어도 W04–06/queue/관리 UI·core 보고/보관 경로를 전부 묶어 막지 않는다.
실제 source/trial/replay/치유·장애·월간 계측/MVP의 필요한 환경 gate는 남긴다.
W06-10→W06-02, W23-01→W09-04, source→package→finish 통합의 진짜 직접 선행은 그대로 지킨다.

## 3. 한 번의 요청과 완료

1. NEXT_ACTION Current와 해당 카드/지정 계약/직접 선행 인계·관련 현재 코드만 읽는다.
2. scope별 구현과 검사를 수행한다. core는 실제 API/DB/파일/브라우저를 쓰고 외부 관찰 fixture 여부를 명시한다. native gate는 실제 VM/USB/provider 근거가 필요하다.
3. `docs/validation/tasks/<ID>.md`에 변경/검증/제공 interface·scope·미완료/재개 조건을 남긴다.
4. 완료면 카드/TASK_INDEX/진행률을 맞추고 다음 준비 후보로 이동한다.
5. 외부 차단이면 대기 기록을 남기고 **전체 색인에서 독립 준비 후보**를 골라 Current를 전환한다. 독립 후보가 없을 때만 필요한 조건을 보고한다.
6. 부모 W는 소속 leaf 전부와 parent_gate_tasks/원래 상위 조건까지 충족돼야 체크한다.

## 4. 공통 규칙 (Global Constraints)

- 케이스가 검증 정의·실행 설정·녹화 절차·근거를 함께 소유한다. TC 등록/연결은 필수 조건이 아니다.
- 녹화 중 승인은 없으며, 정상/실패/중단/미완성 기록도 먼저 저장한다. `stored`와 녹화 성공·절차 완결·증거 준비·승인을 분리한다.
- 각 tap/type/swipe/back마다 전후 PNG·정제 로그·오류·검증/출처를 연결한다. 비밀값·hidden reasoning 원문을 디스크/전송 전에 차단한다.
- 미승인 시범은 허용하고 정식/회귀는 exact 유효 승인을 요구한다. 시범 PASS/engine done은 사람 승인 또는 다음 수행 PASS가 아니다.
- 재녹화는 같은 케이스의 새 전체 녹화 후보다. 새 승인 전까지 기존 기본본 유지, 승인/default/pin/audit는 원자 확정, 과거 승인 자동 철회·기본본 철회 시 자동 fallback 없음.
- 기존 suite/queued/running RUN의 exact version/approval을 새 승인본으로 자동 교체하지 않는다.
- 단일/선택/묶음은 공통 RUN/ITEM/jobs를 사용한다. REC/관리 job QA는 null, terminal 결과 7종+진행=N, 유효 필수 위반은 FAIL 우선으로 보존한다.
- 전체 attempt 자동 retry0, action retry1, model retry2. 제안 한도600초/action50/model80/USD2.00. 실제 비용·성공률 보장값은 아니다.
- 총 slot1/기기당1, heartbeat10초/lease45초/watchdog30초/행동 전 여유10초. 취소 유예5초/정리30초 내 ready 또는 quarantine.
- 런타임 DB/파일은 비동기화 `%LOCALAPPDATA%/AIQA/`. API 단일 writer·worker HTTP/spool, 개인 모드 API는127.0.0.1. 관리 탭과 runner 수명을 분리한다.
- 장기 최소 facts·승인/lineage·commit cursor를 상세 payload90일/PNG·정제로그30일과 분리한다. 유효한 과거 승인 근거도 보호하고 철회 뒤90일 유예한다.
- 최신 MVP는 독립 관리/저장 서버와 등록 실행 PC의 Web·Android 및 전원 종료 중 저장본 조회/승인 수용이 필요하다. [구현 경계](docs/managed-pc/RUNTIME_BOUNDARIES.md)에 기존 W/AD에서 재사용할 범위를 기록했다. 수동 화면 제어·영상·중간 재개·일반 Skill Factory 추천/자가 코드 변경은 후속이다. 승인 replay·bounded healing 정책은 유지한다.

- 기본 `recorded_replay`는 일반 actor0, verifier는 명시 check에만 호출한다. 결정적 검사/OFF는 모델 키 없이 허용한다. 승인 근거 trial은 healing OFF다.
- healing 기본OFF·승인 capability 범위 안에서 접수 ON/OFF snapshot, 미dispatch lookup 실패/결정적 동일 target만 치유한다. ITEM당episode1/모델 합계2회(전송retry포함)/30초 제안, 전체 job/lease/예산 우선.
- 치유 후 PASS·healing_used는 기존 PASS 부분집합이고 unassisted/원래 오류를 별도로 집계한다. 필수 위반/결과 불명·terminal FAIL을 치유로 덮지 않는다. 제안 재사용은 새 전체 REC/OFF trial/사후 승인이다.
- 월1회3,000 TC×1data×1환경의 최초녹화·반복검증·치유·전체재녹화 비용/시간/저장량을 표본에서 측정한다. 고정 월 예산/모델은 아직 미정이다.

## 5. 특히 놓치면 안 되는 검증 (Review Focus)

| 위험한 상황 | 기대 동작 | 담당 단위 |
|---|---|---|
| 한 step에 여러 tap/type/swipe가 포함됨 | 실제 동작별 화면·로그를 각각 남김 | W13–W14 |
| 같은 project/case의 다른 실행 PNG를 검토에 연결 | exact REC/ITEM/attempt 소속 검사로 거부 | W06, W18–W19 |
| 중단본이 stored이거나 재녹화 후보가 반려됨 | 부분 기록은 조회 가능, 승인 차단, 기존 승인본 유지 | W16, W19 |
| 승인/철회·GC·늦은 업로드·중복 finish가 겹침 | 원자성/멱등성 보장, 원본 hash·기본본·근거 보호 유지 | W14, W16, W19, W26–W27 |
| 재실행 PASS·상세 만료·늦은 비용 보정이 발생 | 원본 FAIL·최소 facts·이전 as_of 집계 보존 | W22–W27 |
| script 우회/미dispatch 오판/제품 FAIL·치유 비용 | driver 독점·dispatch_started 영구 기록·bounded policy·역할별 계측 | W29–W32 |

수치/상태/DTO·API 상세는 [공통 계약 C00–C14](docs/execution/CONTRACTS.md)를 따른다.
특히 action retry는 미dispatch 증명된 전달 전만, 미ACK spool은 7일 자동폐기 대상이 아니다.
원본 정의/절차 편집은 새 draft/package=null, 동일 source 재컴파일은 새 manifest/version이다.

추가 규범은 C13(최소 기반)/C14(차단·검증 등급)다. P0 engine gate는 해당 통합/최종 수용의 gate이며 DB/관리 UI의 허위 선행으로 쓰지 않는다.
fixture 데이터/가짜 성공을 생산 경로에 넣지 않는다. 기존 실제 기록을 문서 정리로 다시 만들거나 무효화하지 않는다.

## 6. 상위 W 체크리스트

한 행은 부모 검수 조건이다. 한 번의 구현 요청은 링크된 leaf 한 개다.
부모 외부 gate는 완료 판정에만 적용하며 독립 core leaf의 진행을 막는 DAG 선행이 아니다.

### W00 — 최소 실행 기반·app/page·smoke

- [x] **W00 완료** — 상세4/4. 기존 코드를 보존하며 패키지 import·최소 API/페이지·실제 시작/종료 검증이 통과하고 실행 안내가 있다. engine/기기 준비를 통과한 뜻은 아니다.
- 상세 작업: [W00-01](docs/execution/00-bootstrap.md#w00-01), [W00-02](docs/execution/00-bootstrap.md#w00-02), [W00-03](docs/execution/00-bootstrap.md#w00-03), [W00-04](docs/execution/00-bootstrap.md#w00-04).

### W01 — CUAWright Web authoring·계측·격리 가능성

- [ ] **W01 완료** — 상세1/4. CUAWright Web authoring/격리/동작 계측·직접 replay의 가능/불가·패치·제약이 기록되어 있다.
- 상세 작업: [W01-01](docs/execution/01-foundation-probes.md#w01-01), [W01-02](docs/execution/01-foundation-probes.md#w01-02), [W01-03](docs/execution/01-foundation-probes.md#w01-03), [W01-04](docs/execution/01-foundation-probes.md#w01-04).

### W02 — Android USB·좌표·입력 가능성

- [ ] **W02 완료** — 상세0/4. 실제 좌표/입력/전후 캡처·Mobile-Agent authoring trace를 Android plan으로 재생할 지원 범위와 Windows 제약이 확인되어 있다.
- 상세 작업: [W02-01](docs/execution/01-foundation-probes.md#w02-01), [W02-02](docs/execution/01-foundation-probes.md#w02-02), [W02-03](docs/execution/01-foundation-probes.md#w02-03), [W02-04](docs/execution/01-foundation-probes.md#w02-04).

### W03 — 모델 형식·upstream 채택 결정

- [ ] **W03 완료** — 상세0/3. 양 플랫폼 필수 capture/행동 경계가 확보되고 모델/엔진 결정이 문서에 반영되어 있다.
- 상세 작업: [W03-01](docs/execution/01-foundation-probes.md#w03-01), [W03-02](docs/execution/01-foundation-probes.md#w03-02), [W03-03](docs/execution/01-foundation-probes.md#w03-03).

### W04 — project scope·API 권한·저장 연결

- [x] **W04 완료** — 상세4/4. 실제 자산 저장과 권한 경계를 확인했고 비밀 원문이 응답/DB definition에 없다. 엔진·VM·USB 검증은 아니다.
- 상세 작업: [W04-01](docs/execution/02a-assets-and-scope.md#w04-01), [W04-02](docs/execution/02a-assets-and-scope.md#w04-02), [W04-03](docs/execution/02a-assets-and-scope.md#w04-03), [W04-04](docs/execution/02a-assets-and-scope.md#w04-04).

### W05 — 케이스·불변 버전·선택 TC·데이터 revision

- [x] **W05 완료** — 상세6/6. 검증 내용·녹화 기록이 한 케이스에 귀속되고 별도 TC gate가 없다. 엔진·VM·USB 검증은 아니다.
- 상세 작업: [W05-01](docs/execution/02a-assets-and-scope.md#w05-01), [W05-02](docs/execution/02a-assets-and-scope.md#w05-02), [W05-03](docs/execution/02a-assets-and-scope.md#w05-03), [W05-04](docs/execution/02a-assets-and-scope.md#w05-04), [W05-05](docs/execution/02a-assets-and-scope.md#w05-05), [W05-06](docs/execution/02a-assets-and-scope.md#w05-06).

### W06 — 녹화·수행·증거·장기 facts schema

- [x] **W06 완료** — 상세10/10. 서비스가 임시 JSON/메모리 저장소를 새 사실 원천으로 만들 필요가 없다. 엔진·VM·USB 검증은 아니다.
- 상세 작업: [W06-01](docs/execution/02b-job-evidence-schema.md#w06-01), [W06-10](docs/execution/02b-job-evidence-schema.md#w06-10), [W06-02](docs/execution/02b-job-evidence-schema.md#w06-02), [W06-03](docs/execution/02b-job-evidence-schema.md#w06-03), [W06-04](docs/execution/02b-job-evidence-schema.md#w06-04), [W06-05](docs/execution/02b-job-evidence-schema.md#w06-05), [W06-06](docs/execution/02b-job-evidence-schema.md#w06-06), [W06-07](docs/execution/02b-job-evidence-schema.md#w06-07), [W06-08](docs/execution/02b-job-evidence-schema.md#w06-08), [W06-09](docs/execution/02b-job-evidence-schema.md#w06-09).

### W07 — 실제 환경 adapter·session 수명

- [ ] **W07 완료** — 상세1/4. 관리 UI 탭과 테스트 session이 분리되고 정리 실패 자원을 재배정하지 않는다.
- 상세 작업: [W07-01](docs/execution/03-worker-and-sessions.md#w07-01), [W07-02](docs/execution/03-worker-and-sessions.md#w07-02), [W07-03](docs/execution/03-worker-and-sessions.md#w07-03), [W07-04](docs/execution/03-worker-and-sessions.md#w07-04).
- 상위 실제 수용 gate: [W07-04](docs/execution/03-worker-and-sessions.md#w07-04). core leaf만으로 부모를 완료하지 않는다.

### W08 — 영구 job queue·claim·lease·중복 방지

- [x] **W08 완료** — 상세5/5. 재접수/재연결 때문에 같은 외부 행동을 추가 실행하지 않는다. 엔진·VM·USB 검증은 아니다.
- 상세 작업: [W08-01](docs/execution/03-worker-and-sessions.md#w08-01), [W08-02](docs/execution/03-worker-and-sessions.md#w08-02), [W08-03](docs/execution/03-worker-and-sessions.md#w08-03), [W08-04](docs/execution/03-worker-and-sessions.md#w08-04), [W08-05](docs/execution/03-worker-and-sessions.md#w08-05).

### W09 — 취소·watchdog·process 정리

- [ ] **W09 완료** — 상세4/4. lease 만료를 종료 증명으로 오해하지 않고 ready/quarantine을 설명할 수 있다.
- 상세 작업: [W09-01](docs/execution/03-worker-and-sessions.md#w09-01), [W09-02](docs/execution/03-worker-and-sessions.md#w09-02), [W09-03](docs/execution/03-worker-and-sessions.md#w09-03), [W09-04](docs/execution/03-worker-and-sessions.md#w09-04).

### W10 — 프로젝트·케이스 관리 UI를 실제 DB에 연결

- [x] **W10 완료** — 상세11/11. 케이스에 검증 내용을 직접 입력하고 데이터가 재접속 후에도 남는다. 엔진·VM·USB 검증은 아니다.
- 상세 작업: [W10-01](docs/execution/04a-case-management-ui.md#w10-01), [W10-02](docs/execution/04a-case-management-ui.md#w10-02), [W10-03](docs/execution/04a-case-management-ui.md#w10-03), [W10-04](docs/execution/04a-case-management-ui.md#w10-04), [W10-05](docs/execution/04a-case-management-ui.md#w10-05), [W10-06](docs/execution/04a-case-management-ui.md#w10-06), [W10-07](docs/execution/04a-case-management-ui.md#w10-07), [W10-08](docs/execution/04a-case-management-ui.md#w10-08), [W10-11](docs/execution/04a-case-management-ui.md#w10-11), [W10-09](docs/execution/04a-case-management-ui.md#w10-09), [W10-10](docs/execution/04a-case-management-ui.md#w10-10).

### W11 — 기기·브라우저·앱 빌드·데이터 UI

- [ ] **W11 완료** — 상세6/8. Web은 테스트 브라우저, Android는 직접 연결 기기를 선택하고 필요한 정보를 웹에서 지정한다.
- 상세 작업: [W11-01](docs/execution/04b-environments-and-launcher.md#w11-01), [W11-02](docs/execution/04b-environments-and-launcher.md#w11-02), [W11-03](docs/execution/04b-environments-and-launcher.md#w11-03), [W11-04](docs/execution/04b-environments-and-launcher.md#w11-04), [W11-05](docs/execution/04b-environments-and-launcher.md#w11-05), [W11-06](docs/execution/04b-environments-and-launcher.md#w11-06), [W11-07](docs/execution/04b-environments-and-launcher.md#w11-07), [W11-08](docs/execution/04b-environments-and-launcher.md#w11-08).

### W12 — 로컬 시작·연결 상태·탭 재접속

- [ ] **W12 완료** — 상세3/3. 일상 테스트 조작에 터미널 입력이 필요하지 않고 탭/PC 수명 차이를 안내한다.
- 상세 작업: [W12-01](docs/execution/04b-environments-and-launcher.md#w12-01), [W12-02](docs/execution/04b-environments-and-launcher.md#w12-02), [W12-03](docs/execution/04b-environments-and-launcher.md#w12-03).
- 상위 실제 수용 gate: [W27-02](docs/execution/10-retention-and-release-gates.md#w27-02). core leaf만으로 부모를 완료하지 않는다.

### W13 — 실제 action별 전후 캡처·마스킹·정제 로그

- [ ] **W13 완료** — 상세4/4. 대표 step 이미지가 아니라 실제 tap/swipe/type/back별 증거가 남는다.
- 상세 작업: [W13-01](docs/execution/05a-action-evidence-and-models.md#w13-01), [W13-02](docs/execution/05a-action-evidence-and-models.md#w13-02), [W13-03](docs/execution/05a-action-evidence-and-models.md#w13-03), [W13-04](docs/execution/05a-action-evidence-and-models.md#w13-04).
- 상위 실제 수용 gate: [W16-04](docs/execution/05b-recording-workflow.md#w16-04), [W29-03](docs/execution/06-replay-packages.md#w29-03), [W30-03](docs/execution/06-replay-packages.md#w30-03). core leaf만으로 부모를 완료하지 않는다.

### W14 — spool·ingest·ACK·파일 정합·복구

- [ ] **W14 완료** — 상세4/4. local/spooling/stored·missing/corruption을 실제 보관 상태에 맞게 표시한다.
- 상세 작업: [W14-01](docs/execution/05a-action-evidence-and-models.md#w14-01), [W14-02](docs/execution/05a-action-evidence-and-models.md#w14-02), [W14-03](docs/execution/05a-action-evidence-and-models.md#w14-03), [W14-04](docs/execution/05a-action-evidence-and-models.md#w14-04).

### W15 — 모델 역할별 호출·usage·예산 제어

- [ ] **W15 완료** — 상세3/4. 계측되지 않은 usage를0으로 표시하지 않고 승인한 실행 한도를 신뢰 코드가 적용한다.
- 상세 작업: [W15-01](docs/execution/05a-action-evidence-and-models.md#w15-01), [W15-02](docs/execution/05a-action-evidence-and-models.md#w15-02), [W15-03](docs/execution/05a-action-evidence-and-models.md#w15-03), [W15-04](docs/execution/05a-action-evidence-and-models.md#w15-04).

### W16 — 녹화 마법사·완료/중단 저장·새 후보 생성

- [ ] **W16 완료** — 상세5/8. 실패/중단/반려 여부와 무관하게 기록이 먼저 저장되고 전체 재녹화 후보가 같은 케이스에 남는다.
- 상세 작업: [W16-01](docs/execution/05b-recording-workflow.md#w16-01), [W16-02](docs/execution/05b-recording-workflow.md#w16-02), [W16-03](docs/execution/05b-recording-workflow.md#w16-03), [W16-04](docs/execution/05b-recording-workflow.md#w16-04), [W16-05](docs/execution/05b-recording-workflow.md#w16-05), [W16-06](docs/execution/05b-recording-workflow.md#w16-06), [W16-07](docs/execution/05b-recording-workflow.md#w16-07), [W16-08](docs/execution/05b-recording-workflow.md#w16-08).

### W29 — CUAWright 승인 Web package·격리 direct replay

- [ ] **W29 완료** — 상세4/6. 승인된 exact code/lock/mapping을 격리 재생하고 일반 actor0·driver/lease/capture 통제를 입증한다.
- 상세 작업: [W29-01](docs/execution/06-replay-packages.md#w29-01), [W29-02](docs/execution/06-replay-packages.md#w29-02), [W29-03](docs/execution/06-replay-packages.md#w29-03), [W29-04](docs/execution/06-replay-packages.md#w29-04), [W29-05](docs/execution/06-replay-packages.md#w29-05), [W29-06](docs/execution/06-replay-packages.md#w29-06).

### W30 — Android action plan·결정적/좌표 replay

- [ ] **W30 완료** — 상세2/4. 같은 package·화면 조건으로 재생하며 기록과 현재 검증을 새로 남기고 actor0이다.
- 상세 작업: [W30-01](docs/execution/06-replay-packages.md#w30-01), [W30-02](docs/execution/06-replay-packages.md#w30-02), [W30-03](docs/execution/06-replay-packages.md#w30-03), [W30-04](docs/execution/06-replay-packages.md#w30-04).

### W17 — 미승인 시범과 실제 QA 판정

- [ ] **W17 완료** — 상세3/4. 승인 이전에도 시범이 가능하며 판정/증거는 이번 수행에서 새로 수집한다.
- 상세 작업: [W17-01](docs/execution/07-trial-and-review.md#w17-01), [W17-02](docs/execution/07-trial-and-review.md#w17-02), [W17-03](docs/execution/07-trial-and-review.md#w17-03), [W17-04](docs/execution/07-trial-and-review.md#w17-04).

### W18 — 저장본·동작별 출처/시범 검토 UI

- [ ] **W18 완료** — 상세5/5. 사람이 녹화가 끝나 저장된 동작을 보고 사후 검토하며 runtime 허가와 섞이지 않는다.
- 상세 작업: [W18-01](docs/execution/07-trial-and-review.md#w18-01), [W18-02](docs/execution/07-trial-and-review.md#w18-02), [W18-03](docs/execution/07-trial-and-review.md#w18-03), [W18-04](docs/execution/07-trial-and-review.md#w18-04), [W18-05](docs/execution/07-trial-and-review.md#w18-05).
- 상위 실제 수용 gate: [W17-04](docs/execution/07-trial-and-review.md#w17-04). core leaf만으로 부모를 완료하지 않는다.

### W19 — 승인·반려·철회·재녹화 전환의 원자성

- [ ] **W19 완료** — 상세3/4. 저장과 승인이 분리되고 재녹화/철회/경합에서도 잘못된 기본본이나 사라진 승인 근거가 없다.
- 상세 작업: [W19-01](docs/execution/07-trial-and-review.md#w19-01), [W19-02](docs/execution/07-trial-and-review.md#w19-02), [W19-03](docs/execution/07-trial-and-review.md#w19-03), [W19-04](docs/execution/07-trial-and-review.md#w19-04).

### W31 — bounded healing ON/OFF·runtime override·수정 제안

- [ ] **W31 완료** — 상세6/7. 제안은 immutable repair proposal로 남고 채택은 새 전체 REC→OFF trial→사후 승인이다. 원본 code/default/suite 자동 수정0, 생성 code 즉시 치유 실행0.
- 상세 작업: [W31-01](docs/execution/08a-self-healing.md#w31-01), [W31-02](docs/execution/08a-self-healing.md#w31-02), [W31-03](docs/execution/08a-self-healing.md#w31-03), [W31-04](docs/execution/08a-self-healing.md#w31-04), [W31-05](docs/execution/08a-self-healing.md#w31-05), [W31-06](docs/execution/08a-self-healing.md#w31-06), [W31-07](docs/execution/08a-self-healing.md#w31-07).

### W20 — 단독 정식 접수·exact snapshot

- [ ] **W20 완료** — 상세4/4. preview/enqueue/claim에 같은 purpose별 승인 정책이 적용된다.
- 상세 작업: [W20-01](docs/execution/08b-execution-and-suites.md#w20-01), [W20-02](docs/execution/08b-execution-and-suites.md#w20-02), [W20-03](docs/execution/08b-execution-and-suites.md#w20-03), [W20-04](docs/execution/08b-execution-and-suites.md#w20-04).
- 상위 실제 수용 gate: [W22-04](docs/execution/08b-execution-and-suites.md#w22-04). core leaf만으로 부모를 완료하지 않는다.

### W21 — 선택 수행·묶음 revision·순차 정책

- [ ] **W21 완료** — 상세5/5. 사용자가 확인한 구성만 실행되고 빠진 대상/미실행 사유가 분모에 맞게 남는다.
- 상세 작업: [W21-01](docs/execution/08b-execution-and-suites.md#w21-01), [W21-02](docs/execution/08b-execution-and-suites.md#w21-02), [W21-03](docs/execution/08b-execution-and-suites.md#w21-03), [W21-04](docs/execution/08b-execution-and-suites.md#w21-04), [W21-05](docs/execution/08b-execution-and-suites.md#w21-05).
- 상위 실제 수용 gate: [W22-04](docs/execution/08b-execution-and-suites.md#w22-04). core leaf만으로 부모를 완료하지 않는다.

### W22 — 수행/항목 취소·skip·새 재실행

- [ ] **W22 완료** — 상세3/4. original FAIL과 새 RUN PASS를 다른 관측으로 추적할 수 있다.
- 상세 작업: [W22-01](docs/execution/08b-execution-and-suites.md#w22-01), [W22-02](docs/execution/08b-execution-and-suites.md#w22-02), [W22-03](docs/execution/08b-execution-and-suites.md#w22-03), [W22-04](docs/execution/08b-execution-and-suites.md#w22-04).

### W23 — ITEM 근거·실패 분석·7결과 리포트

- [ ] **W23 완료** — 상세5/5. 완료율/검증 통과/전체 통과·미검증을 구분하고 분석 의견이 원본 판정을 바꾸지 않는다.
- 상세 작업: [W23-01](docs/execution/09-results-and-analytics.md#w23-01), [W23-02](docs/execution/09-results-and-analytics.md#w23-02), [W23-03](docs/execution/09-results-and-analytics.md#w23-03), [W23-04](docs/execution/09-results-and-analytics.md#w23-04), [W23-05](docs/execution/09-results-and-analytics.md#w23-05).
- 상위 실제 수용 gate: [W22-04](docs/execution/08b-execution-and-suites.md#w22-04), [W31-07](docs/execution/08a-self-healing.md#w31-07). core leaf만으로 부모를 완료하지 않는다.

### W24 — 누적 facts·기간·cohort·과거 as_of

- [ ] **W24 완료** — 상세5/5. 전체 이력/조건별 최근 완료를 구분하고 원본 실패·이전 보고서를 재해석 없이 재현한다.
- 상세 작업: [W24-01](docs/execution/09-results-and-analytics.md#w24-01), [W24-02](docs/execution/09-results-and-analytics.md#w24-02), [W24-03](docs/execution/09-results-and-analytics.md#w24-03), [W24-04](docs/execution/09-results-and-analytics.md#w24-04), [W24-05](docs/execution/09-results-and-analytics.md#w24-05).
- 상위 실제 수용 gate: [W22-04](docs/execution/08b-execution-and-suites.md#w22-04). core leaf만으로 부모를 완료하지 않는다.

### W25 — CSV·인쇄용 HTML·snapshot export

- [ ] **W25 완료** — 상세3/3. 내보낸 리포트에 원본 IDs·기준·시점이 있고 나중의 결과/비용 보정으로 바뀌지 않는다.
- 상세 작업: [W25-01](docs/execution/09-results-and-analytics.md#w25-01), [W25-02](docs/execution/09-results-and-analytics.md#w25-02), [W25-03](docs/execution/09-results-and-analytics.md#w25-03).

### W26 — 보관 만료·승인 근거 보호·백업복원

- [ ] **W26 완료** — 상세5/5. 파일이 만료돼도 결과/승인 이력을 설명할 수 있고 유효 승인 근거를 GC가 지우지 않는다.
- 상세 작업: [W26-01](docs/execution/10-retention-and-release-gates.md#w26-01), [W26-02](docs/execution/10-retention-and-release-gates.md#w26-02), [W26-03](docs/execution/10-retention-and-release-gates.md#w26-03), [W26-04](docs/execution/10-retention-and-release-gates.md#w26-04), [W26-05](docs/execution/10-retention-and-release-gates.md#w26-05).

### W27 — 통합 장애·중복·복구·metadata 부하

- [ ] **W27 완료** — 상세1/4. 실제 장애 기록과 제약이 있고 중복 행동/원본 덮어쓰기·사라진 근거를 정상 완료로 표시하지 않는다.
- 상세 작업: [W27-01](docs/execution/10-retention-and-release-gates.md#w27-01), [W27-02](docs/execution/10-retention-and-release-gates.md#w27-02), [W27-03](docs/execution/10-retention-and-release-gates.md#w27-03), [W27-04](docs/execution/10-retention-and-release-gates.md#w27-04).

### W32 — 대표 표본 비용·안정성·월3,000 TC 추정

- [ ] **W32 완료** — 상세1/3. 고정 월 예산/실제 성공률을 꾸며내지 않고 비용과 오판/복구 이력을 함께 비교한다. 가격이 낮아도 QA/격리 기준을 낮추지 않는다.
- 상세 작업: [W32-01](docs/execution/10-retention-and-release-gates.md#w32-01), [W32-02](docs/execution/10-retention-and-release-gates.md#w32-02), [W32-03](docs/execution/10-retention-and-release-gates.md#w32-03).

### W28 — 양 플랫폼 전체 UI 동선·MVP 완료 판정

- [ ] **W28 완료** — 상세0/5. 양 플랫폼과 모든 핵심 UI·DB/보관/분석 gate가 통과하고 실제 사용 안내/알려진 제약이 정리되어 있다. 배포/중앙 운영은 자동 착수하지 않는다.
- 상세 작업: [W28-01](docs/execution/10-retention-and-release-gates.md#w28-01), [W28-02](docs/execution/10-retention-and-release-gates.md#w28-02), [W28-03](docs/execution/10-retention-and-release-gates.md#w28-03), [W28-04](docs/execution/10-retention-and-release-gates.md#w28-04), [W28-05](docs/execution/10-retention-and-release-gates.md#w28-05).

## 7. 추적과 통합

- UI94개 조작/상태·기본15화면+선택TC1화면은 [UI_COVERAGE](docs/execution/UI_COVERAGE.md)를 따른다.
- R35(P0 32/P1 3)와 UI21/DATA22/실행10의53개 시나리오는 [COVERAGE](docs/execution/COVERAGE.md)에서 담당을 확인한다.
- 치유 core/UI와 실제 수용을 W31-01–06/W31-07로 분리했다. 실제 실패/불명 재dispatch·원본 불변 조건은 삭제하지 않는다.
- task별 직접 선행 변경·검증 등급과 독립 경로는 [SCHEDULING](docs/execution/SCHEDULING.md), 구조 검사는 [VALIDATION](docs/execution/VALIDATION.md)에 기록한다.

## 8. 작업 기록

| 날짜 | 작업 | 상태 | 근거 | 다음 |
|---|---|---|---|---|
| 2026-10-31 | 기존 W01-01 | complete 유지 | source 조사/기존 코드·인계 보존 | 재구현하지 않음 |
| 2026-10-31 | 기존 W01-02 | blocked 유지 | VM 부재/실제 검증 미실행 | 환경 변경 후 해당 가지 재개 |
| 2026-10-31 | v0.8 계획 수정 | 문서 작성, 제품 진척 제외 | 기본4개/실제 healing gate 분리·직접 선행 교정 | W00-01 |
| 2026-10-31 | W00-01 | complete | venv editable install·lock·W01-01 회귀 | W00-02 |
| 2026-10-31 | W00-02 | complete | factory·loopback 설정·ASGI health. 페이지/DB 없음 | W00-03 |
| 2026-10-31 | W00-03 | complete | 기본 페이지·CSS·브라우저 liveness. 서버 smoke/DB 없음 | W00-04 |
| 2026-11-01 | W00-04 | complete | 소유 프로세스 시작·HTTP·브라우저·종료·port 해제. W00 상위 완료 | W04-01 |
| 2026-11-01 | W04-01 | complete | 임시 LOCALAPPDATA의 SQLite migration·재시작 조회·worker 비개방. W04 상위는 열림 | W04-02 |
| 2026-11-01 | W04-02 | complete | 프로젝트 A/B 저장, key 중복 409, 다른 프로젝트 audit 404, rollback 시 row 0. W04 상위는 열림 | W04-03 |
| 2026-11-01 | W04-03 | complete | loopback 세션·CSRF·Origin·worker 승인 거부. 원문 nonce/token은 DB에 없음. W04 상위는 열림 | W04-04 |
| 2026-11-01 | W04-04 | complete | OS secret store에만 원문. 조회 응답·DB·예외 로그에 원문 없음. W04 상위 완료 | W05-01 |
| 2026-11-01 | W05-01 | complete | canon-json-v1·좌표 불변 digest·expected 변경. projection은 같은 transaction. W05 상위는 열림 | W05-02 |
| 2026-11-01 | W05-02 | complete | TC 없는 초안, stale head 409, 다른 케이스 parent 거부, content UPDATE 거부. W05 상위는 열림 | W05-03 |
| 2026-11-01 | W05-03 | complete | readiness 5단계와 C03 이유. 의미 편집은 package null. W05 상위는 열림 | W05-04 |
| 2026-11-01 | W05-04 | complete | TC 연결·수정·보관·해제가 case revision/승인/head를 바꾸지 않음. 다른 project 참조는 404. W05 상위는 열림 | W05-05 |
| 2026-11-01 | W05-05 | complete | data/env/model binding 불변 revision. schema 422, 다른 project secret 404. W05 상위는 열림 | W05-06 |
| 2026-11-01 | W05-06 | complete | 목록 cursor, 승인 없는 복제, 보관 뒤 history 유지, 활성 녹화 보관 409. W05 상위는 열림 | W06-01 |
| 2026-11-01 | W06-01 | complete | REC는 같은 case만 참조. manifest output 1개, 상태 축 분리, note seq는 local_seq와 별개. W05 상위 완료 | W06-10 |
| 2026-11-01 | W06-10 | complete | 같은 worker serial은 물리 key 1개. project 별칭 2개. 없는 worker와 project 이동은 거부. W06 상위는 열림 | W06-02 |
| 2026-11-01 | W06-02 | complete | recording은 REC, trial은 ITEM, reverification job은 regression. package_rebuild owner는 둘 다 null. W06 상위는 열림 | W06-03 |
| 2026-11-01 | W06-03 | complete | 같은 event seq는 원래 receipt. 다른 hash는 409. check는 같은 attempt. unknown usage는 null. W06 상위는 열림 | W06-04 |
| 2026-11-01 | W06-04 | complete | artifact owner는 정확히 1개. 다른 case 승인 pointer와 중복 결정·revoke는 거부. provenance는 pin이 아니다. W06 상위는 열림 | W06-05 |
| 2026-11-01 | W06-05 | complete | version당 package 1개, ready 1·draft 0. 다른 case package와 중복 episode/override는 거부. body에 produced version hash 없음. W06 상위는 열림 | W06-06 |
| 2026-11-01 | W06-06 | complete | finalization은 ITEM당 1개. seq 10·20·30은 as_of로 조회. 늦은 usage는 원본을 덮지 않음. fingerprint에 commit_seq. W06 상위는 열림 | W06-07 |
| 2026-11-01 | W06-07 | complete | 빈 DB 재시작과 0008 upgrade의 integrity·FK·필수 인덱스가 같다. 봉인 content UPDATE는 거부. W06 상위는 열림 | W06-08 |
| 2026-11-01 | W06-08 | complete | probe capture는 같은 lease의 attempt만 가진다. recording 직후 화면으로 연결되지 않음. owner는 하나. W06 상위는 열림 | W06-09 |
| 2026-11-01 | W06-09 | complete | proposal 수락은 version 1개. 거부는 0개. stale head는 409. 재시작 뒤 diff가 남음. 승인은 복사되지 않음. W06 상위 완료 | W07-01 |
| 2026-11-01 | W07-01 | complete | 같은 serial은 물리 key 1개. 두 project busy 보고의 lease는 1개. raw handle은 응답과 DB에 없음. W07 상위는 열림 | W08-01 |
| 2026-11-01 | W08-01 | complete | 같은 key/body는 job 1개. 다른 body는 409. unknown purpose는 422. REC와 job 사이 실패는 owner 0행. W08 상위는 열림 | W08-02 |
| 2026-11-01 | W08-02 | complete | 동시 claim의 활성 slot은 1개. 같은 기기 lease는 1개. 한 job의 attempt는 1개. 정리 전 다음 ITEM은 queued. W08 상위는 열림 | W08-03 |
| 2026-11-01 | W08-03 | complete | 같은 nonce ACK는 attempt 1개. 만료 generation은 409. lease는 45초, heartbeat는 10초. 모델 대기 중에도 갱신된다. W08 상위는 열림 | W08-04 |
| 2026-11-01 | W08-04 | complete | seq 1·3의 연속 ACK는 1. seq 2 뒤 ACK는 3. 다른 hash는 409. terminal 뒤 hash는 그대로. W08 상위는 열림 | W08-05 |
| 2026-11-01 | W08-05 | complete | queued는 유지. 죽은 runner의 attempt는 1개. 다른 PC boot의 자원은 quarantine. 같은 boot의 유효 generation은 running. W08 상위 완료 | W09-01 |
| 2026-11-01 | W09-01 | complete | 취소 기록 뒤 늦은 응답 dispatch는 0. terminal 결과는 그대로. runner 정지와 cleanup은 비어 있다. W09 상위는 열림 | W09-02 |
| 2026-11-01 | W09-02 | complete | watchdog 29초는 허용, 30초는 거부. lease 여유 10초는 허용, 9초는 거부. action 51은 dispatch되지 않음. attempt 자동 retry는 0. W09 상위는 열림 | W09-03 |
| 2026-11-01 | W09-03 | complete | 소유 pid tree만 종료. 같은 이름의 다른 process는 유지. proof 없는 context는 quarantine. W09 상위는 열림 | W10-01 |
| 2026-11-01 | W10-01 | complete | 목록 조회가 상세를 다녀온 뒤에도 남는다. 새로고침은 추가 변경 0. 브라우저 저장소에 비밀 없음. 키보드로 항목을 열 수 있다. W10 상위는 열림 | W10-02 |
| 2026-11-01 | W10-02 | complete | 중복 key는 409. 진행 중 작업의 보관은 409. 보관 뒤 이력은 읽을 수 있고 복구는 audit를 남긴다. W10 상위는 열림 | W10-03 |
| 2026-11-01 | W10-03 | complete | 개요 count가 저장된 행과 같다. 빈 프로젝트에 PASS 표시는 0. 새 녹화는 기기 단계로 이동한다. W10 상위는 열림 | W10-04 |
| 2026-11-01 | W10-04 | complete | 기본 페이지는 25건이다. 상세에서 돌아온 조회가 남는다. 다른 프로젝트 행은 0건이다. TC가 없는 케이스도 선택할 수 있다. W10 상위는 열림 | W10-05 |
| 2026-11-01 | W10-05 | complete | 선택 결과에서 빠지는 항목은 0건이다. 복제본 승인은 0건이다. 보관은 과거 행을 지우지 않는다. 진행 중 녹화는 차단 사유가 보인다. W10 상위는 열림 | W10-06 |
| 2026-11-01 | W10-06 | complete | 불완전한 초안이 저장된다. 정식 실행 가능은 거짓이다. 다른 머리 저장은 409이고 입력과 서버 초안이 남는다. 비밀 원문은 응답에 없다. W10 상위는 열림 | W10-07 |
| 2026-11-01 | W10-07 | complete | 단계 복제는 새 ID다. 제안 거부는 버전 0개, 수락은 1개다. 기존 버전 hash는 그대로다. W10 상위는 열림 | W10-08 |
| 2026-11-01 | W10-08 | complete | 최신 초안과 승인본이 다르다. 패키지 없음이 표시된다. 실행 이력은 0건이다. 스냅샷은 읽기 전용이다. W10 상위는 열림 | W10-11 |
| 2026-11-01 | W10-11 | complete | 설정 변경은 새 초안이다. 기존 승인 범위는 그대로다. 새 패키지는 없다. healing 기본은 꺼져 있다. 오류여도 입력은 남는다. W10 상위는 열림 | W10-09 |
| 2026-11-01 | W10-09 | complete | 역할별 binding이 분리된다. 키 원문은 조회에 없다. 브라우저는 키를 저장하지 않는다. 기존 승인 범위는 넓어지지 않는다. W10 상위는 열림 | W10-10 |
| 2026-11-01 | W10-10 | complete | 케이스는 TC 없이 둘 수 있다. 참조 연결은 승인과 hash를 바꾸지 않는다. 가져오기 수락은 새 케이스 버전 하나다. 다른 프로젝트 TC는 거절된다. W10 상위는 상세 11/11로 닫힌다 | W13-01 |
| 2026-11-01 | W13-01 | complete | 범위 밖 제안의 dispatch는 0이다. raw shell은 허용되지 않는다. 화면 지시는 실행 권한이 아니다. W13 상위는 열림 | W13-02 |
| 2026-11-01 | W13-02 | complete | 하위 행동 3개의 전 캡처가 보관된다. 원문 비밀과 reasoning은 디스크에 없다. 전 캡처 실패의 dispatch는 0이다. W13 상위는 열림 | W13-03 |
| 2026-11-01 | W13-03 | complete | journal flush 실패의 dispatch는 0이다. 명령 뒤 timeout은 다시 호출하지 않는다. timeout을 lookup_failed로 바꾸지 않는다. W13 상위는 열림 | W13-04 |
| 2026-11-01 | W13-04 | complete | 정상 행동 3개의 전후 캡처는 6개다. 후 캡처가 없어도 다시 누르지 않는다. 늦은 재관찰은 즉시 후 캡처가 아니다. W13 상위는 열림 | W14-01 |
| 2026-11-01 | W14-01 | complete | 미ACK 파일 삭제는 0이다. ACK는 hash가 맞아야 한다. 같은 업로드가 행동을 늘리지 않는다. 디스크 압박은 새 행동을 멈춘다. W14 상위는 열림 | W14-02 |
| 2026-11-01 | W14-02 | complete | ready 전에 ACK하지 않는다. hash가 다르면 ready가 아니다. 경로가 밖으로 나가지 않는다. 같은 파일은 같은 receipt다. W14 상위는 열림 | W14-03 |
| 2026-11-01 | W14-03 | complete | 없는 파일을 성공으로 돌려주지 않는다. 바뀐 파일은 corruption이다. 원래 hash는 바꾸지 않는다. W14 상위는 열림 | W14-04 |
| 2026-11-01 | W14-04 | complete | 미전송 캡처는 새 recovery manifest다. 기존 결과는 그대로다. 늦은 사진은 즉시 후 캡처가 아니다. dispatch는 0이다. W14 상위는 열림 | W15-01 |
| 2026-11-01 | W15-01 | complete | 등록되지 않은 check 호출은 거절된다. 다른 ITEM episode 호출은 거절된다. replay script에는 key가 없다. authoring 호출은 계측된다. W15 상위는 열림 | W15-02 |
| 2026-11-01 | W15-02 | complete | 미보고 토큰은 null이다. 미사용 role의 call은 0이다. 일부 토큰만 있으면 partial이다. 늦은 정산은 원래 값을 바꾸지 않는다. W15 상위는 열림 | W15-03 |
| 2026-11-01 | W15-03 | complete | 예산을 넘는 예약은 0이다. 가격이 없는 strict 호출은 거절된다. healer 세 번째 전송은 거절된다. 늦은 응답은 행동을 시작하지 않는다. W15 상위는 열림 | W11-01 |
| 2026-11-01 | W11-01 | complete | 관리 화면은 테스트 브라우저가 아니다. 오래된 수신 시각이 보인다. 권한 없는 preview는 거절된다. preview는 기기를 조작하지 않는다. W11 상위는 열림 | W11-02 |
| 2026-11-01 | W11-02 | complete | 허용 범위 밖 주소와 패키지는 거절된다. 미지원 기능은 선택할 수 없다. 새 revision은 이전 스냅샷을 바꾸지 않는다. W11 상위는 열림 | W11-03 |
| 2026-11-01 | W11-03 | complete | 필수 열이 없으면 422이다. 같은 행 ID는 거절된다. 이전 revision의 값은 유지된다. 응답에 비밀 원문은 없다. W11 상위는 열림 | W11-05 |
| 2026-11-01 | W11-05 | complete | 분할 묶음은 거절된다. ZIP 경로 탈출은 거절된다. 분석 도구가 없으면 ready가 아니다. 올린 파일은 실행하지 않는다. W11 상위는 열림 | W11-07 |
| 2026-11-01 | W11-07 | complete | VM이 없으면 Web은 ready가 아니다. 복구는 proof가 필요하다. 지원하지 않는 버튼은 0이다. 진단 QA는 null이다. W11 상위는 열림 | W11-08 |
| 2026-11-01 | W11-08 | complete | 다른 프로젝트 이력은 0건이다. 권한이 폐기된 worker는 작업을 받지 못한다. 보호 공간이 보인다. W11 상위는 열림 | W12-01 |
| 2026-11-01 | W12-01 | complete | API는 1개다. worker는 1개다. 탭을 닫아도 프로세스는 유지된다. 포트 충돌은 설명된다. W12 상위는 열림 | W12-02 |
| 2026-11-01 | W12-02 | complete | 조회 간격은 2초다. 재연결 mutation은 0이다. 선택한 action이 복원된다. 두 커서는 섞이지 않는다. W12 상위는 열림 | W12-03 |
| 2026-11-01 | W12-03 | complete | 자동 재개는 0이다. 불명 상태를 성공으로 바꾸지 않는다. 마지막 수신이 보인다. 정리 또는 quarantine이 있다. W12 상위는 열림 | W16-01 |
| 2026-11-01 | W16-01 | complete | 기기가 먼저다. TC는 필수가 아니다. 불완전 초안이 저장된다. 다른 대상 필드는 남지 않는다. W16 상위는 열림 | W16-03 |
| 2026-11-01 | W16-03 | complete | 같은 키의 녹화는 1건이다. 다른 본문은 409이다. 해시가 다르면 409이다. TC가 없어도 접수된다. W16 상위는 열림 | W16-05 |
| 2026-11-01 | W16-05 | complete | 승인 없이 저장된다. 실패도 저장된다. 같은 완료의 materialization은 1건이다. compiler가 없으면 package는 비어 있다. W16 상위는 열림 | W16-06 |
| 2026-11-01 | W16-06 | complete | 저장된 기록이 완료를 뜻하지 않는다. 반려도 보인다. receipt 버전이 보인다. 로컬은 서버 저장이 아니다. W16 상위는 열림 | W16-08 |
| 2026-11-01 | W16-08 | complete | 같은 케이스다. 기준 버전은 남는다. 기존 승인은 바뀌지 않는다. 늦은 완료가 head를 덮지 않는다. W16 상위는 열림 | W29-01 |
| 2026-11-01 | W29-01 | complete | hash 순환은 허용되지 않는다. mapping이 없으면 ready가 아니다. 다른 source는 허용되지 않는다. W29 상위는 열림 | W29-02 |
| 2026-11-01 | W29-02 | complete | 지원하지 않는 문법은 거절된다. expected는 바뀌지 않는다. 모든 행동이 매핑된다. W29 상위는 열림 | W29-04 |
| 2026-11-01 | W29-04 | complete | ready package는 1건이다. 부분 commit은 0이다. 같은 manifest version은 1건이다. 늦은 attach는 거절된다. W29 상위는 열림 | W17-01 |
| 2026-11-01 | W17-01 | complete | 승인 없는 ready package 시범은 가능하다. package가 없으면 시범은 거절된다. healing은 꺼져 있다. 결정적 검사는 키 없이 진행된다. AI 검사는 키가 없으면 막힌다. W17 상위는 열림 | W29-06 |
| 2026-11-01 | W29-06 | complete | package가 없어도 기록은 보인다. code는 읽기 전용이다. mapping은 저장된 step과 같다. 다른 프로젝트 조회는 거절된다. W29 상위는 열림 | W17-02 |
| 2026-11-01 | W17-02 | complete | 같은 값은 satisfied다. 다른 값은 violated다. 관찰이 없으면 unknown이다. 엔진 완료만으로 만족이 되지 않는다. W17 상위는 열림 | W30-01 |
| 2026-11-01 | W30-01 | complete | tap/type/swipe/back만 plan이 된다. model loop는 plan 명령이 아니다. secret 원문은 저장되지 않는다. geometry가 없으면 ready가 아니다. W30 상위는 열림 | W17-03 |
| 2026-11-01 | W17-03 | complete | violated에는 모델을 호출하지 않는다. 선언되지 않은 method도 호출하지 않는다. parse 실패는 unknown이다. 필수 위반 latch는 FAIL이다. W17 상위는 열림 | W30-02 |
| 2026-11-01 | W30-02 | complete | 겹친 target은 dispatch하지 않는다. 해상도가 바뀌면 막는다. 추정 좌표 dispatch는 0이다. W30 상위는 열림 | W18-01 |
| 2026-11-01 | W18-01 | complete | 다른 ITEM 증거와 섞인 action은 거절된다. healing 시범은 받지 않는다. 검토 pin과 30일 보호가 생긴다. W18 상위는 열림 | W18-02 |
| 2026-11-01 | W18-02 | complete | 같은 시도의 전후 화면만 보인다. 다른 실행 그림으로 바꾸지 않는다. 만료는 사유로 보인다. 키보드로 다음 행동으로 이동한다. W18 상위는 열림 | W18-03 |
| 2026-11-01 | W18-03 | complete | 의견은 entry에 덧붙는다. 출처와 시범의 같은 action 표시는 따로 센다. digest가 바뀌면 409이다. 녹화 중 의견은 거절된다. QA 행은 그대로다. W18 상위는 열림 | W18-04 |
| 2026-11-01 | W18-04 | complete | 미완성 후보는 승인되지 않는다. 차단 사유가 보인다. 이전 검토는 복사되지 않는다. 출처와 시범은 따로 보인다. W18 상위는 열림 | W18-05 |
| 2026-11-01 | W18-05 | complete | 연장은 새 보호 사건이다. 이전 기한은 그대로다. 만료된 근거는 승인을 막는다. 반려 기록은 남는다. 다른 승인 pin은 그대로다. W18 상위는 열림 | W19-01 |
| 2026-11-01 | W19-01 | complete | 승인 사건과 pin과 기본본과 감사가 함께 남는다. 진 요청은 409이다. 이전 승인은 철회되지 않는다. 부분 승인 행은 0이다. W19 상위는 열림 | W19-02 |
| 2026-11-01 | W19-02 | complete | 실패한 후보는 기본본을 바꾸지 않는다. 반려 기록은 남는다. 409는 다시 승인하지 않는다. 빈 사유는 거절된다. W19 상위는 열림 | W19-03 |
| 2026-11-01 | W19-03 | complete | 철회하면 기본본은 비워진다. 이전 승인으로 돌아가지 않는다. 대기 접수는 막힌다. 끝난 판정은 그대로다. W19 상위는 열림 | W31-01 |
| 2026-11-01 | W31-01 | complete | healing 기본은 꺼져 있다. 허용이 없으면 켜기 요청은 거절된다. 시범은 켜지지 않는다. 진행 중 snapshot은 바뀌지 않는다. W31 상위는 열림 | W23-01 |
| 2026-11-01 | W23-01 | complete | 종료 10개의 완료율은 1, 검증 통과율은 0.75, 전체 통과율은 0.6, 미검증은 2다. 빈 실행의 비율은 비운다. 위반 취소는 실패 1회다. W23 상위는 열림 | W31-02 |
| 2026-11-01 | W31-02 | complete | 항목당 episode는 1개다. 꺼진 정책의 모델 예약은 0이다. 중복 요청은 episode를 추가하지 않는다. dispatch 뒤에는 예약하지 않는다. W31 상위는 열림 | W09-04 |
| 2026-11-01 | W09-04 | complete | 녹화와 관리 작업의 판정은 비운다. 필수 위반은 취소 뒤에도 실패로 남는다. 위반 없는 불명 종료는 불명이다. 정리 실패는 격리고 판정을 바꾸지 않는다. W09 상위는 열림 | W31-03 |
| 2026-11-01 | W31-03 | complete | 같은 대상은 locator가 바뀌어도 증명되면 받는다. 동명 중복, 다른 동작, 화면만 있는 후보는 거절한다. W31 상위는 열림 | W20-01 |
| 2026-11-01 | W20-01 | complete | 정식 미리보기는 유효한 과거 승인을 그 버전에 고정한다. 미승인 정식은 받지 않는다. 빠짐은 확인이 있어야 하고 미리보기는 예약하지 않는다. W20 상위는 열림 | W31-04 |
| 2026-11-01 | W31-04 | complete | 받은 대상만 그 항목에 남고 원래 동작은 한 번 실행된다. 필수 위반은 실패로 남고 이후 결과가 그 판정을 바꾸지 않는다. W31 상위는 열림 | W20-02 |
| 2026-11-01 | W20-02 | complete | 같은 접수는 실행 1건이다. 중단된 접수는 행이 0이다. 철회된 승인의 claim은 막히고 최신 승인으로 바꾸지 않는다. W20 상위는 열림 | W31-05 |
| 2026-11-01 | W31-05 | complete | 같은 제안은 하나다. 다른 케이스 채택은 거절된다. 원본 script와 기본 승인은 그대로이고 새 전체 녹화가 생긴다. W31 상위는 열림 | W20-03 |
| 2026-11-01 | W20-03 | complete | 수행 준비는 4단계다. 빈 수행과 100개 초과는 시작되지 않는다. 시범과 정식은 한 수행에 섞이지 않는다. W20 상위는 열림 | W31-06 |
| 2026-11-01 | W31-06 | complete | 치유 기본은 꺼져 있고 진행 중에는 바꿀 수 없다. 치유를 사용한 성공은 배지다. 원래 오류는 그대로 보이고 끝난 실패는 새 수행으로 이어진다. W31 상위는 열림 | W20-04 |
| 2026-11-01 | W20-04 | complete | 종료 수와 성공 수는 따로다. 단계는 작업 상태와 다르다. 새로고침은 작업을 늘리지 않고 선택 항목이 남는다. W20 상위는 열림 | W21-01 |
| 2026-11-01 | W21-01 | complete | 빈 묶음은 저장된다. 구성이 0이면 실행되지 않는다. 복제와 보관 뒤에도 진행 중 수행의 버전은 그대로다. W21 상위는 열림 | W21-02 |
| 2026-11-01 | W21-02 | complete | 항목 번호는 고유하다. 같은 검증의 데이터 행은 구분된다. 대상이 섞이면 자원이 있어야 한다. 이전 구성은 그대로다. W21 상위는 열림 | W21-03 |
| 2026-11-01 | W21-03 | complete | 새 승인은 차이와 영향 항목으로 보인다. 거절은 구성을 만들지 않는다. 선택한 항목만 바뀌고 이전 수행은 그대로다. W21 상위는 열림 | W23-02 |
| 2026-11-01 | W23-02 | complete | 첫 실패는 이후 만족 뒤에도 남는다. 고른 시도만 보이고 없는 화면은 모델 그림으로 바뀌지 않는다. 보관 기한 사유가 보인다. W23 상위는 열림 | W21-04 |
| 2026-11-01 | W21-04 | complete | 100개 확장은 받는다. 0개와 101개는 422이다. 확인하지 않은 제외는 0이다. W21 상위는 열림 | W23-03 |
| 2026-11-01 | W23-03 | complete | 분석 기록 2건이 남는다. 원래 판정은 그대로다. 잘못된 주소는 거절되고 메모는 화면에서 이스케이프된다. W23 상위는 열림 | W21-05 |
| 2026-11-01 | W21-05 | complete | 한 번에 한 항목만 잡는다. 중단의 나머지는 실행하지 않은 항목이고 사용자 취소와 다르다. 부모는 모든 항목이 끝난 뒤에 끝난다. W21 상위는 열림 | W23-04 |
| 2026-11-01 | W23-04 | complete | 열 개 수행의 세 비율은 1, 0.75, 0.6이다. 시범은 기본 목록에 없고 녹화는 포함되지 않는다. 진행 중 보고는 중간 보고로 보인다. W23 상위는 열림 | W22-01 |
| 2026-11-01 | W22-01 | complete | 실패로 끝난 항목은 취소 뒤에도 실패다. 완료 항목의 내용은 그대로다. 같은 취소의 효과는 1개다. W22 상위는 열림 | W23-05 |
| 2026-11-01 | W23-05 | complete | 만족 6건 중 도움 없음은 4건이고 치유는 1건이다. 끝 구분은 7개다. 측정이 일부만 있으면 partial이다. W23 상위는 열림 | W22-02 |
| 2026-11-01 | W22-02 | complete | 대기 항목은 건너뜀이 된다. 진행 중 건너뛰기는 거절된다. 자원은 잡지 않고 완료된 실패는 그대로다. W22 상위는 열림 | W24-01 |
| 2026-11-01 | W24-01 | complete | 재시도는 관측을 늘리지 않고 재실행은 관측 2개다. as_of 15에서는 아직 종료가 아니다. 미실행은 분모에 있다. W24 상위는 열림 | W22-03 |
| 2026-11-01 | W22-03 | complete | 실패 항목은 새 수행이 된다. 원본 실패와 시도 수는 그대로다. 같은 키는 새 수행 1건이다. W22 상위는 열림 | W24-02 |
| 2026-11-01 | W24-02 | complete | 기대가 바뀌면 series가 달라진다. 켜짐과 꺼짐은 같은 strict가 아니다. 미사용과 불명은 다르다. 진행 중 항목은 최근 완료를 바꾸지 않는다. W24 상위는 열림 | W24-03 |
| 2026-11-01 | W24-03 | complete | 빈 표본은 비율이 없다. 미실행 시간은 비어 있다. 기준 시각 뒤의 비용은 더하지 않는다. W24 상위는 열림 | W24-04 |
| 2026-11-01 | W24-04 | complete | 조건 차이와 다른 절차가 보인다. 조건이 섞이면 배너가 있고 자동 확정은 0이다. 원본 실패는 그대로다. W24 상위는 열림 | W24-05 |
| 2026-11-01 | W24-05 | complete | 상세가 비어도 이전 시점의 분모·확정·비용은 같다. 늦은 비용은 그 시점의 내보내기를 바꾸지 않는다. W24 상위는 열림 | W25-01 |
| 2026-11-01 | W25-01 | complete | 진행 중 내보내기의 시점과 비용은 고정된다. 같은 키는 1건이고 만료 이유가 보인다. W25 상위는 열림 | W25-02 |
| 2026-11-01 | W25-02 | complete | 수식 문자는 막히고 한글은 유지된다. 비밀 원문은 빠지고 원본 식별자는 남는다. W25 상위는 열림 | W25-03 |
| 2026-11-01 | W25-03 | complete | 인쇄 화면은 핵심 칸을 자르지 않는다. 스크립트는 이스케이프되고 PDF는 만들지 않는다. W25 상위는 열림 | W26-01 |
| 2026-11-01 | W26-01 | complete | 만료는 payload만 지우고 hash와 tombstone을 남긴다. 미확인 spool과 지난 통계는 남는다. W26 상위는 열림 | W26-02 |
| 2026-11-01 | W26-02 | complete | 과거 승인 pin은 GC가 집지 않는다. manual 해제는 다른 pin을 풀지 않는다. W26 상위는 열림 | W26-03 |
| 2026-11-01 | W26-03 | complete | 보호 파일이 한도를 넘으면 새 행동을 멈추고 일부 기록은 남는다. 이력 정리 버튼은 없다. W26 상위는 열림 | W26-04 |
| 2026-11-01 | W26-04 | complete | 백업은 이 PC 전체의 일관 스냅샷이다. 프로젝트 권한만으로는 받지 못하고 비밀 원문은 빠진다. W26 상위는 열림 | W26-05 |
| 2026-11-01 | W26-05 | complete | 복원 검사는 실행 중인 저장소와 다른 경로에서 하고, 활성화는 소유자의 명시 확인 뒤에만 진행 작업을 정리한다. W26 상위는 열림 | W32-01 |
| 2026-11-01 | W32-01 | complete | 역할별 비용은 통화마다 따로 합산하고, 계측이 없으면 금액이 비며 미사용 역할은 0이다. W32 상위는 열림 | W27-04 |
| 2026-11-01 | W27-04 | complete | 합성 1만 항목과 10만 행동의 query plan을 측정했다. 파일 입출력과 기기 지연은 빠진다. W27 상위는 열림 | 준비 후보 없음 |

진행률은50/163이다. W00, W04, W05, W06, W08, W10 상위는 각각 상세를 마쳤고, 엔진 검증은 아니다. W07 상위는 상세 1/4, W09 상위는 상세 3/4, W13 상위는 상세 4/4이고 parent gate는 남아 있다. W14 상위는 상세 4/4이고 parent gate는 남아 있다. W09-04는 W23-01을 기다린다. W11-01은 W14-03을 기다린다. W01-02 차단은 유지한다.

## 9. MVP 이후 범위

중앙 관리/cloud 접속·인증은 현재 전환 범위다. 이후 확장은 대규모 운영·SSO 고도화, 일반 Skill Factory/자가 코드 수정, 영상/trace/logcat·수동제어·pause/partial merge,
선택 API/DB oracle, 예약/CI/외부 알림/TC CSV/PDF, 파괴적 history purge는 기존 후속 범위다.
Web/Android replay·명시 verifier·bounded healing·사후 승인·CSV/인쇄HTML의 필수 실제 검증은 유지한다.

복구 접수·워커 선행 [RX-92~95](docs/managed-pc/HEALING_ADMISSION_TASKS.md)는 4/4이다. 설정 보존·서버 정책 해석·claim 재검사를 작은 단위로 분리했다.

RX-92/93의 설정 저장·서버 healing 정책 해석은 로컬 계약/브라우저 검증을 마쳤다. 정상 ON 접수 RX-86과 claim RX-94/플랫폼 runtime은 진행 중인 별도 범위다. 전체 검사 기준 커밋의 [9개 실패](docs/validation/tasks/REGRESSION_BASELINE_2026-11-09.md)는 전체 green으로 오인하지 않는다.

RX-86/94/95: 실제 API ON 접수/같은 구성 재실행·정확한 승인/키/정책 claim 재검사·워커 typed pin validation을 구현했다. 정상 ON 실행의 실제 모델/episode/locator 치유는 RX-87/88이며 UI는 RX-89에 남아 있다.
