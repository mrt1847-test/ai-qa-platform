# AI QA 플랫폼 작업 진행표 v0.7

기준일: **2026-10-31 (Asia/Seoul)** · 제품 설계: **v0.6 + 실행 보완 계약** · 제품 구현: **미착수**.

**이 문서는 32개 상위 W의 진행표다. 모델에게 실제로 맡기는 단위는 [영역별 상세 작업서](docs/execution/README.md)의158개 leaf다.**
한 요청에 부모 W 전체를 구현하라고 하지 않는다. 이전 채팅/모델 기억 없이 담당 카드·지정 계약·직접 선행 근거로 진행한다.

**매 실행은 [NEXT_ACTION.md](NEXT_ACTION.md)에서 시작한다. Current/실행 우선순위는 그 파일만 관리하며, 이 문서는 상위 진행률과 검수 요약이다.**

[처음 읽을 실행 안내](docs/execution/README.md) · [공통 계약](docs/execution/CONTRACTS.md) · [모델 인계 양식](docs/execution/HANDOFF.md) · [UI94개 조작](docs/execution/UI_COVERAGE.md) · [요구·시나리오 추적](docs/execution/COVERAGE.md) · [검토·보완32건](docs/execution/REVIEW.md)

## 1. 현재 상태

| 구분 | 상태 |
|---|---|
| 제품 설계/조사 | 검토 문서 있음. 실제 DB/VM/모델/기기 합격 아님 |
| 클릭 가능한 frontend | [v0.5 모의 샘플](prototype/README.md), v0.6 실제 replay/healing 구현 아님 |
| 제품 상위 작업 | **완료0 / 32 W** |
| 제품 상세 작업 | **완료0 / 158** |
| 실제 모델·양 플랫폼·DB 시험 | 미실행 |
| 실행 지시 대상 | [NEXT_ACTION의 Current](NEXT_ACTION.md#current)에서만 관리 |
| 이후 후보 | [NEXT_ACTION의 Next](NEXT_ACTION.md#next), 직접 선행 충족 후 선택 |

이번 개정은 문서 세분화·교차 검토다. 설치/제품 코드/모델 호출/기기 실행/배포를 하지 않았다.
개정 전 여섯 문서는 [v0.6 보관본](docs/history/v0.6/WORK_PROGRESS.md)에 보존했다.

## 2. 전체 순서와 영역별 문서

| 단계 | 상위 W | 상세 수 | 완료 | 산출 |
|---|---|---:|---:|---|
| A · 공개 코드·모델·연결 탐색 | W01 W02 W03 | 11 | 0 | [A · 공개 코드·모델·연결 탐색](docs/execution/01-foundation-probes.md) |
| B · 데이터·권한·불변 버전 | W04 W05 W06 | 20 | 0 | [B-1 · 권한·케이스·TC·환경·data](docs/execution/02a-assets-and-scope.md) / [B-2 · 자원·REC·job·증거·장기 facts schema](docs/execution/02b-job-evidence-schema.md) |
| C · 세션·작업 큐·중단 | W07 W08 W09 | 13 | 0 | [C · 세션·작업 큐·중단](docs/execution/03-worker-and-sessions.md) |
| D · 관리 화면·환경·설정 | W10 W11 W12 | 22 | 0 | [D-1 · 프로젝트·케이스·설정·선택 TC UI](docs/execution/04a-case-management-ui.md) / [D-2 · 환경·기기·앱·data·launcher UI](docs/execution/04b-environments-and-launcher.md) |
| E · AI 녹화·먼저 저장·증거 | W13 W14 W15 W16 | 20 | 0 | [E-1 · 행동·증거·spool·모델 계측](docs/execution/05a-action-evidence-and-models.md) / [E-2 · 녹화 입력·진행·저장·재녹화](docs/execution/05b-recording-workflow.md) |
| F · 승인 package·모델 없는 재생 | W29 W30 | 10 | 0 | [F · 승인 package·모델 없는 재생](docs/execution/06-replay-packages.md) |
| G · 시범·사후 검토·승인 | W17 W18 W19 | 13 | 0 | [G · 시범·사후 검토·승인](docs/execution/07-trial-and-review.md) |
| H · 선택 치유·정식·묶음 수행 | W31 W20 W21 W22 | 19 | 0 | [H-1 · 선택 셀프힐링·제안](docs/execution/08a-self-healing.md) / [H-2 · 정식·선택·묶음·취소·재실행](docs/execution/08b-execution-and-suites.md) |
| I · 결과·분석·내보내기 | W23 W24 W25 | 13 | 0 | [I · 결과·분석·내보내기](docs/execution/09-results-and-analytics.md) |
| J · 보관·장애·비용·최종 동선 | W26 W27 W32 W28 | 17 | 0 | [J · 보관·장애·비용·최종 동선](docs/execution/10-retention-and-release-gates.md) |
| 합계 | **32 W** | **158** | **0** | **14개 영역 문서** |

**Current/우선순위는 [NEXT_ACTION](NEXT_ACTION.md), 실행 자격은 [TASK_INDEX.json](docs/execution/TASK_INDEX.json)의 직접 선행 ID를 따른다.** ID를 숫자 정렬하지 않는다.
W16-05(raw source/실패 초안) → W29/W30(package/재생) → W16-07(finish 통합)이므로 W16 전체 완료를 W29의 선행으로 걸지 않는다.
W10-11(case 설정 편집)은 W10-08 다음이다. W06-10의 자원 schema는 W06-02보다 먼저, W23-01 순수 집계 kernel은 W06-06 뒤·W09-04 첫 사용 전에 구현한다. UI의 앞선 shell 완료가 뒤 기능의 구현 완료는 아니다.
W17에서 미승인 trial의 공통 RUN/ITEM 경로를 먼저 만들고 W20에서 정식 승인 검사를 확장한다.

## 3. 한 번의 요청과 완료 기준

1. NEXT_ACTION의 Current leaf ID를 확인한다. 지정 CONTRACTS 절과 직접 선행의 실제 interface/검증 근거를 읽는다.
2. 현재 코드/저장소 지침과 사용자 허용 범위를 확인한다. 문서의 미래 경로가 이미 존재한다고 가정하지 않는다.
3. 카드에 적힌 입력/부정 조건·필요한 실패 시험/화면 확인을 작성하고 지정 범위만 구현한다.
4. 명시된 명령과 UI/실환경 조건을 검사한다. 키/장비 부재로 SKIP된 필수 gate는 차단/미실행이다.
5. diff·UI 조작·저장/API·불변식을 검토하고 `docs/validation/tasks/{ID}.md`에 실제 인계를 남긴다.
6. 카드 완료 체크·TASK_INDEX.status·이 문서 요약·NEXT_ACTION의 Current/Next를 함께 갱신한다. 미완료면 Current와 재개 조건을 유지한다.

상세 작업 전부 완료 + 아래 상위 통합 조건 충족 때만 W를 체크한다.
분모는 W32개/상세158개 두 가지를 별도로 표시하며 공수/일정 달성률로 해석하지 않는다.
필요한 추가 분할/요구 보완은 새 ID·선행·UI/요구/시험 매핑을 만들고 분모 변경 이유를 기록한다.

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
- Web·직접 연결 Android 둘 다 완료해야 MVP다. 클라우드·수동 화면 제어·영상·중간 재개·일반 Skill Factory 추천/자가 코드 변경은 후속이다. 승인 Web code/Android action replay·bounded healing은 이32개에 포함한다.

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

수치/상태/DTO·API 상세는 [공통 계약 C00–C12](docs/execution/CONTRACTS.md)를 따른다.
특히 action retry는 미dispatch 증명된 전달 전만, 미ACK spool은 7일 자동폐기 대상이 아니다.
원본 정의/절차 편집은 새 draft/package=null, 동일 source 재컴파일은 새 manifest/version이다.

## 6. 상위 W 체크리스트

아래 각 행은 **상세 작업을 묶는 상위 검수 조건**이다. 한 행 전체를 새 모델에게 작업 지시로 주지 않는다.
원래 W01–W32 ID는 유지했다. 실제 leaf 카드는 링크된 영역 문서에 있다.

### W01 — CUAWright Web authoring·계측·격리 가능성

- [ ] **W01 완료** — 상세0/4. CUAWright Web authoring/격리/동작 계측·직접 replay의 가능/불가·패치·제약이 기록되어 있다.
- 상세 작업: [W01-01](docs/execution/01-foundation-probes.md#w01-01), [W01-02](docs/execution/01-foundation-probes.md#w01-02), [W01-03](docs/execution/01-foundation-probes.md#w01-03), [W01-04](docs/execution/01-foundation-probes.md#w01-04).

### W02 — Android USB·좌표·입력 가능성

- [ ] **W02 완료** — 상세0/4. 실제 좌표/입력/전후 캡처·Mobile-Agent authoring trace를 Android plan으로 재생할 지원 범위와 Windows 제약이 확인되어 있다.
- 상세 작업: [W02-01](docs/execution/01-foundation-probes.md#w02-01), [W02-02](docs/execution/01-foundation-probes.md#w02-02), [W02-03](docs/execution/01-foundation-probes.md#w02-03), [W02-04](docs/execution/01-foundation-probes.md#w02-04).

### W03 — 모델 형식·upstream 채택 결정

- [ ] **W03 완료** — 상세0/3. 양 플랫폼 필수 capture/행동 경계가 확보되고 모델/엔진 결정이 문서에 반영되어 있다.
- 상세 작업: [W03-01](docs/execution/01-foundation-probes.md#w03-01), [W03-02](docs/execution/01-foundation-probes.md#w03-02), [W03-03](docs/execution/01-foundation-probes.md#w03-03).

### W04 — project scope·API 권한·저장 연결

- [ ] **W04 완료** — 상세0/4. 실제 자산 저장과 권한 경계를 확인했고 비밀 원문이 응답/DB definition에 없다.
- 상세 작업: [W04-01](docs/execution/02a-assets-and-scope.md#w04-01), [W04-02](docs/execution/02a-assets-and-scope.md#w04-02), [W04-03](docs/execution/02a-assets-and-scope.md#w04-03), [W04-04](docs/execution/02a-assets-and-scope.md#w04-04).

### W05 — 케이스·불변 버전·선택 TC·데이터 revision

- [ ] **W05 완료** — 상세0/6. 검증 내용·녹화 기록이 한 케이스에 귀속되고 별도 TC gate가 없다.
- 상세 작업: [W05-01](docs/execution/02a-assets-and-scope.md#w05-01), [W05-02](docs/execution/02a-assets-and-scope.md#w05-02), [W05-03](docs/execution/02a-assets-and-scope.md#w05-03), [W05-04](docs/execution/02a-assets-and-scope.md#w05-04), [W05-05](docs/execution/02a-assets-and-scope.md#w05-05), [W05-06](docs/execution/02a-assets-and-scope.md#w05-06).

### W06 — 녹화·수행·증거·장기 facts schema

- [ ] **W06 완료** — 상세0/10. 서비스가 임시 JSON/메모리 저장소를 새 사실 원천으로 만들 필요가 없다.
- 상세 작업: [W06-01](docs/execution/02b-job-evidence-schema.md#w06-01), [W06-10](docs/execution/02b-job-evidence-schema.md#w06-10), [W06-02](docs/execution/02b-job-evidence-schema.md#w06-02), [W06-03](docs/execution/02b-job-evidence-schema.md#w06-03), [W06-04](docs/execution/02b-job-evidence-schema.md#w06-04), [W06-05](docs/execution/02b-job-evidence-schema.md#w06-05), [W06-06](docs/execution/02b-job-evidence-schema.md#w06-06), [W06-07](docs/execution/02b-job-evidence-schema.md#w06-07), [W06-08](docs/execution/02b-job-evidence-schema.md#w06-08), [W06-09](docs/execution/02b-job-evidence-schema.md#w06-09).

### W07 — 실제 환경 adapter·session 수명

- [ ] **W07 완료** — 상세0/4. 관리 UI 탭과 테스트 session이 분리되고 정리 실패 자원을 재배정하지 않는다.
- 상세 작업: [W07-01](docs/execution/03-worker-and-sessions.md#w07-01), [W07-02](docs/execution/03-worker-and-sessions.md#w07-02), [W07-03](docs/execution/03-worker-and-sessions.md#w07-03), [W07-04](docs/execution/03-worker-and-sessions.md#w07-04).

### W08 — 영구 job queue·claim·lease·중복 방지

- [ ] **W08 완료** — 상세0/5. 재접수/재연결 때문에 같은 외부 행동을 추가 실행하지 않는다.
- 상세 작업: [W08-01](docs/execution/03-worker-and-sessions.md#w08-01), [W08-02](docs/execution/03-worker-and-sessions.md#w08-02), [W08-03](docs/execution/03-worker-and-sessions.md#w08-03), [W08-04](docs/execution/03-worker-and-sessions.md#w08-04), [W08-05](docs/execution/03-worker-and-sessions.md#w08-05).

### W09 — 취소·watchdog·process 정리

- [ ] **W09 완료** — 상세0/4. lease 만료를 종료 증명으로 오해하지 않고 ready/quarantine을 설명할 수 있다.
- 상세 작업: [W09-01](docs/execution/03-worker-and-sessions.md#w09-01), [W09-02](docs/execution/03-worker-and-sessions.md#w09-02), [W09-03](docs/execution/03-worker-and-sessions.md#w09-03), [W09-04](docs/execution/03-worker-and-sessions.md#w09-04).

### W10 — 프로젝트·케이스 관리 UI를 실제 DB에 연결

- [ ] **W10 완료** — 상세0/11. 케이스에 검증 내용을 직접 입력하고 데이터가 재접속 후에도 남는다.
- 상세 작업: [W10-01](docs/execution/04a-case-management-ui.md#w10-01), [W10-02](docs/execution/04a-case-management-ui.md#w10-02), [W10-03](docs/execution/04a-case-management-ui.md#w10-03), [W10-04](docs/execution/04a-case-management-ui.md#w10-04), [W10-05](docs/execution/04a-case-management-ui.md#w10-05), [W10-06](docs/execution/04a-case-management-ui.md#w10-06), [W10-07](docs/execution/04a-case-management-ui.md#w10-07), [W10-08](docs/execution/04a-case-management-ui.md#w10-08), [W10-11](docs/execution/04a-case-management-ui.md#w10-11), [W10-09](docs/execution/04a-case-management-ui.md#w10-09), [W10-10](docs/execution/04a-case-management-ui.md#w10-10).

### W11 — 기기·브라우저·앱 빌드·데이터 UI

- [ ] **W11 완료** — 상세0/8. Web은 테스트 브라우저, Android는 직접 연결 기기를 선택하고 필요한 정보를 웹에서 지정한다.
- 상세 작업: [W11-01](docs/execution/04b-environments-and-launcher.md#w11-01), [W11-02](docs/execution/04b-environments-and-launcher.md#w11-02), [W11-03](docs/execution/04b-environments-and-launcher.md#w11-03), [W11-04](docs/execution/04b-environments-and-launcher.md#w11-04), [W11-05](docs/execution/04b-environments-and-launcher.md#w11-05), [W11-06](docs/execution/04b-environments-and-launcher.md#w11-06), [W11-07](docs/execution/04b-environments-and-launcher.md#w11-07), [W11-08](docs/execution/04b-environments-and-launcher.md#w11-08).

### W12 — 로컬 시작·연결 상태·탭 재접속

- [ ] **W12 완료** — 상세0/3. 일상 테스트 조작에 터미널 입력이 필요하지 않고 탭/PC 수명 차이를 안내한다.
- 상세 작업: [W12-01](docs/execution/04b-environments-and-launcher.md#w12-01), [W12-02](docs/execution/04b-environments-and-launcher.md#w12-02), [W12-03](docs/execution/04b-environments-and-launcher.md#w12-03).

### W13 — 실제 action별 전후 캡처·마스킹·정제 로그

- [ ] **W13 완료** — 상세0/4. 대표 step 이미지가 아니라 실제 tap/swipe/type/back별 증거가 남는다.
- 상세 작업: [W13-01](docs/execution/05a-action-evidence-and-models.md#w13-01), [W13-02](docs/execution/05a-action-evidence-and-models.md#w13-02), [W13-03](docs/execution/05a-action-evidence-and-models.md#w13-03), [W13-04](docs/execution/05a-action-evidence-and-models.md#w13-04).

### W14 — spool·ingest·ACK·파일 정합·복구

- [ ] **W14 완료** — 상세0/4. local/spooling/stored·missing/corruption을 실제 보관 상태에 맞게 표시한다.
- 상세 작업: [W14-01](docs/execution/05a-action-evidence-and-models.md#w14-01), [W14-02](docs/execution/05a-action-evidence-and-models.md#w14-02), [W14-03](docs/execution/05a-action-evidence-and-models.md#w14-03), [W14-04](docs/execution/05a-action-evidence-and-models.md#w14-04).

### W15 — 모델 역할별 호출·usage·예산 제어

- [ ] **W15 완료** — 상세0/4. 계측되지 않은 usage를0으로 표시하지 않고 승인한 실행 한도를 신뢰 코드가 적용한다.
- 상세 작업: [W15-01](docs/execution/05a-action-evidence-and-models.md#w15-01), [W15-02](docs/execution/05a-action-evidence-and-models.md#w15-02), [W15-03](docs/execution/05a-action-evidence-and-models.md#w15-03), [W15-04](docs/execution/05a-action-evidence-and-models.md#w15-04).

### W16 — 녹화 마법사·완료/중단 저장·새 후보 생성

- [ ] **W16 완료** — 상세0/8. 실패/중단/반려 여부와 무관하게 기록이 먼저 저장되고 전체 재녹화 후보가 같은 케이스에 남는다.
- 상세 작업: [W16-01](docs/execution/05b-recording-workflow.md#w16-01), [W16-02](docs/execution/05b-recording-workflow.md#w16-02), [W16-03](docs/execution/05b-recording-workflow.md#w16-03), [W16-04](docs/execution/05b-recording-workflow.md#w16-04), [W16-05](docs/execution/05b-recording-workflow.md#w16-05), [W16-06](docs/execution/05b-recording-workflow.md#w16-06), [W16-07](docs/execution/05b-recording-workflow.md#w16-07), [W16-08](docs/execution/05b-recording-workflow.md#w16-08).

### W29 — CUAWright 승인 Web package·격리 direct replay

- [ ] **W29 완료** — 상세0/6. 승인된 exact code/lock/mapping을 격리 재생하고 일반 actor0·driver/lease/capture 통제를 입증한다.
- 상세 작업: [W29-01](docs/execution/06-replay-packages.md#w29-01), [W29-02](docs/execution/06-replay-packages.md#w29-02), [W29-03](docs/execution/06-replay-packages.md#w29-03), [W29-04](docs/execution/06-replay-packages.md#w29-04), [W29-05](docs/execution/06-replay-packages.md#w29-05), [W29-06](docs/execution/06-replay-packages.md#w29-06).

### W30 — Android action plan·결정적/좌표 replay

- [ ] **W30 완료** — 상세0/4. 같은 package·화면 조건으로 재생하며 기록과 현재 검증을 새로 남기고 actor0이다.
- 상세 작업: [W30-01](docs/execution/06-replay-packages.md#w30-01), [W30-02](docs/execution/06-replay-packages.md#w30-02), [W30-03](docs/execution/06-replay-packages.md#w30-03), [W30-04](docs/execution/06-replay-packages.md#w30-04).

### W17 — 미승인 시범과 실제 QA 판정

- [ ] **W17 완료** — 상세0/4. 승인 이전에도 시범이 가능하며 판정/증거는 이번 수행에서 새로 수집한다.
- 상세 작업: [W17-01](docs/execution/07-trial-and-review.md#w17-01), [W17-02](docs/execution/07-trial-and-review.md#w17-02), [W17-03](docs/execution/07-trial-and-review.md#w17-03), [W17-04](docs/execution/07-trial-and-review.md#w17-04).

### W18 — 저장본·동작별 출처/시범 검토 UI

- [ ] **W18 완료** — 상세0/5. 사람이 녹화가 끝나 저장된 동작을 보고 사후 검토하며 runtime 허가와 섞이지 않는다.
- 상세 작업: [W18-01](docs/execution/07-trial-and-review.md#w18-01), [W18-02](docs/execution/07-trial-and-review.md#w18-02), [W18-03](docs/execution/07-trial-and-review.md#w18-03), [W18-04](docs/execution/07-trial-and-review.md#w18-04), [W18-05](docs/execution/07-trial-and-review.md#w18-05).

### W19 — 승인·반려·철회·재녹화 전환의 원자성

- [ ] **W19 완료** — 상세0/4. 저장과 승인이 분리되고 재녹화/철회/경합에서도 잘못된 기본본이나 사라진 승인 근거가 없다.
- 상세 작업: [W19-01](docs/execution/07-trial-and-review.md#w19-01), [W19-02](docs/execution/07-trial-and-review.md#w19-02), [W19-03](docs/execution/07-trial-and-review.md#w19-03), [W19-04](docs/execution/07-trial-and-review.md#w19-04).

### W31 — bounded healing ON/OFF·runtime override·수정 제안

- [ ] **W31 완료** — 상세0/6. 제안은 immutable repair proposal로 남고 채택은 새 전체 REC→OFF trial→사후 승인이다. 원본 code/default/suite 자동 수정0, 생성 code 즉시 치유 실행0.
- 상세 작업: [W31-01](docs/execution/08a-self-healing.md#w31-01), [W31-02](docs/execution/08a-self-healing.md#w31-02), [W31-03](docs/execution/08a-self-healing.md#w31-03), [W31-04](docs/execution/08a-self-healing.md#w31-04), [W31-05](docs/execution/08a-self-healing.md#w31-05), [W31-06](docs/execution/08a-self-healing.md#w31-06).

### W20 — 단독 정식 접수·exact snapshot

- [ ] **W20 완료** — 상세0/4. preview/enqueue/claim에 같은 purpose별 승인 정책이 적용된다.
- 상세 작업: [W20-01](docs/execution/08b-execution-and-suites.md#w20-01), [W20-02](docs/execution/08b-execution-and-suites.md#w20-02), [W20-03](docs/execution/08b-execution-and-suites.md#w20-03), [W20-04](docs/execution/08b-execution-and-suites.md#w20-04).

### W21 — 선택 수행·묶음 revision·순차 정책

- [ ] **W21 완료** — 상세0/5. 사용자가 확인한 구성만 실행되고 빠진 대상/미실행 사유가 분모에 맞게 남는다.
- 상세 작업: [W21-01](docs/execution/08b-execution-and-suites.md#w21-01), [W21-02](docs/execution/08b-execution-and-suites.md#w21-02), [W21-03](docs/execution/08b-execution-and-suites.md#w21-03), [W21-04](docs/execution/08b-execution-and-suites.md#w21-04), [W21-05](docs/execution/08b-execution-and-suites.md#w21-05).

### W22 — 수행/항목 취소·skip·새 재실행

- [ ] **W22 완료** — 상세0/4. original FAIL과 새 RUN PASS를 다른 관측으로 추적할 수 있다.
- 상세 작업: [W22-01](docs/execution/08b-execution-and-suites.md#w22-01), [W22-02](docs/execution/08b-execution-and-suites.md#w22-02), [W22-03](docs/execution/08b-execution-and-suites.md#w22-03), [W22-04](docs/execution/08b-execution-and-suites.md#w22-04).

### W23 — ITEM 근거·실패 분석·7결과 리포트

- [ ] **W23 완료** — 상세0/5. 완료율/검증 통과/전체 통과·미검증을 구분하고 분석 의견이 원본 판정을 바꾸지 않는다.
- 상세 작업: [W23-01](docs/execution/09-results-and-analytics.md#w23-01), [W23-02](docs/execution/09-results-and-analytics.md#w23-02), [W23-03](docs/execution/09-results-and-analytics.md#w23-03), [W23-04](docs/execution/09-results-and-analytics.md#w23-04), [W23-05](docs/execution/09-results-and-analytics.md#w23-05).

### W24 — 누적 facts·기간·cohort·과거 as_of

- [ ] **W24 완료** — 상세0/5. 전체 이력/조건별 최근 완료를 구분하고 원본 실패·이전 보고서를 재해석 없이 재현한다.
- 상세 작업: [W24-01](docs/execution/09-results-and-analytics.md#w24-01), [W24-02](docs/execution/09-results-and-analytics.md#w24-02), [W24-03](docs/execution/09-results-and-analytics.md#w24-03), [W24-04](docs/execution/09-results-and-analytics.md#w24-04), [W24-05](docs/execution/09-results-and-analytics.md#w24-05).

### W25 — CSV·인쇄용 HTML·snapshot export

- [ ] **W25 완료** — 상세0/3. 내보낸 리포트에 원본 IDs·기준·시점이 있고 나중의 결과/비용 보정으로 바뀌지 않는다.
- 상세 작업: [W25-01](docs/execution/09-results-and-analytics.md#w25-01), [W25-02](docs/execution/09-results-and-analytics.md#w25-02), [W25-03](docs/execution/09-results-and-analytics.md#w25-03).

### W26 — 보관 만료·승인 근거 보호·백업복원

- [ ] **W26 완료** — 상세0/5. 파일이 만료돼도 결과/승인 이력을 설명할 수 있고 유효 승인 근거를 GC가 지우지 않는다.
- 상세 작업: [W26-01](docs/execution/10-retention-and-release-gates.md#w26-01), [W26-02](docs/execution/10-retention-and-release-gates.md#w26-02), [W26-03](docs/execution/10-retention-and-release-gates.md#w26-03), [W26-04](docs/execution/10-retention-and-release-gates.md#w26-04), [W26-05](docs/execution/10-retention-and-release-gates.md#w26-05).

### W27 — 통합 장애·중복·복구·metadata 부하

- [ ] **W27 완료** — 상세0/4. 실제 장애 기록과 제약이 있고 중복 행동/원본 덮어쓰기·사라진 근거를 정상 완료로 표시하지 않는다.
- 상세 작업: [W27-01](docs/execution/10-retention-and-release-gates.md#w27-01), [W27-02](docs/execution/10-retention-and-release-gates.md#w27-02), [W27-03](docs/execution/10-retention-and-release-gates.md#w27-03), [W27-04](docs/execution/10-retention-and-release-gates.md#w27-04).

### W32 — 대표 표본 비용·안정성·월3,000 TC 추정

- [ ] **W32 완료** — 상세0/3. 고정 월 예산/실제 성공률을 꾸며내지 않고 비용과 오판/복구 이력을 함께 비교한다. 가격이 낮아도 QA/격리 기준을 낮추지 않는다.
- 상세 작업: [W32-01](docs/execution/10-retention-and-release-gates.md#w32-01), [W32-02](docs/execution/10-retention-and-release-gates.md#w32-02), [W32-03](docs/execution/10-retention-and-release-gates.md#w32-03).

### W28 — 양 플랫폼 전체 UI 동선·MVP 완료 판정

- [ ] **W28 완료** — 상세0/5. 양 플랫폼과 모든 핵심 UI·DB/보관/분석 gate가 통과하고 실제 사용 안내/알려진 제약이 정리되어 있다. 배포/중앙 운영은 자동 착수하지 않는다.
- 상세 작업: [W28-01](docs/execution/10-retention-and-release-gates.md#w28-01), [W28-02](docs/execution/10-retention-and-release-gates.md#w28-02), [W28-03](docs/execution/10-retention-and-release-gates.md#w28-03), [W28-04](docs/execution/10-retention-and-release-gates.md#w28-04), [W28-05](docs/execution/10-retention-and-release-gates.md#w28-05).

## 7. 추적·누락 검사

- UI는 [UI_COVERAGE](docs/execution/UI_COVERAGE.md)의94개 조작·상태 묶음으로 검수한다. 화면 이름/메뉴 존재만으로 완료하지 않는다.
- R35개 중 P0 32개/P1 3개와 UI21/DATA22/실행10 시나리오는 [COVERAGE](docs/execution/COVERAGE.md)에 원문/담당을 연결했다.
- schema/모델 제안·메모·기기 preview/artifact 소유·승인/재녹화/보관의 보완은 [REVIEW](docs/execution/REVIEW.md)에 남겼다.
- T0–T14는 [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)의 설계/기능 묶음이다. 실제 구현 순서는 leaf DAG이며 테스트 파일/함수/근거는 각 카드에 있다.
- 검사 실패나 계약 변경 때 기존 완료 표시를 해제하고 소비 작업까지 영향을 기록한다.

## 8. 작업 기록

| 날짜 | 작업 | 상태 | 근거 | 다음 |
|---|---|---|---|---|
| 2026-10-31 | v0.7 문서 세분화/보완 | 문서 작성, 제품 진척 제외 | 32 W/158상세/13영역·94 UI·요구/시나리오 대응 | 구현 요청 뒤 W01-01 |

구현 때부터 ID/담당/revision/변경파일/검사결과/근거/제약/다음 준비 ID를 기록한다.
지금은 제품 완료가 없으므로 실제 PASS 인계 파일을 만들어 채우지 않는다.

## 9. MVP 이후 범위

아래는 T11/P1 또는 별도 후속 요구이며158개 제품 작업 완료율에 넣지 않는다.

- 중앙 API/PostgreSQL·여러 PC worker·TLS/팀 계정·cloud browser/device farm.
- 일반 Skill Factory 추천/자가 코드 수정·부분 action 병합/중간 재개.
- 선택 API/DB oracle·영상/trace/logcat·수동 화면 제어/녹화·pause/resume.
- 예약/CI/외부 알림·TC CSV import·PDF 자동 생성.
- 파괴적 이력 purge UI. 기본 archive는 기록을 지우지 않는다.

Web 승인 code/Android plan replay·명시 verifier·bounded healing ON/OFF·사후 승인·CSV/인쇄HTML은 이번 MVP다.
