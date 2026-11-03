# 재생 우선 실행·선택 AI 검증·셀프힐링 설계 v0.6

> **2026-11-02 배치 확정:** [중앙 관리·실행 PC 규범](2026-11-02-managed-pc-execution-design.md)이 실행 위치/수명의 우선 규범이다. 관리 서버·DB·증거는 실행 PC와 분리한다. 초기 실행 자원은 현재 PC이며 추가 PC/선택 cloud adapter로 확장한다. 접속 PC는 웹만 사용한다. 실행 PC offline에도 서버 저장본 조회/승인은 가능하고 재녹화/테스트는 불가하다. 실제 분리 배포·단절 감지/원격 실행의 완료는 별도 근거가 필요하다.

기준일: **2026-10-31 (Asia/Seoul)** · 상태: 문서 설계, 제품 미구현·실기기/모델/비용 미측정.

기준 문서: [DESIGN](../../../DESIGN.md), [DATA_DESIGN](../../../DATA_DESIGN.md), [UI_SPEC](../../../UI_SPEC.md), [작업 진행도](../../../WORK_PROGRESS.md). 사용자가 확정한 실행 방향을 반영하며 v0.5의 매 실행 AI 재탐색 기본값을 대체한다.

## 1. 확정한 목표와 적용 방식

| 시점 | 기본 동작 | AI 사용 |
|---|---|---|
| 최초 녹화·전체 재녹화 | 자연어 검증 의도로 탐색하고 동작/코드·전후 PNG/정제 로그·검증 binding 생성 | authoring agent 사용 |
| 시범·정식/회귀 수행 | exact 저장 코드/동작 데이터와 현재 환경으로 재생 | 일반 동작 actor 호출0 |
| 검증 | locator/text/value/URL/UI hierarchy 등의 결정적 검사를 우선 | 명시된 ai_visual 또는 허용한 unknown 보완에만 verifier 호출 |
| 예외·셀프힐링 OFF | 원인·부분 증거 보존, 기존 QA 규칙으로 종료 | healer 호출0 |
| 예외·셀프힐링 ON | 승인된 범위에서 동일 대상의 locator/좌표 재탐색 | 아래 gate를 통과한 때만 제한 호출 |

녹화 중 사람 승인은 없다. 실패/중단/미완성도 먼저 저장한다. 녹화 후 source/trial 동작을 사람이 검토해 exact case version을 승인한다. TC는 선택 참조이며 이 계약의 필수 부모가 아니다.

**실행 모드 이름은 `recorded_replay`**다. `fixed_steps_ai`는 v0.5 보관본의 이전 결정이며 신규 기본 모드로 구현하지 않는다. 모든 검증이 결정적이고 셀프힐링 OFF이면 모델 API 키가 없어도 동작한다. 필요한 앱 로그인 secret/환경 권한은 별도다.

## 2. 비교한 접근과 채택 결정

| 접근 | 이점 | 판단 |
|---|---|---|
| 매 실행 AI 재탐색 | 현재 화면에 대응 | 반복 호출·시간·변동이 기본적으로 발생하므로 기본안에서 제외 |
| 좌표/코드만 재생 | 동작 모델 호출0 | 기본 실행 경로. 환경 조건과 현재 검증을 반드시 결합 |
| 저장 재생 + 선택 verifier + bounded healer | 정상 재생 비용을 낮추고 필요한 시각 검증·국소 복구 지원 | **사용자가 선택한 현행 방향** |

### Web

CUAWright를 **MVP Web authoring 엔진**으로 포함한다. 고정 소스 SHA `35dbcf389ce2d9a77eb22f539c79a1274ea53559`를 출발점으로 모델이 만든 `final_script.py`와 실제 recording trace를 함께 저장한다. 모델/호스트 제공자의 API를 실행할 때마다 task를 새로 풀게 하지 않는다.

생성 코드에서 승인 가능한 `approved_script.py`/runtime dependency lock·step/check mapping을 만드는 변환/계측은 플랫폼 개발 사항이다. 원본 script hash·변환기/패치 버전·결과 hash와 diff를 보존한다. 일반 재생은 exact package를 직접 선택한다. Skill Factory의 자동 추천·parameter 추론·agent fallback을 매 회귀의 진입점으로 사용하지 않는다.

코드는 모든 실제 하위 행동을 `ReplayActionExecutor.execute` 경계로 통과시켜야 한다. raw browser 제어로 capture/lease/정책 검사를 우회하거나 숨은 LLM/helper/subprocess를 호출하는 산출물은 readiness를 통과시키지 않는다. 정적 검사만으로 안전한 코드라고 보장하지 않으며 아래 VM·권한 경계를 함께 적용한다. 원하는 capture/control 계약을 CUAWright 산출물에 연결할 수 있는지는 W01/W29의 실제 검증 gate다.

공개 `run_skill`은 저장 Python의 직접 실행 경로이고 결과 shape가 맞다고 실제 정답을 보장하지 않는다. 생성 코드 내부가 LLM을 호출할 수도 있으므로 플랫폼의 재생/검증 분리를 대체하지 않는다. [직접 실행](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/execute.py), [추천/fallback](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/extensions/skill-factory/src/cuawright/webwright/skill_factory/route.py#L137-L160).

### Android

Mobile-Agent v3.5(고정 SHA `81fa28b564ef7a695521500bc15a0e1324b2b394`)는 녹화/재녹화 시 화면 탐색·행동 제안에 사용한다. 플랫폼이 저장한 structured action plan을 **별도 신뢰 runner**가 ADB로 재생한다. Mobile-Agent 원본 루프를 회귀 때 다시 돌려 매 단계 모델을 호출하지 않는다. Android 재생은 CUAWright의 기존 제공 기능이라고 표현하지 않는다.

target binding 우선순위는 검증된 resource-id/텍스트/영역 기반 관찰 → 현재 화면과 연결한 결정적 locator → 조건을 고정한 좌표다. 각 binding에 target 의미·관찰 방법·expected screen/element 조건을 저장한다. 좌표를 쓸 때 원본/모델/터치 크기·transform·rotation/content bounds를 고정하고 불일치 시 임의 축척/이전 좌표로 탭하지 않는다. UI hierarchy를 읽을 수 없는 화면의 좌표 재생은 같은 화면 조건을 확인할 수 있는 케이스로 제한한다. OCR/시각 추론에 모델을 쓰면 해당 model call로 계측한다.

## 3. 소스 관리·서비스 실행·키 경계

두 upstream은 버전 고정한 `third_party/mobile_agent/`, `third_party/cuawright/`와 `patches/`로 우리 코드와 구분해 관리하는 것을 제안한다. source manifest에 원본 URL/SHA·필요 subtree·LICENSE/NOTICE·patch/lock hash를 남긴다. 별도 공개 GitHub fork는 필수가 아니다. Python/Chromium/ADB/가상화 등 실행 의존성 준비는 소스 포함과 별도이며 아직 설치하지 않는다.

최신 배치는 독립 중앙 관리/저장 서버와 등록 실행 PC worker다. 초기에는 현재 PC의 테스트 브라우저·Android emulator/연결 기기를 사용하고 이후 여러 PC/선택 cloud adapter로 확장한다. 생성 code는 실행 PC에서 격리하고 신뢰 driver만 제어 handle을 소유한다. 접속 PC에는 worker/ADB/VM을 요구하지 않으며 등록 실행 PC에는 필요 환경을 준비한다. 실제 두 엔진 hook·격리·정제/ACK 연결은 PC-04에서 후속 카드로 확정한다. lease/cancel/deadline·event/spool/정리와 초기 합계slot1을 유지한다.

VM은 폐기 가능한 작업 디스크·제한 계정·CPU/RAM/시간 한도·대상 egress allowlist를 사용하고 host 파일/credential/Docker socket을 공유하지 않는다. Job Object/임시 디렉터리/AST 검사만으로 생성 코드를 격리했다고 표현하지 않는다. 서비스 측 격리/worker 제어가 불가능하면 해당 실행 backend gate 실패로 기록하고 배치를 수정한다. 기존 W01/W03 로컬 gate는 이력으로 보존한다. 자동으로 격리 없는 native 실행으로 낮추지 않는다.

**같은 VM에 둔 것만으로 action 경계가 강제되는 것은 아니다.** 승인 코드는 제한된 `qa_runtime` IPC client를 호출하는 형태로 변환하고, Playwright/browser/CDP handle은 별도 신뢰 driver가 독점한다. 생성 script와 driver는 서로 다른 OS 권한·네트워크 공간에 두고 script의 browser endpoint 탐색/접속·프로세스 메모리/credential 읽기·대상 사이트 직접 요청을 막는다. script에는 job/step별 제한 IPC만 열고 driver가 package mapping/권한/lease·전후 capture를 검사한다. 모델 호출 broker는 driver의 승인된 check/episode 이벤트만 수락한다. authoring에서도 관찰/행동은 이 driver 경계를 거치며 자유로운 raw Playwright 제어 산출물을 그대로 승인하지 않는다. 이 제어 경계를 구현하지 못하면 capture 강제 gate 실패다.

모델 키는 설정 UI의 일회 입력→중앙 인증 API→서버 secret store로 저장하고(기존 OS store는 개발 profile), DB/manifest에는 참조만 둔다. authoring/verifier/healer는 각각 역할과 모델 binding이 있다. 재생 VM/script에는 모델 키나 upstream credential 파일을 주입하지 않고 모델 endpoint 접근을 차단한다. 명시 verifier/healer 요청은 신뢰 broker가 목적·job·check/healing ID·한도를 검증해 모델 호출을 대행한다. 생성 코드가 임의로 broker를 호출하거나 새 검증을 만들 수 없다. 녹화 agent의 모델 호출도 gateway를 거쳐 전부 계측한다.

## 4. 저장·검토할 replay package

case version은 아래 immutable manifest를 소유한다. PNG/log는 기존 artifact/typed refs로 연결한다.

- `execution_mode=recorded_replay`, `target_kind`, `authoring_engine`/SHA/patch, `replay_runtime`/version, dependency lock·protocol hash.
- Web 원본/승인 script artifact IDs/hashes 또는 Android action plan artifact ID/hash. 생성/변환 lineage를 함께 보존.
- stable step/action/check IDs·required path·binding·action type/input secret ref·전후 condition·timeout·동작별 계측 mapping.
- 현재 실행 환경/허용 build 범위·data schema/row refs·viewport/rotation/reset/cleanup·실행/모델 한도.
- check별 `deterministic`/`ai_visual`/`deterministic_then_ai_unknown` method와 versioned verifier binding. AI 보완은 미관찰/추출 불가에 대해 미리 허용된 검사에만 가능하고 `violated`를 재판정해 지우지 않는다.
- 승인된 healing capability/scope/binding/한도 및 default OFF. target 역할·허용 endpoint/package·동일 action 범위가 포함된다.

입력/실패/미완성 draft는 package0개, 재생 준비된 exact case version은 package1개다. **sealed source manifest → compiler/계측 검사와 artifact ready → 하나의 materialization transaction에서 package row+새 case version을 함께 확정**한다. version hash에는 package body hash를 넣되 package body에는 produced version ID/hash를 넣지 않는다. package body는 source/input manifest ID/hash·code/plan/lock/mapping만 포함하고, produced version FK는 body 밖 DB receipt에 둔다. raw source manifest도 compiled package hash를 포함하지 않아 순환 hash를 피한다.

컴파일 실패도 package=null/사유를 가진 새 draft로 먼저 보존한다. 같은 manifest 재전송은 같은 receipt/version이며 나중 성공했다고 기존 version에 package를 붙이지 않는다. 재컴파일/변환기 변경은 `package_rebuild` manifest revision(원본 capture/source hash·새 compiler/lock ref, compiled hash 제외)과 새 materialization/version·새 trial/review로 연결한다. 제어 권한 없는 관리 job이며 기존 source/trial/승인은 불변이다. version↔package의 같은 case composite FK는 DEFERRABLE INITIALLY DEFERRED로 commit 시 함께 검증하며 hash body에는 순환 참조가 없다.

승인 근거 trial은 **셀프힐링 OFF·일반 동작 actor0회**로 수행한다. 필요한 verifier 호출은 허용한다. source/승인 package/hash·동작 mapping·완결·필수 evidence·모든 required check PASS·사후 action review를 요구한다. 치유를 써야만 성공한 원본 package를 깨끗한 재생본으로 승인하지 않는다.

실제 PNG/로그 수집은 모델 호출 없이 매 행동에서 계속 수행한다. 실행한 package와 runtime override는 별도 hash로 기록한다. source package를 runtime에서 UPDATE하지 않는다.

## 5. 셀프힐링 ON/OFF 계약

### 5.1 설정과 승인 범위

`healing_policy.allowed`는 해당 case version이 허용하는 capability다. scope를 준비한 기본 profile은 `allowed=true, default_enabled=false`로 제안하며 reviewer가 이 허용 범위를 함께 승인한다. 사용자가 capability 자체를 금지한 case는 false다. execution preview에서 요청하는 `self_healing_enabled`는 기본 OFF이고, true는 승인 capability·호환 healer binding·예산이 있을 때만 허용한다. run/ITEM에 resolved policy hash를 고정한다. scope/권한/모델/상한 확대는 새 case version/trial/승인이다. 실행 중 토글로 snapshot을 바꾸지 않는다.

검증 AI 설정과 healing 설정은 독립이다. healing OFF라도 필수 ai_visual 검사는 수행한다. 필수 AI 검사를 끄거나 키/예산이 없으면 unknown/불명 사유를 남기며 검사 생략 PASS를 만들지 않는다. 순수 결정적 검사+healing OFF는 모델 키 없이 허용한다.

초기 제안 한도: **ITEM당 episode1개·healer 모델 호출 합계2회(전송 retry 포함)·healing wall time30초**. 후보 target 선택/검증 후 원래 동작을 최대1번 dispatch한다. 기존 action retry와 별도 추가 기회를 누적하지 않고 이미 dispatch한 action에는 치유 재실행을 허용하지 않는다. job600초/model80/USD2.00 제안 상한과 lease 여유가 항상 우선한다. 한도를 늘리면 새 policy 승인을 요구한다.

### 5.2 호출 가능한 상황

| trigger/조건 | 처리 |
|---|---|
| target_not_found/ambiguous_target/layout_shift, 원래 action이 아직 dispatch되지 않음, 필수 QA 위반 없음 | ON이면 candidate target 재탐색 가능, OFF이면 action 미완료 근거로 종료 |
| 좌표 replay 전에 해상도/rotation/bounds 불일치 | 재생 차단. MVP의 좌표 환경 변경은 자동 치유 불가; 새 환경/녹화 필요 |
| UI 위치/locator가 달라도 같은 로그인 버튼·같은 action·같은 입력/필수 경로임을 확인 | 정책 검사 후 일시 target binding override1개로 원래 행동 수행 |
| 제품 expected 불일치·필수 path 위반·보안 확인/권한 확대·새 페이지 우회·data 변경·검사 삭제 | 치유 금지. 유효 violation은 FAIL latch |
| 클릭/주문/입력이 이미 처리됐는지 불명, post capture 누락, command timeout·worker lost | 재dispatch 금지. 위반 없으면 INCONCLUSIVE, 위반 있으면 FAIL |
| 앱 crash·임의 popup·네트워크/권한/설치 실패 | 일반 error 정책. 임의 재시작/닫기/초기화로 치유하지 않음 |

버튼 부재가 제품 결함일 수 있으므로 locator 실패라는 이유만으로 정상이라고 간주하지 않는다. 후보의 target 의미·필수 경로·precondition·observed evidence가 부족하면 `rejected/unknown`으로 남기고 수행을 멈춘다. target을 확정할 수 없는 시각 영역은 자동 치유 범위에 넣지 않는다.

동일 target의 최종 허용 주체는 AI가 아닌 신뢰 `validate_healing_proposal`이다. 승인된 대체 식별 조건(예: role/name+container 또는 resource-id/text+화면 context)을 현재 DOM/UI hierarchy로 확인하고, unique1개·visible/enabled·동일 action/input·허용 screen/path를 모두 만족해야 한다. AI가 새 의미/조건을 만들어 통과시킬 수 없다. 좌표 제안도 위 조건으로 확인한 요소의 현재 bounds 안에 있을 때만 허용한다. visual-only/canvas·새 문구 의미 추정으로만 같은 target이라고 주장하는 치유는 MVP에서 제외한다.

### 5.3 실행 순서와 결과

재생의 action lookup 실패 → event/전 화면 보존 → policy/lease/미dispatch/violation/예산 검사 → 허용된 healer 요청 → structured candidate 검증 → **원래 동작**을 trusted executor로 실행 → 후 캡처/현재 QA 검증 → 정상 step으로 복귀 또는 종료다. healer가 만든 임의 Python/shell을 즉시 실행하지 않는다. 실행 failure의 일시 상태와 최종 terminal QA를 구분한다. 이미 terminal인 RUN/ITEM을 치유로 덮지 않고 새 수행을 만든다.

동작 상태는 durable journal/event에 `planned→lookup_failed` 또는 `planned→dispatch_started→acknowledged→observed`로 기록한다. lookup은 read-only로 분리하고 command API 호출 **전에** `dispatch_started`를 local journal에 flush한다. 그 경계를 넘은 뒤의 오류·프로세스 사망은 `unknown`이 가능하며, 실제 command가 전달되지 않았을 것 같아도 미dispatch로 되돌리지 않는다. Playwright click의 navigation timeout이나 ADB 반환/후 캡처 실패는 lookup 실패로 분류하지 않는다. 치유 가능한 것은 driver의 read-only lookup이 실패했고 journal에 dispatch_started가 한 번도 없는 경우뿐이다. journal 기록 자체가 실패하면 command를 발행하지 않는다.

유효 violation 없이 허용 치유를 사용하고 이후 모든 필수 검사·근거가 충족되면 `display_result=PASS, healing_used=true`와 **‘PASS · 셀프힐링 사용’**을 표시한다. 새 8번째 결과 bucket을 만들지 않는다. 유효 필수 위반이 있으면 이후 관찰/시도가 성공해도 최종 FAIL이다. unavailable target은 실제 필수 조건 부재가 증명되면 FAIL, 근거/결과가 불명확하면 INCONCLUSIVE, 실행 전 정책/환경 불가면 BLOCKED다.

항상 원래 lookup 오류·모델 제안/짧은 근거·정책 판정·변경 전후 target/evidence·실제 dispatch 여부·후속 check·복구 결과·usage/cost를 보존한다. 비밀/hidden reasoning은 저장하지 않는다. 새 재실행은 original ref가 있는 새 RUN/ITEM이다.

## 6. 치유 결과의 재사용과 사람 승인

치유 결과는 immutable `repair_proposals`로 저장한다. 기존 case version/녹화/script·current approval·suite는 그대로 둔다. **수정 제안은 자동 승인 가능한 새 case version이 아니다.**

MVP에서는 사용자가 제안 diff/근거를 보고 **전체 재녹화의 입력 제안으로 적용**한다. 동일 검증 의도로 새 REC/코드 또는 action plan·전후 증거를 만든 뒤 healing OFF trial·사후 review·새 승인을 거친다. 부분 step만 병합해 즉시 default로 저장하는 기능은 후속이다. 이 전체 재녹화 비용도 유지보수 비용으로 계측한다.

새 승인 시에만 default를 원자 전환하고 old approval은 자동 철회하지 않는다. 기존 suite/queued/running exact snapshot은 유지하며 묶음 갱신·철회는 기존 명시 절차를 따른다. source/final facts/기존 보고서는 UPDATE하지 않는다.

## 7. DB·API·인터페이스

구체 FK/protection/retention은 DATA_DESIGN과 결합한다. 다음 logical entities를 추가한다.

| 단위 | 최소 필드와 제약 |
|---|---|
| replay_packages/package_artifacts | project/case/version ID, mode/runtime/hash·source/script/plan/lock·mapping/transform version; exact version당0..1개, replay ready일 때1개 필수, same-case composite FK. produced version FK는 hash body 밖 receipt |
| package_steps | package+stable step/action ID, semantic target hash, original artifact/line mapping·safe dispatch contract; code/plan 실제 행동과 mapping 일치 검사 |
| case checks/healing policies | immutable method/binding/scope/limits/hash. execution/ITEM에는 resolved snapshot과 ON/OFF 요청·actual counters |
| healing_episodes | project/ITEM/attempt/package/action ID, trigger/captured error, outcome/status, policy hash·seq/time·dispatch_state, reserved budget; UNIQUE(ITEM,episode ordinal), 초기 episode≤1을 transaction으로 강제 |
| healing_events | episode/commit_seq, proposed target·policy acceptance/dispatch/검증/종료·hash/evidence refs; append-only, 동일 source job/attempt/action membership 검사 |
| runtime_overrides | episode ID UNIQUE, original binding hash·candidate hash·허용 동작/target 의미·actual dispatch action ID; source package 수정 금지 |
| repair_proposals | project/case/source version/package/ITEM/episode, proposed diff/hash/근거, actor/time, 새 REC로 채택 ref nullable; source/proposal immutable, 채택은 별도 event |

episode 예약/호출 한도/usage 예약은 같은 transaction/CAS로 중복 healer 발행을 막는다. 불명한 네트워크 요청을 무조건 재발행하지 않고 provider request ID/계측 상태를 남긴다. model_calls role은 `authoring/verification/healing/maintenance`와 owner(check 또는 episode)로 연결한다. runtime action은 `replay/healing_override` provenance를 갖고 before/after artifact refs를 동일 capture 계약으로 남긴다.

최종 ITEM 최소 facts에 `action_actor_call_count, verification_call_count, healing_call_count, healing_used, healing_outcome, original_execution_error, unassisted_pass, package_hash, resolved_healing_policy_hash`를 seal한다. `unassisted_pass`는 PASS이고 action lookup/dispatch 오류·retry/recovery·healing이 없을 때만 true다. AI verifier 사용 자체는 action assistance로 세지 않으며 별도 count로 노출한다. episode/proposal 최소 facts/hash는 장기 보존하고 큰 정제 payload/PNG는 기존 만료·보호 규칙을 따른다. 승인 package/script/plan/lock·mapping은 유효 승인 동안 보호한다.

| 경계 | 제안 signature/추가 API |
|---|---|
| package 생성·검사 | `compile_replay_package(source_manifest_id, target_kind) -> ReplayPackage`; `validate_replay_package(package_id) -> ReplayReadiness` |
| 재생 | `ReplayRunner.run(spec: ExecutionSpec, sink: EventSink, control: RunControl) -> ReplayOutcome` |
| 모든 실제 행동 | `ReplayActionExecutor.execute(action: RecordedAction, context: ActionContext) -> ActionRecord` |
| 치유 요청/검사 | `HealingService.propose(request: HealingRequest, control: RunControl) -> HealingProposal`; `validate_healing_proposal(proposal, approved_policy, observation) -> HealingDecision` |
| 입력/조회 | execution-previews/executions에 `self_healing_enabled`·package/policy hash; GET case-versions/{v}/replay-package·case-runs/{i}/healing-episodes |
| 수정 제안 | GET repair-proposals/{id}; POST cases/{c}/rerecordings에 `repair_proposal_id` optional·base version·reason. 제안 diff 적용은 새 입력/REC이며 기존 source 불변 |

## 8. 비용·월 3,000개 TC와 계측 gate

기준 workload는 **월1회 릴리스·3,000 TC를 각각 한 환경/data에서1회 수행**이다. 여러 data/환경/재시도·재녹화는 추가 관측/비용으로 분리한다. 기존 RUN당 data 확장 후 ITEM100개 cap은 유지하므로 이 workload는 최소30개 RUN으로 나눠 같은 `release_label`/요청 범위로 누적 분석한다. 3,000개 단일 RUN 지원이나 단일 실행 버튼을 이미 제공한다고 가정하지 않는다. 고정 월 예산은 아직 정하지 않았으며 모델·제공자/캐시·이미지·출력 크기까지 실측한 뒤 결정한다. 특정 단가나 예전 대화의 계산 예시를 요금 보장으로 고정하지 않는다.

보고 비용은 최초 authoring, 반복 verification, 예외 healing, 수정/전체 재녹화 maintenance로 나눈다. 정상 replay actor 비용은0이어야 하고 숨은 helper/router 호출은 부정 시험으로 탐지한다. 모든 정제 PNG를 모델로 전송하지 않는다. 검사에 필요한 현재 화면/영역과 기대/관찰만 전송하되 필요한 근거를 잘라 거짓 PASS를 만들지 않는다.

W32에서 대표30–50 TC·정상/제품 결함/locator 변경/결과 불명·각 구성3회 제안으로 비교한다. (1) 전부 결정적 재생/OFF (2) 재생+필요 AI검증/OFF (3) 재생+필요검증/ON을 같은 데이터/조건에서 측정한다. authoring 비용은 별도 측정하고 반복으로 나눈 상각값도 표시한다.

실측 지표: model role별 요청 수·image 포함 input/cache/output/계측 null·tariff/currency/비용 p50/p95, unassisted PASS/치유 후 PASS/치유 실패/실제 제품 FAIL/미검증·거짓PASS, 전체시간·모델대기·저장량이다. 월 예상비용은 관측 workload×단가/usage·치유 빈도로 추정하고 표본수/조건·미계측 범위를 표시한다. 호출이 저렴해도 판정 정확성 gate를 낮추지 않는다.

## 9. 필수 합격/부정 시나리오 — 향후 검증

1. Web 승인 code/Android plan 직접 재생 + 결정적 검사 + healing OFF에서 모델 credential 제거·endpoint 차단 상태의 actor/verifier/healer 호출0, 매 action 증거 수집 성공.
2. 명시 AI check만 verifier 호출, healing OFF/ON과 독립. AI unknown/timeout·예산 부족은 검사 생략 PASS가 아님.
3. ON에서 미dispatch locator 변경만 episode1개/최대2호출/30초 안에 치유. OFF/한도 소진/lease 부족이면 호출0 또는 추가 호출 차단.
4. 같은 project/case의 다른 ITEM/attempt/source package/evidence 혼입·중복 trigger/이벤트 재전송·동시 episode 예약을 거부/멱등 처리.
5. expected/path violation·알 수 없는 popup·입력/주문 결과 불명·capture missing·rotation mismatch에서 치유 재dispatch 금지. 이미 관측한 FAIL은 최종 FAIL.
6. 허용 치유 후 모든 check 만족은 PASS+healing_used, 결과7종 합계와 unassisted 지표가 일치. terminal FAIL 이후 치유는 새 RUN.
7. runtime override·repair proposal 저장 후 기존 script/case/default/suite/과거 export hash 불변. 제안 채택은 새 전체 REC→OFF trial→사후 승인.
8. 생성 script가 직접 LLM/helper/subprocess·raw action으로 broker/계측/정책을 우회하면 package 검증 또는 실제 격리 경계에서 차단. VM 부재를 정상 배치로 가장하지 않음.
9. 보호된 승인 package/원본/lock/mapping·근거는 GC 불가, 파일 만료 뒤 healing/final facts·usage ledger/as_of 재현.
10. 대표 workload의 비용/지연·오판을 측정하고 월3,000 TC 추정과 저장량을 제시. 측정 전 ‘무조건 저렴/성공’으로 표현하지 않음.

본 문서와 root 설계/계획을 수정하는 작업은 제품 코드·프런트 샘플·설치·실기기/모델 실행·배포를 변경하거나 수행하지 않는다. 기존 `prototype/`는 v0.5 모의 동선이며 v0.6 replay/healing 구현 증거가 아니다.
