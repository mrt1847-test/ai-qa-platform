# AI QA 플랫폼 코드 작업 진행도 · Implementation Plan

기준일: **2026-10-31 (Asia/Seoul)** · 기준 설계: **v0.6** · 상태: **제품 구현 착수 전**

> **For agentic workers:** 구현 요청을 받은 뒤 `superpowers:executing-plans` 또는 사용자가 선택한 실행 방식으로 한 작업 단위씩 진행한다. 체크박스는 실제 구현·검증 근거가 있을 때만 갱신한다. 이 문서를 작성하는 작업에 설치·실기기/모델 실행·배포는 포함하지 않는다.

**Goal:** 디바이스 선택 → 검증 내용 입력 → AI 녹화/먼저 저장 → 사람이 저장본 검토·승인 → 단독/선택/묶음 수행 → 결과 누적 분석을 실제 제품으로 완성한다.

**Architecture:** Web은 CUAWright authoring/격리 승인 code replay, Android는 Mobile-Agent authoring/신뢰 recorded action replay다. 정상 동작 actor0·필요 verifier·기본OFF bounded healer를 분리한다. 로컬 웹 UI/API와 별도 worker를 둔다. API가 SQLite의 유일한 writer이고 worker는 HTTP와 정제 spool을 사용한다. Web은 Playwright, USB Android는 ADB를 연결하며 녹화·버전·승인·수행 결과와 파일 보관을 분리한다.

**Tech Stack:** Python 3.11 잠정, FastAPI/Jinja2/HTMX, SQLAlchemy/Alembic/SQLite, 같은 PC 격리 Linux VM/Chromium·호스트 ADB, CUAWright + Mobile-Agent v3.5 연동. 구체 dependency/model lock은 W01–W03에서 확인한다.

**Spec:** [재생·셀프힐링 상세](docs/superpowers/specs/2026-10-31-replay-and-self-healing-design.md), [중심 설계](DESIGN.md), [UI 명세](UI_SPEC.md), [데이터·승인·재녹화 설계](DATA_DESIGN.md), [기술 조사](RESEARCH.md), [상세 구현 계획 T0–T14](IMPLEMENTATION_PLAN.md).

v0.6은 사용자가 선택한 AI 녹화·기록 replay·선택 AI 검증·healing ON/OFF를 반영한다. [v0.5 진행표](docs/history/v0.5/WORK_PROGRESS.md)는 보관했다. 기존 W01–W28 ID는 유지하고 W29–W32를 추가했다. **ID는 식별자이고 실행 순서는 아래 선행 관계/단계표를 따른다.**

## 1. 지금 어디까지 되어 있나

| 구분 | 현재 상태 | 근거 |
|---|---|---|
| 기술 조사·설계 | 검토용 문서 작성 완료 | DESIGN / RESEARCH / UI_SPEC / DATA_DESIGN |
| 클릭 가능한 프런트 샘플 | 작성·주요 데스크톱 동선 확인 완료 | [체험 안내](prototype/README.md), [확인 기록](prototype/VALIDATION.md) |
| 실제 제품 구현 | **완료 0 / 32개 작업 단위** | 아래 W01–W32 모두 미착수 |
| 실제 AI·Web·Android 검증 | 미실행 | 모의 화면/결과를 실기기 근거로 계산하지 않음 |
| 실제 DB·보관·복구 검증 | 미실행 | 논리 설계만 존재 |
| 다음 착수 단위 | **W01 Web 연동 가능성 검증** | 제품 구현 요청 후 진행 |

`prototype/`는 화면과 동선을 검토하는 샘플이다. 제품의 API/DB/worker가 구현됐다는 근거로 사용하지 않는다. UI의 배치·문구는 참고하되, localStorage의 샘플 상태 관리와 모의 승인/판정 코드를 제품에 그대로 연결하지 않는다.

## 2. 어떤 순서로 진행하나

**기술 검증 → 데이터 기반 → worker 제어 → 실제 관리 UI → 녹화 저장 → package/재생 → 사후 승인 → 셀프힐링/정식 수행 → 누적 분석 → 운영·비용 검증** 순서다.

| 단계 | 작업 단위 | 현재 완료 | 이 단계가 끝나면 확인할 결과 | 기존 계획 |
|---|---|---|---|---|
| A. 실제 연결 가능성 확인 | W01–W03 | 0 / 3 | CUAWright Web authoring/격리·Android 관찰/행동·모델 프로토콜 gate | T0, T1 탐색 |
| B. DB·버전·권한 기반 | W04–W06 | 0 / 3 | 불변버전/package0..1·episode/proposal/dispatch·facts schema | T2 |
| C. worker·작업 제어 | W07–W09 | 0 / 3 | VM browser/호스트USB·독점·취소/정리 | T1 |
| D. 실제 관리 화면 | W10–W12 | 0 / 3 | case/환경/계정·AI role/재생·healing 설정 UI | T3 |
| E. 녹화·먼저 저장 | W13–W16 | 0 / 4 | AI authoring trace/raw script·plan·동작별 근거·실패/중단 보존 | T4, T5 |
| F. 승인 package·재생 | W29–W30 | 0 / 2 | Web IPC script·격리/driver, Android plan, actor0 실제 재생 | T12 |
| G. 시범·사후 승인 | W17–W19 | 0 / 3 | OFF clean trial·현재 검사·package/scope 승인 | T6 |
| H. healing·정식 수행 | W31 → W20–W22 | 0 / 4 | bounded ON/OFF·exact 단독/선택/suite·원본 실패 유지 | T13, T7 |
| I. 결과·누적 분석 | W23–W25 | 0 / 3 | 정상/치유 PASS·role 비용·조건/as_of/export | T8 |
| J. 운영·비용·MVP | W26 → W27 → W32 → W28 | 0 / 4 | 보관/복원·장애·월3,000 TC 표본 추정·양 플랫폼 gate | T9, T14, T10 |

**순서를 정할 때 주의할 두 곳:**

- W01–W03의 기기/브라우저 시험은 연결 가능성을 확인하는 탐색이다. 영구 작업 큐는 DB 계약 W04–W06 뒤 W08에서 구현한다. DB가 없는 임시 메모리 큐를 제품 기반으로 만들지 않는다.
- 승인에 필요한 **시범 수행은 W17에서 먼저** 만든다. 그때 공통 RUN/ITEM/runner의 최소 경로를 구현하고 W20에서 같은 경로에 정식 승인 검사를 확장한다. 시범용/정식용 runner를 따로 만들지 않는다.

### 단계 종료 시 직접 확인하는 지점

- [ ] A 통과: 양 플랫폼과 필수 action capture 경계 확인. 한쪽이 불가능하면 엔진/연동 결정을 먼저 수정한다.
- [ ] B–D 통과: 실제 API/DB로 케이스를 저장하고 재시작·새로고침 후 조회한다. 프런트의 모의 데이터를 교체한다.
- [ ] E 통과: 녹화 완료/중단본을 승인 없이 저장하고 동작별 근거를 조회한다.
- [ ] F 통과: 승인 code/action package를 모델 key/endpoint 없이 재생하고 일반 actor0·매 action 계측·VM/driver 경계를 확인한다.
- [ ] G 통과: 저장 → 시범 → 출처/시범 검토 → 승인 순서가 작동한다. 재녹화 실패는 기존 승인본을 바꾸지 않는다.
- [ ] H–I 통과: exact 승인본을 실행하고 원본 FAIL/새 PASS·분모·누적 조건을 구분한다.
- [ ] J 통과: 두 플랫폼의 정상/부정/장애·복원 근거가 있고, 알려진 제약을 반영한 뒤 MVP 완료로 표시한다.

위 단계 체크는 W 작업 완료를 요약한다. **제품 진행률의 분모는 W01–W32의 ‘완료’ 체크 32개뿐**이며, 준비 문서·하위 체크·후속 기능은 포함하지 않는다. 개수 기준 진행률은 공수/일정 달성률이 아니다.

## 3. 한 번의 코드 작업은 어느 정도로 나누나

**한 W 단위는 하나의 결과를 독립적으로 검토할 수 있는 크기**다. 한 화면 전체나 모든 DB 테이블을 한꺼번에 구현하고 나중에 검증하지 않는다. 반대로 설정 파일 한 개 같은 준비만 별도 성과로 세지 않고 그 설정이 필요한 기능에 포함한다.

작업을 시작하면 해당 W 하나를 현재 작업으로 기록한다. 선행 단위가 통과하지 않은 작업을 완료 처리하지 않는다. 더 나눠야 하면 `W16-a/W16-b`처럼 하위 작업으로 적고 부모 W 완료 조건을 모두 충족한 뒤 체크한다. 분할했다고 전체 32개 분모를 임의로 바꾸지 않는다.

매 작업에서 적용하는 순서:

1. 선행 결과와 연결 계약/변경 파일을 확인한다.
2. 아래에 명시한 실패·누락·경합 사례를 재현하는 시험을 작성하고, 구현 전 실패 이유를 확인한다. 단순 문구/CSS 변경은 필요한 화면 확인으로 검증한다.
3. 해당 작업의 최소 기능을 구현하고 실제 API/DB/worker에 연결한다.
4. 지정 검증과 해당 화면/실기기 확인을 실행한다. `SKIP`·모의 PASS를 필수 실제 시험의 통과로 세지 않는다.
5. 변경 diff와 검증 근거를 검토하고, 작업 기록 및 완료 체크를 갱신한다. 커밋/PR은 실행 시점의 저장소 지침·작업 방식에 맞춰 진행한다.

완료 기록에는 **작업 ID, 변경 파일, 실행한 검사와 결과, 실제 근거 위치, 남은 제약**이 있어야 한다. 코드만 작성했거나 UI 버튼만 보이면 완료가 아니다.

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

## 6. 코드의 책임 경계

아래는 **향후 만들 파일**이다. 현재 제품 파일이 존재한다는 뜻이 아니다. 상세 signature/DTO는 DESIGN §8.1과 IMPLEMENTATION_PLAN의 해당 T 계약을 따른다. 계약을 바꿀 때 두 문서와 이 진행표를 함께 맞춘다.

| 경로 | 책임 | 최초 담당 |
|---|---|---|
| `pyproject.toml`, dependency lock, `third_party/{mobile_agent,cuawright}/`, `patches/` | 실행 가능한 버전/연동 패치·라이선스 고정 | W01–W03 |
| `src/aiqa/contracts.py` | Case/REC/RUN/ITEM/job·환경·event DTO와 상태 | W04–W06 |
| `src/aiqa/store/models.py`, `migrations/` | schema/FK/불변 제약·revision/commit cursor | W04–W06 |
| `src/aiqa/api/auth.py`, `src/aiqa/api/app.py` | API 생성·인증/권한/CSRF·worker scope | W04 |
| `src/aiqa/domain/versions.py` | 케이스 불변 버전·readiness·선택 TC metadata | W05 |
| `src/aiqa/environments/` | 실제 Chromium/USB 자원·session·앱 준비 | W07, W11 |
| `src/aiqa/store/queue.py`, `src/aiqa/worker/` | 영구 job·배정/lease·실행/취소·정리 | W08–W09 |
| `src/aiqa/api/catalog.py`, `cases.py`, `resources.py` | 관리 자산·케이스·기기 API | W10–W11 |
| `src/aiqa/web/templates/`, `web/static/` | 실제 API와 연결되는 UI | W10 이후 기능별 |
| `src/aiqa/launcher.py` | 탭과 독립된 API/worker 시작·상태·종료 | W12 |
| `src/aiqa/recording/action_executor.py`, `src/aiqa/adapters/` | 정책 검사·하위 action 실행/계측 | W13 |
| `src/aiqa/store/evidence.py`, `artifacts.py` | 정제 ingest/ACK·파일 정합·protection/GC | W14, W26 |
| `src/aiqa/models/client.py`, `compatibility.py` | 모델 호환·역할별 호출·usage/budget | W03, W15 |
| `src/aiqa/recording/service.py`, `review_manifest.py` | 녹화→불변 receipt/초안·검토 snapshot | W16, W18 |
| `src/aiqa/validation/`, `domain/verdicts.py` | 현재 oracle·필수 경로·FAIL latch | W17 |
| `src/aiqa/domain/approvals.py` | 승인/반려/철회·default/pin 원자성 | W19 |
| `src/aiqa/api/executions.py`, `domain/suites.py` | 공통 수행 접수·exact 묶음 구성 | W17, W20–W22 |
| `src/aiqa/domain/reporting.py`, `api/reports.py` | 불변 결과·분석/집계·누적/내보내기 | W23–W25 |
| `src/aiqa/replay/{packages,web_runner,android_runner,driver,ipc,action_executor}.py` | 승인 package·직접 replay·browser handle 신뢰 driver 독점 | W29–W30 |
| `src/aiqa/worker/isolated_web.py`, `src/aiqa/models/broker.py` | 같은 PC VM 제어·AI role/check/episode/예산 게이트 | W29, W31 |
| `src/aiqa/healing/{service,policy,proposals}.py` | typed proposal/결정적 검증·runtime override·수정 제안 | W31 |
| `tools/validation/benchmark_replay.py`, `tests/integration/test_cost_accounting.py` | 대표 workload 비용/안정성·3,000 TC 추정 | W32 |
| `tests/`, `docs/validation/` | 각 단위의 자동 검사·실제 근거 | 각 W 담당 |

## 7. 단계별 작업 체크리스트

모든 검사 명령과 파일은 **앞으로 구현할 때의 기준**이다. 이번에 해당 시험을 실행했다는 뜻이 아니다. 각 단위의 ‘Wxx 완료’ 체크가 진행률의 원본이다.

### A. 실제 연결 가능성 확인

#### W01 — CUAWright Web authoring·계측·격리 가능성

선행: 기존 조사/실행 설계. 연결: **T0, T12 탐색**. 산출: source code 생성→driver 계측→직접 replay·VM 경계가 가능한지 판단.

- [ ] `tests/integration/test_upstream_contracts.py`에 CUAWright response/code 형식·원본/승인 script/step mapping·raw Playwright/CDP/helper 우회·한글/공백 경로를 작성한다.
- [ ] CUAWright SHA `35dbcf389ce2d9a77eb22f539c79a1274ea53559` 기반 최소 authoring/IPC·신뢰 driver·로컬 VM 탐색을 하고 dependency/patch/license를 고정한다. 관리 API에서 생성 code를 실행하지 않는다.
- [ ] `python -m pytest tests/integration/test_upstream_contracts.py -k web -q`와 합성 Web 실제 관찰/행동/전후 capture·raw endpoint 차단을 `docs/validation/web-spike.md`에 기록한다. VM·계측 미확보는 통과가 아니다.
- [ ] **W01 완료** — CUAWright Web authoring/격리/동작 계측·직접 replay의 가능/불가·패치·제약이 기록되어 있다.

#### W02 — Android USB·좌표·입력 가능성

선행: W01의 실행/검증 구조. 연결: **T0, T1 탐색**. 산출: 지정 Android에서 행동·한글 입력·전후 캡처·IME 복구 근거.

- [ ] `tests/integration/test_upstream_contracts.py`에 좌표 transform/회전·해상도 변경/unknown action·ADB 오류 사례를 추가한다.
- [ ] `src/aiqa/adapters/mobile_agent_android.py`와 `patches/mobile-agent/`에 serial 고정·허용 argument list·관찰 정제 경계를 연결한다. 임의 raw shell 실행은 허용하지 않는다.
- [ ] `python -m pytest tests/integration/test_upstream_contracts.py -k android -q`와 실제 tap/type/swipe/back·USB 단절·IME 복구를 확인해 `docs/validation/android-spike.md`에 기록한다.
- [ ] **W02 완료** — 실제 좌표/입력/전후 캡처·Mobile-Agent authoring trace를 Android plan으로 재생할 지원 범위와 Windows 제약이 확인되어 있다.

#### W03 — 모델 형식·upstream 채택 결정

선행: W01–W02. 연결: **T0**. 산출: 양 플랫폼이 사용할 모델/엔진/patch/lock과 P0 판단.

- [ ] `tests/integration/test_upstream_contracts.py`에 image/action 응답 호환·timeout·잘못된 action·usage 누락=null 사례를 추가한다.
- [ ] `src/aiqa/models/compatibility.py`의 `check_binding`/`describe_capture_boundaries`를 구현하고, 허용한 모델 접근/합성 환경으로 Web/Android 최소 호출을 확인한다. SDK/model alias와 실제 응답 ID를 구분한다.
- [ ] `python -m pytest tests/integration/test_upstream_contracts.py -q`와 실제 근거를 `docs/validation/upstream.md`에 기록한다. 실패 시 CUAWright code 변환/driver/VM 또는 Android plan/배치를 수정한다. replay/격리 gate를 없애지 않는다.
- [ ] **W03 완료** — 양 플랫폼 필수 capture/행동 경계가 확보되고 모델/엔진 결정이 문서에 반영되어 있다.

### B. DB·버전·권한 기반

#### W04 — project scope·API 권한·저장 연결

선행: W03. 연결: **T2**. 산출: 실제 API/SQLite로 프로젝트를 저장·조회하며 다른 project 접근을 차단.

- [ ] `tests/integration/test_assets_versions.py`에 DB 재시작 후 프로젝트 유지·다른 project ID/artifact 접근 거부·CSRF/worker 권한 오류를 작성한다.
- [ ] `contracts.py`, `store/models.py`, `migrations/`, `api/app.py`, `api/auth.py`에 project/actor·API 세션·worker scope·감사·OS secret ref와 연결별 FK 활성화를 구현한다. 경로는 모두 위 책임표의 `src/aiqa/` 아래다.
- [ ] `python -m pytest tests/integration/test_assets_versions.py -k 'project or auth or secret' -q`를 확인한다. 런타임 DB는 OneDrive 밖 `%LOCALAPPDATA%/AIQA/`에 둔다.
- [ ] **W04 완료** — 실제 자산 저장과 권한 경계를 확인했고 비밀 원문이 응답/DB definition에 없다.

#### W05 — 케이스·불변 버전·선택 TC·데이터 revision

선행: W04. 연결: **T2**. 산출: 검증 정의/설정/절차를 한 버전으로 저장하고 새 수정은 새 revision.

- [ ] `tests/integration/test_assets_versions.py`에 content UPDATE 거부·revision CAS409·다른 case FK 거부·TC0개/null 정상·TC 변경/보관 시 기존 승인/hash 유지 사례를 추가한다.
- [ ] `domain/versions.py`, `store/models.py`, `migrations/`에 `save_case_revision`/`compute_case_readiness`/`set_tc_reference`, canonical hash·stable step/check projection·dataset revisions를 구현한다. 명시 TC import 수락만 새 case version을 만든다.
- [ ] `python -m pytest tests/integration/test_assets_versions.py -k 'version or tc or dataset' -q`로 소속·불변성·모호한 정의의 draft 저장을 확인한다.
- [ ] **W05 완료** — 검증 내용·녹화 기록이 한 케이스에 귀속되고 별도 TC gate가 없다.

#### W06 — 녹화·수행·증거·장기 facts schema

선행: W05. 연결: **T2, DATA_DESIGN §3–5**. 산출: 이후 서비스들이 의존할 영구 ID/관계·멱등/불변/보관 기반.

- [ ] `tests/integration/test_storage_schema.py`에 REC/ITEM owner 배타·다른 attempt action/check FK 거부·manifest별 produced version1개·불변 final facts·commit_seq 원자 증가를 작성한다.
- [ ] `store/models.py`, `migrations/`, `contracts.py`에 manifests/materializations/review membership·RUN/ITEM/jobs/attempts·typed artifact refs/protections/releases·detail payload 분리·finalization/lifecycle/usage ledger를 구현한다. provenance ref와 active 보호를 구분한다.
- [ ] `python -m pytest tests/integration/test_storage_schema.py -q`와 schema migration/재시작 검사를 통과한다. approval/default 같은 교차 row 적합성은 W19의 transaction 검사로 완성한다.
- [ ] replay_packages/package_steps0..1·비순환 hash/원자 materialization·healing episodes/events/overrides/proposals·dispatch 상태·role usage·resolved ON/OFF와 DATA_DESIGN §11 추가15–22의 소속 제약을 schema에 연결해 검사한다.
- [ ] **W06 완료** — 서비스가 임시 JSON/메모리 저장소를 새 사실 원천으로 만들 필요가 없다.

### C. worker·작업 제어

#### W07 — 실제 환경 adapter·session 수명

선행: W06, W01–W02 근거. 연결: **T1**. 산출: 실제 Chromium context/USB device의 확보·준비·해제.

- [ ] `tests/integration/test_sessions_queue.py`에 별도 Web context·device serial 고정·중복 release·정리 실패 quarantine을 작성한다.
- [ ] `environments/base.py`, `isolated_local_chromium.py`, `usb_android.py`, `worker/resources.py`에 DESIGN의 `EnvironmentAdapter`와 `acquire_environment`/`release_environment` 연결을 구현한다.
- [ ] `python -m pytest tests/integration/test_sessions_queue.py -k session -q`와 Windows 실제 browser/context/IME 해제를 확인한다.
- [ ] 같은 PC VM Chromium·신뢰 driver/제한 IPC의 session/lease/cancel·파일 전송/격리 경계, Android 호스트USB를 실제 환경으로 연결한다.
- [ ] **W07 완료** — 관리 UI 탭과 테스트 session이 분리되고 정리 실패 자원을 재배정하지 않는다.

#### W08 — 영구 job queue·claim·lease·중복 방지

선행: W07. 연결: **T1**. 산출: API 재시작 후에도 남는 작업과 자원 독점 배정.

- [ ] `tests/integration/test_sessions_queue.py`에 동시 claim·같은 key 재접수·같은 event 재전송·generation 만료·slot1·기기당1을 작성한다.
- [ ] `store/queue.py`, `worker/service.py`, `api/worker.py`에 `claim_job`·heartbeat/ACK·조건부 lease 갱신·DB receipt를 구현한다. REC/ITEM 생성+job 접수는 원자 처리하고, 긴 작업은 실행 완료를 기다리지 않고202/job ID를 반환한다.
- [ ] `python -m pytest tests/integration/test_sessions_queue.py -k 'claim or lease or duplicate' -q`로 heartbeat10초/lease45초·늦은 generation409를 확인한다.
- [ ] **W08 완료** — 재접수/재연결 때문에 같은 외부 행동을 추가 실행하지 않는다.

#### W09 — 취소·watchdog·process 정리

선행: W08. 연결: **T1**. 산출: 모델 응답 대기/프로세스 장애 중에도 행동 차단·정리/격리.

- [ ] `tests/integration/test_sessions_queue.py`에 취소/완료 경합·늦은 모델 응답·worker 사망·cleanup timeout을 작성한다.
- [ ] `worker/runner.py`, `worker/processes.py`, `store/queue.py`에 `cancel_job`, watchdog30초/행동 전 lease 여유10초·취소 유예5초·정리30초·Windows process tree 정리를 구현한다.
- [ ] `python -m pytest tests/integration/test_sessions_queue.py -q`와 실제 Windows 종료/USB 해제 검사를 기록한다. REC/관리 job 모든 terminal 경로의 QA는 null이어야 한다.
- [ ] **W09 완료** — lease 만료를 종료 증명으로 오해하지 않고 ready/quarantine을 설명할 수 있다.

### D. 실제 관리 화면

#### W10 — 프로젝트·케이스 관리 UI를 실제 DB에 연결

선행: W09. 연결: **T3 / UI01–04·15·선택16**. 산출: 샘플 대신 실제 저장을 사용하는 목록/상세/편집.

- [ ] `tests/acceptance/test_asset_ui.py`에 빈 목록·검색/분류/page·복제/보관·새로고침 복원·미저장/403/409·TC0개 정상 동선을 작성한다.
- [ ] `api/catalog.py`, `api/cases.py`, `web/templates/{base,projects,overview,cases,case_detail,settings,tcs}.html`, `web/static/`에 CRUD·통합 탭·선택 TC 참조/명시 import diff를 연결한다. 샘플의 모의 상태 변경 함수를 제품 저장 경로로 사용하지 않는다.
- [ ] `python -m pytest tests/acceptance/test_asset_ui.py -q`와 실제 UI 저장→새로고침→DB 조회 일치를 확인한다.
- [ ] code/plan·package/lock/mapping·verifier method/role·승인 healing capability/scope·기본OFF를 case 상세/설정에 표시한다. 샘플 v0.5와 제품 구현을 구분한다.
- [ ] **W10 완료** — 케이스에 검증 내용을 직접 입력하고 데이터가 재접속 후에도 남는다.

#### W11 — 기기·브라우저·앱 빌드·데이터 UI

선행: W10. 연결: **T3 / UI14**. 산출: 실제 연결/권한/점유와 앱/data revision 선택.

- [ ] `tests/integration/test_app_preparation.py`에 설치 앱 hash unknown·APK hash/minSdk/ABI·서명/업데이트 실패·명시 설치·clear/reset 미선택 시 데이터 유지 사례를 작성한다.
- [ ] `api/resources.py`, `environments/app_builds.py`, `web/templates/environments.html`에 `register_app_build`/`prepare_app`, inventory/진단·APK registry·계정 ref/data 선택을 구현한다. 설치 요청은 관리 job이고 매 수행 재설치하지 않는다.
- [ ] `python -m pytest tests/integration/test_app_preparation.py tests/acceptance/test_asset_ui.py -q`와 실제 연결 화면/기본 설치 앱 선택·명시 설치를 확인한다.
- [ ] Web VM/driver/broker·script의 key/endpoint 차단 상태를 표시하고 부재/계측 불가를 package 차단 사유로 연결한다.
- [ ] **W11 완료** — Web은 테스트 브라우저, Android는 직접 연결 기기를 선택하고 필요한 정보를 웹에서 지정한다.

#### W12 — 로컬 시작·연결 상태·탭 재접속

선행: W11. 연결: **T3 / UI 공통 상태**. 산출: API/worker를 시작하고 관리 탭을 닫았다 다시 열어도 조회 가능.

- [ ] `tests/integration/test_launcher_lifecycle.py`에 중복 시작·port 사용 중·worker 불가·탭 종료/재접속·PC 절전 뒤 stale/lost 표시를 작성한다.
- [ ] `launcher.py`, `api/app.py`, `web/templates/base.html`에 지속 process 시작/상태/종료 안내·마지막 수신 시각·복구 안내를 구현한다. 프런트가 raw ADB/shell을 직접 호출하지 않는다.
- [ ] `python -m pytest tests/integration/test_launcher_lifecycle.py -q`와 Windows에서 시작→탭 닫기→재접속을 확인한다. PC 중단 동안 실행 지속/자동 재개를 보장하지 않는다.
- [ ] **W12 완료** — 일상 테스트 조작에 터미널 입력이 필요하지 않고 탭/PC 수명 차이를 안내한다.

### E. 녹화·먼저 저장

#### W13 — 실제 action별 전후 캡처·마스킹·정제 로그

선행: W12. 연결: **T4**. 산출: 여러 하위 동작을 각각 관찰/실행/기록하는 신뢰 경계.

- [ ] `tests/integration/test_action_evidence.py`에 한 step의 tap/type/swipe3개→action3개/전후PNG6개/로그3개·전 캡처 실패 시 실행 중지·후 실패 시 무조건 재동작 금지·화면 속 지시/범위 밖 URL·package·action 거부를 작성한다.
- [ ] `recording/action_executor.py`, `adapters/`, `validation/`에 `execute_action`과 `PolicyGate.authorize`를 연결하고 좌표 transform/명령 결과·오류/검증·capture timing을 저장한다. URL/redirect/package·도구 allowlist를 신뢰 코드가 강제하고 PNG/DOM/stdout/event 모두 저장·전송 전에 마스킹한다.
- [ ] `python -m pytest tests/integration/test_action_evidence.py -k capture -q`와 Web/Android 실제 동작별 증거를 확인한다. hidden reasoning/raw secret 파일이 없어야 한다.
- [ ] read-only lookup과 dispatch를 분리하고 native command 전에 dispatch_started를 durable journal에 flush한다. click navigation/ADB timeout·후 PNG 누락을 lookup_failed로 되돌리지 않는 시험을 추가한다.
- [ ] **W13 완료** — 대표 step 이미지가 아니라 실제 tap/swipe/type/back별 증거가 남는다.

#### W14 — spool·ingest·ACK·파일 정합·복구

선행: W13. 연결: **T4, T5**. 산출: 수집한 정제 기록을 단절/재전송 뒤에도 중복 없이 보관.

- [ ] `tests/integration/test_action_evidence.py`에 seq/hash 중복·다른 body409·rename 후 crash·ready 파일 누락·ACK 전 삭제 금지·제어 권한 없는 evidence_sync를 추가한다.
- [ ] `store/evidence.py`, `store/artifacts.py`, `worker/service.py`에 `append_evidence`, staging→임시파일/hash/rename→DB ready/ACK·reconcile·정제 spool 재전송을 구현한다.
- [ ] `python -m pytest tests/integration/test_action_evidence.py -q`와 업로드 단절/재연결을 확인한다. 뒤늦은 재관찰 PNG를 당시 즉시 후 캡처로 바꾸지 않는다.
- [ ] **W14 완료** — local/spooling/stored·missing/corruption을 실제 보관 상태에 맞게 표시한다.

#### W15 — 모델 역할별 호출·usage·예산 제어

선행: W14, W03. 연결: **T4**. 산출: 구조화/actor/verifier/retry를 포함한 실제 비용/한도 계측.

- [ ] `tests/unit/test_usage_budget.py`에 usage 미보고=null·일부 누락=partial·모든 role/retry 계수·예약 실패 시 다음 호출 차단·취소 뒤 늦은 응답 행동 금지를 작성한다.
- [ ] `models/client.py`, `contracts.py`, `store/models.py`에 `invoke_model`/`ModelClient.invoke`의 공통 경로·tariff version/nullable usage·예약/정산·append 보정 ledger를 구현한다.
- [ ] `python -m pytest tests/unit/test_usage_budget.py -q`와 허용된 최소 실제 호출의 계측 상태를 확인한다. USD2.00은 제안 예산이며 실제 청구 hard cap으로 표현하지 않는다.
- [ ] 모델 broker는 authoring/verification/healing/maintenance·check/episode·예산만 허용한다. 결정적/OFF replay는 키 없이 가능하고 script의 직접/숨은 LLM 호출은 차단한다. healer retry도 episode2회 합계에 포함한다.
- [ ] **W15 완료** — 계측되지 않은 usage를0으로 표시하지 않고 승인한 실행 한도를 신뢰 코드가 적용한다.

#### W16 — 녹화 마법사·완료/중단 저장·새 후보 생성

선행: W15. 연결: **T5 / UI05–06**. 산출: 디바이스→정보→자연어 검증→AI 녹화→미승인 보관.

- [ ] `tests/acceptance/test_recording_save_before_approval.py`에 승인0건의 정상/실패/중단 저장·finish 중복·manifest별 produced version1개·늦은 finish branch·재녹화 중 기존 default 유지 사례를 작성한다.
- [ ] `recording/service.py`, `api/recordings.py`, `web/templates/{recording,recording_history}.html`에 `start_recording`/`finish_recording`/`stop_recording`/`materialize_case_draft`를 구현한다. input hash 고정·실제 구조화 제안/diff·seal/flush/cleanup·불변 manifest/recovery receipt와 새 produced version을 연결한다.
- [ ] `python -m pytest tests/acceptance/test_recording_save_before_approval.py -q`와 실제 양 플랫폼 녹화·저장본 조회를 확인한다. 녹화 중 승인/저장 gate가 없어야 하고 stored/종료/완결/증거/검토 상태가 구분되어야 한다.
- [ ] raw script/plan·sealed source는 compiler 부재/실패에도 package=null/사유 있는 draft로 저장한다. W29 이후 finish의 compile→artifact ready→package/version 원자 materialize를 통합한다. 나중 컴파일은 package_rebuild/new version이고 immutable draft attach는 금지한다.
- [ ] **W16 완료** — 실패/중단/반려 여부와 무관하게 기록이 먼저 저장되고 전체 재녹화 후보가 같은 케이스에 남는다.

### F. 승인 package·모델 없는 동작 재생

#### W29 — CUAWright 승인 Web package·격리 direct replay

선행: W16의 sealed source 보존, W06–W09·W13–W15. 연결: **T12**. 산출: source code→검토 가능한 IPC script/lock/mapping→일반 actor0 Web replay.

- [ ] `tests/integration/test_replay_packages.py`에 input/부분 package0·ready1개·hash 비순환·materialization 원자성·compiler 실패/나중 package_rebuild/new version·중복 receipt를 작성한다. package_rebuild purpose/schema·동일 case source ref·관리 job owner null/QA null·worker slot만 사용·physical session/기기/브라우저/모델 제어 권한 없음도 검증한다.
- [ ] `replay/{packages,web_runner,driver,ipc,action_executor}.py`, `worker/isolated_web.py`에 `compile_replay_package`/`validate_replay_package`·`ReplayRunner.run`·trusted execute를 구현한다. VM/권한·네트워크를 분리한 driver가 browser/CDP handle을 독점하고 script는 제한 IPC만 사용한다.
- [ ] `python -m pytest tests/integration/test_replay_packages.py tests/integration/test_replay_isolation.py -q`와 Web 실제 모델 key 제거/endpoint 차단·결정적 검사/OFF replay·매 하위 action 증거를 확인한다. 숨은 LLM/helper/raw action·host credential/target 직접 요청 우회를 차단한다. W16 finish/compile 통합과 기존 저장 시험도 확인한다.
- [ ] **W29 완료** — 승인된 exact code/lock/mapping을 격리 재생하고 일반 actor0·driver/lease/capture 통제를 입증한다.

#### W30 — Android action plan·결정적/좌표 replay

선행: W29의 package/driver 계약, W16의 Android source. 연결: **T12**. 산출: Mobile-Agent 녹화 행동을 신뢰 ADB runner가 모델 없이 재생.

- [ ] `tests/integration/test_android_replay.py`에 resource-id/text/context binding·조건 고정 좌표·해상도/회전/화면 불일치·전후 capture·secret ref 입력·모델 호출0을 작성한다.
- [ ] `replay/android_runner.py`, `replay/action_executor.py`, `environments/usb_android.py`에 trace→immutable action plan/mapping·`ReplayRunner.run`을 연결한다. 원본 Mobile-Agent model loop를 반복 실행하지 않는다.
- [ ] `python -m pytest tests/integration/test_android_replay.py tests/integration/test_replay_packages.py -q`와 USB 실제 tap/type/swipe/back·모델 key/endpoint 없는 결정적/OFF replay를 확인한다. 관찰/좌표 조건 불명은 임의 재탐색/재탭하지 않는다.
- [ ] **W30 완료** — 같은 package·화면 조건으로 재생하며 기록과 현재 검증을 새로 남기고 actor0이다.

### G. 시범·사후 검토·승인

#### W17 — 미승인 시범과 실제 QA 판정

선행: W29–W30 ready package, W16 source. 연결: **T6, T7 최소 공통 수행**. 산출: 저장된 exact 후보로 새 RUN/ITEM/attempt·현재 증거/검증을 수행.

- [ ] `tests/integration/test_trial_verdicts.py`에 미승인 trial 허용·agent done/click 성공만으로 PASS 금지·필수 check/path 위반 latch·근거 부족 INCONCLUSIVE·준비 문제 BLOCKED를 작성한다.
- [ ] `api/executions.py`, `worker/runner.py`, `domain/verdicts.py`, `validation/`에 공통 `preview_execution`/`enqueue_execution`의 trial 경로와 `Validator.evaluate`를 구현한다. Web locator/state와 Android 관찰 가능한 UI hierarchy/명시 값 검증을 우선한다.
- [ ] `python -m pytest tests/integration/test_trial_verdicts.py -q`와 Web/Android 정상·값 불일치 실제 시범을 확인한다. 시범 PASS가 자동 승인을 만들면 실패다.
- [ ] exact package의 healing OFF·일반 actor0 trial과 명시 verifier만 연결한다. 모델 key 제거/endpoint 차단·결정적 검사에서 호출0, AI 검사 unknown/키/예산 부재는 생략 PASS가 아닌지를 확인한다.
- [ ] **W17 완료** — 승인 이전에도 시범이 가능하며 판정/증거는 이번 수행에서 새로 수집한다.

#### W18 — 저장본·동작별 출처/시범 검토 UI

선행: W17. 연결: **T6 / UI07**. 산출: 사람이 source/trial 동작의 전후 PNG/로그를 구분해 확인.

- [ ] `tests/acceptance/test_case_review_ui.py`에 출처/시범의 같은 A001 혼입 방지·미검토/수정 필요·PNG 누락·recording/storing 중 승인 비활성·manifest 변경409를 작성한다.
- [ ] `recording/review_manifest.py`, `api/cases.py`, `web/templates/case_review.html`에 `request_review`/`review_action`, review snapshot/membership·전후 확대·로그/오류·미검토 이동을 구현한다. review entry의 exact action→attempt→job→REC/ITEM 소속을 검사한다.
- [ ] `python -m pytest tests/acceptance/test_case_review_ui.py -q`와 실제 저장본의 source/trial 범위·검토 counts를 확인한다.
- [ ] 원본/승인 code 또는 plan·lock/runtime·source/action mapping·package ready·OFF clean trial을 함께 검토한다. raw action/LLM 우회·package0개는 승인 차단 사유다.
- [ ] **W18 완료** — 사람이 녹화가 끝나 저장된 동작을 보고 사후 검토하며 runtime 허가와 섞이지 않는다.

#### W19 — 승인·반려·철회·재녹화 전환의 원자성

선행: W18. 연결: **T6, DATA_DESIGN §5–7**. 산출: exact 근거에 대한 결정과 안전한 기본 실행본 전환.

- [ ] `tests/integration/test_post_recording_approval.py`에 다른 case/ITEM 근거 거부·동시 승인409·approval/pin/default 일부 실패 전체 rollback·GC/철회 경합·현재 철회 no fallback을 작성한다.
- [ ] `domain/approvals.py`, `recording/review_manifest.py`, `store/artifacts.py`, `web/templates/case_review.html`에 `approve_case(..., expected_current_approval_id, ...)`, 반려/철회·actor/time/reason·보호/유예·queued 차단/진행 취소 기록을 구현한다. completed source/완결/증거/PASS trial/필수 동작 검토를 모두 요구한다.
- [ ] `python -m pytest tests/integration/test_post_recording_approval.py -q`와 v2 승인→재녹화 실패/중단/반려→기존 v2 유지→후보 승인 시만 default 전환을 실제 UI/DB에서 확인한다. 이전 승인과 suite/RUN은 자동 변경하지 않는다.
- [ ] 승인 hash에 package·검증 method/binding·healing capability/scope/한도를 결합한다. 치유 PASS를 원본 package 승인용 OFF trial로 재사용하지 않는다. runtime override/proposal은 source/기본본을 바꾸지 않는다.
- [ ] **W19 완료** — 저장과 승인이 분리되고 재녹화/철회/경합에서도 잘못된 기본본이나 사라진 승인 근거가 없다.

### H. 셀프힐링·정식·묶음 수행

#### W31 — bounded healing ON/OFF·runtime override·수정 제안

선행: W19 승인 capability·W29–W30 replay·W09/W15 제어/계측. 연결: **T13**. 산출: 승인된 예외만 국소 치유하고 원본/최종 QA를 보존.

- [ ] `tests/integration/test_self_healing.py`에 기본OFF·접수snapshot/진행중불변·정상호출0·미dispatch lookup·동일 target 결정적 증명·ITEM episode1/모델합계2회(전송retry포함)/30초·동시 예약/중복0을 작성한다.
- [ ] `healing/{service,policy,proposals}.py`, `models/broker.py`, `replay/action_executor.py`에 `HealingService.propose`/`validate_healing_proposal`·role budget·typed override·원래 동작1회 dispatch·전후 증거/usage를 구현한다. command 전 dispatch_started flush, 이후 오류를 lookup 실패로 되돌리지 않는다.
- [ ] `python -m pytest tests/integration/test_self_healing.py tests/integration/test_post_recording_approval.py -q`와 실제 locator 변화/제품 expected 불일치/결과 불명·visual-only/rotation·click navigation timeout을 확인한다. 위반 FAIL·불명 action 재dispatch 금지, 치유 후 PASS badge/unassisted 분리·terminal 원본 불변이어야 한다.
- [ ] **W31 완료** — 제안은 immutable repair proposal로 남고 채택은 새 전체 REC→OFF trial→사후 승인이다. 원본 code/default/suite 자동 수정0, 생성 code 즉시 치유 실행0.

#### W20 — 단독 정식 접수·exact snapshot

선행: W31, W19·W29–W30. 연결: **T7 / UI09–10**. 산출: 승인 버전1개를 정식 RUN/ITEM/job으로 접수하고 UI에서 진행 조회.

- [ ] `tests/integration/test_execution_items.py`에 미승인 정식 거부/미승인 trial 허용·preview 후 revoke·다른 approval/hash·같은 key 중복 접수·claim 환경 변경을 작성한다.
- [ ] W17의 `preview_execution`/`enqueue_execution`을 정식 regression/reverification으로 확장하고 `api/executions.py`, `web/templates/{execution_setup,execution}.html`에4단계 확인·버전/approval/data/env/build/한도 snapshot을 연결한다.
- [ ] `python -m pytest tests/integration/test_execution_items.py -k 'single or approval or snapshot' -q`와 실제 승인 단독 수행을 확인한다. 원본 승인/PASS 화면을 새 근거로 재사용하지 않는다.
- [ ] UI09 preview에 recorded_replay/package/policy hash·필수 verifier·healing 기본OFF/승인 범위ON·1episode/2호출/30초와 차단 이유를 표시하고 접수 snapshot을 고정한다. 실행 중 토글 불가, trial은OFF다.
- [ ] **W20 완료** — preview/enqueue/claim에 같은 purpose별 승인 정책이 적용된다.

#### W21 — 선택 수행·묶음 revision·순차 정책

선행: W20. 연결: **T7 / UI03·08–10**. 산출: 복수 case/data를 exact 구성으로 순차 실행.

- [ ] `tests/integration/test_execution_items.py`에 selection/suite·data 확장 최대100·N0 거부·명시 제외·확정 뒤 NOT_RUN·새 approval 자동 추종 금지를 추가한다.
- [ ] `domain/suites.py`, `api/executions.py`, `web/templates/{suites,execution_setup,execution}.html`에 exact suite versions·순서/환경/data·명시 갱신 diff·RUN/전체 ITEM/jobs 원자 생성·continue/stop을 구현한다.
- [ ] `python -m pytest tests/integration/test_execution_items.py -k 'selection or suite or exclusion' -q`와 Web/Android mixed 묶음을 확인한다. 새 승인 뒤 기존 suite/접수 RUN이 이전본인지를 검증한다.
- [ ] **W21 완료** — 사용자가 확인한 구성만 실행되고 빠진 대상/미실행 사유가 분모에 맞게 남는다.

#### W22 — 수행/항목 취소·skip·새 재실행

선행: W21. 연결: **T7 / UI10–12**. 산출: 부분 실행 이력과 원본에 연결된 새 RUN/ITEM.

- [ ] `tests/integration/test_execution_items.py`에 미시작 skip만 허용·취소 직전 FAIL 유지·전체/항목 취소·재시작 중복0·재실행 PASS가 과거 FAIL을 변경하지 않는 사례를 추가한다.
- [ ] `api/executions.py`, `store/queue.py`, `web/templates/{execution,case_run}.html`에 `cancel_item`/`skip_item`, 새 rerun 원본 ref/사유·동일 exact 구성 확인을 구현한다.
- [ ] `python -m pytest tests/integration/test_execution_items.py -q`와 mixed 수행 중 취소/실패 항목 재실행을 확인한다. 완료 결과를 취소/다음 PASS로 덮지 않는다.
- [ ] **W22 완료** — original FAIL과 새 RUN PASS를 다른 관측으로 추적할 수 있다.

### I. 리포트·누적 분석

#### W23 — ITEM 근거·실패 분석·7결과 리포트

선행: W22. 연결: **T8 / UI11–12**. 산출: 한 수행의 판정/진행/분석을 구분한 리포트.

- [ ] `tests/unit/test_report_math.py`에 terminal7+진행=N·분모0·N10(P6/F2/B1/NOT_RUN1)→100%/75%/60%/미검증2·FAIL+취소1회 집계를 작성한다.
- [ ] `domain/reporting.py`, `api/reports.py`, `web/templates/{case_run,report}.html`에 `derive_display_result`/`summarize_execution`/`add_analysis`, 첫 실패·first/latest attempt·별도 append 분석/이의·issue ref를 구현한다.
- [ ] `python -m pytest tests/unit/test_report_math.py tests/acceptance/test_reports_ui.py -q`와 실제 단일/묶음·진행 리포트를 확인한다.
- [ ] PASS bucket 안의 healing_used와 unassisted를 별도 표시하고 원래 lookup 오류·제안/정책/dispatch/후속QA·role 비용·수정 제안을 ITEM 상세에 연결한다. 8번째 결과 bucket을 만들지 않는다.
- [ ] **W23 완료** — 완료율/검증 통과/전체 통과·미검증을 구분하고 분석 의견이 원본 판정을 바꾸지 않는다.

#### W24 — 누적 facts·기간·cohort·과거 as_of

선행: W23. 연결: **T8, DATA_DESIGN §8**. 산출: 상세 파일 만료와 무관한 조건별 장기 결과 조회.

- [ ] `tests/integration/test_analytics_facts.py`에 parent requested_at UTC [from,to)/KST 경계·REC/관리/trial 기본 제외·attempt1관측·rerun2관측·strict cohort별 최근1개·검증 완화는 다른 series를 작성한다.
- [ ] `domain/reporting.py`, `api/reports.py`, `web/templates/{analytics,comparison}.html`에 series/strict keys·실제 build/device/browser/model/prompt/data/oracle 차이·혼합 배너·created/finalized commit_seq/usage ledger 기반 as_of를 구현한다. 당시 미관찰 값은 unknown으로 유지한다.
- [ ] `python -m pytest tests/integration/test_analytics_facts.py -q`로 현재 terminal/늦은 비용 보정 이후에도 과거 진행/분모/비용이 재현되는지 확인한다.
- [ ] strict cohort에 package/runtime/lock·요청 healing ON/OFF·policy hash·verifier 조건을 추가하고 model not_used와 usage unknown을 구분한다. 치유/role facts와 commit_seq/as_of를 보존한다.
- [ ] **W24 완료** — 전체 이력/조건별 최근 완료를 구분하고 원본 실패·이전 보고서를 재해석 없이 재현한다.

#### W25 — CSV·인쇄용 HTML·snapshot export

선행: W24. 연결: **T8 / UI12–13**. 산출: 생성 시점·산식/필터·권한·만료 상태가 명시된 내보내기.

- [ ] `tests/integration/test_report_exports.py`에 CSV 수식 안전화·secret/hidden reasoning 제외·다른 project 차단·진행 보고·as_of 고정·파일 만료 표기를 작성한다.
- [ ] `domain/reporting.py`, `api/reports.py`, `web/templates/report_print.html`에 `export_report`와 export 관리 job·artifact/receipt·CSV/printable_html을 구현한다. export job QA는 null이다.
- [ ] `python -m pytest tests/integration/test_report_exports.py tests/acceptance/test_reports_ui.py -q`와 실제 CSV/인쇄용 HTML을 확인한다. localhost 링크의 외부 공유나 PDF 자동 생성을 보장하지 않는다.
- [ ] **W25 완료** — 내보낸 리포트에 원본 IDs·기준·시점이 있고 나중의 결과/비용 보정으로 바뀌지 않는다.

### J. 보관·장애·비용·MVP 검증

#### W26 — 보관 만료·승인 근거 보호·백업복원

선행: W25. 연결: **T9, DATA_DESIGN §9**. 산출: 장기 facts와 실제 파일의 수명·보호/복원 일치.

- [ ] `tests/integration/test_storage_review_integrity.py`에 detail90일/PNG30일 만료·유효 과거 approval pin·review30일 연장·revoke90일 유예·GC/approve 경쟁·payload 만료 뒤 core/hash 유지·일관 backup/restore를 작성한다.
- [ ] `store/artifacts.py`, `store/backup.py`, `api/reports.py`, `web/templates/settings.html`에 active protection/release·delete_pending/tombstone·만료 이유/보호 조회·20GB/REC·ITEM500MB 공간 차단·SQLite snapshot+그 시점 artifact manifest/임시 보호를 구현한다.
- [ ] `python -m pytest tests/integration/test_storage_review_integrity.py -q`와 실제 별도 복원 경로의 FK/integrity/hash/누락·최소 facts 검사를 확인한다. archive로 이력을 삭제하거나 secret을 평문 backup하지 않는다.
- [ ] 유효 승인 package/script/plan/lock/mapping도 보호하고 healing/proposal 최소 facts·hash/ledger는 장기 보존한다. 큰 정제 payload/PNG 만료로 원본/통계를 깨지 않는다.
- [ ] **W26 완료** — 파일이 만료돼도 결과/승인 이력을 설명할 수 있고 유효 승인 근거를 GC가 지우지 않는다.

#### W27 — 통합 장애·중복·복구·metadata 부하

선행: W26. 연결: **T9, T10 부하**. 산출: 주요 장애/경합과 누적 조회의 실제 측정 근거.

- [ ] `tests/integration/test_fault_matrix.py`에 REC/ITEM 각각 모델대기 취소·USB/browser/worker/API 중단·중복/늦은 이벤트·업로드 단절·disk full·PC 중단을 작성한다. DATA_DESIGN §11의22개 시나리오를 담당 단위와 대조한다.
- [ ] `docs/validation/faults.md`에 각 장애 최소3회·새 복구 manifest/version/review·원본 hash/terminal 유지·정리/quarantine 결과를 기록하고 실패한 구현을 해당 책임 파일에서 수정한다.
- [ ] `python -m pytest tests/integration/test_fault_matrix.py tests/integration/test_storage_review_integrity.py -q`와 합성 ITEM10,000/action100,000의 query plan/최근30일 추세 p95≤1초·이벤트200개 page p95≤500ms 제안 목표를 측정한다. 미달은 결과/조치로 남긴다.
- [ ] **W27 완료** — 실제 장애 기록과 제약이 있고 중복 행동/원본 덮어쓰기·사라진 근거를 정상 완료로 표시하지 않는다.

#### W32 — 대표 표본 비용·안정성·월3,000 TC 추정

선행: W25 리포트·W27 장애·W29–W31 실행/치유 근거. 연결: **T14**. 산출: 모델 역할/치유 빈도·정확성을 반영한 운영 비용/시간/저장량 판단.

- [ ] `tests/integration/test_cost_accounting.py`에 authoring/verification/healing/maintenance·모든 retry/check/episode·미보고null/미사용0·late ledger/as_of·role별 합계를 작성한다.
- [ ] `tools/validation/benchmark_replay.py`에 `benchmark_replay(workload: WorkloadSpec, policies: list[ExecutionPolicy]) -> BenchmarkReport`를 구현한다. 대표30–50 TC·정상/제품FAIL/locator변화/불명결과·각구성3회 제안으로 결정적/OFF, 필요한 verifier/OFF, 필요한 verifier/ON을 같은 조건에서 측정한다.
- [ ] `python -m pytest tests/integration/test_cost_accounting.py -q`와 실제 표본/price tariff·model p50/p95/호출·unassisted/치유 PASS/거짓PASS·시간/저장량을 `docs/validation/replay-costs.md`에 기록한다. 월1회3,000 TC×1data×1환경은 RUN당100 상한으로 최소30 RUN/release_label 집계하며 추가 환경/재시도/전체재녹화와 분리하고 미계측을 표시한다.
- [ ] **W32 완료** — 고정 월 예산/실제 성공률을 꾸며내지 않고 비용과 오판/복구 이력을 함께 비교한다. 가격이 낮아도 QA/격리 기준을 낮추지 않는다.

#### W28 — 양 플랫폼 전체 UI 동선·MVP 완료 판정

선행: W32 및 W01–W27·W29–W31 전부. 연결: **T10**. 산출: 사용자 동선·양 플랫폼 정상/부정/장애의 최종 근거.

- [ ] `tests/acceptance/test_mvp_ui_matrix.py`에 UI_SPEC §9의21개 동선과 기본15화면/선택TC1화면을 연결한다. TC0개에서 디바이스→정보/검증→녹화 선저장→사후 검토/승인→단독/선택/suite→분석/재실행을 수행한다.
- [ ] Web/Android 정상 각20회(첫 attempt≥18/20·허용 retry포함≥19/20 제안), 값불일치/요소부재/timeout 각5회, UI위치/문구변경 각5회를 사람 oracle과 대조한다. 거짓PASS0·누락 증거 승인0·녹화 중 승인0·중복 자원소유0·원본 덮어쓰기0·secret 유출0을 확인한다.
- [ ] `python -m pytest tests/acceptance/test_mvp_ui_matrix.py -q`, 실제 RUN/REC/ITEM·화면/로그·측정 p50/p95/usage/저장량을 `docs/validation/mvp-results.md`에 기록한다. 키보드/오류·미저장/409/403·1024px 보조 패널/1440px 기본 화면·탭/PC 복원 안내도 확인한다.
- [ ] 실행 상세 §9·DATA_DESIGN §11의22개·ON/OFF/제품FAIL/결과불명/국소 치유·원본 code 불변/새전체녹화·월3,000 TC의 조건부 계측을 최종 대조한다. actor0·격리·dispatch·falsePASS0 기준을 포함한다.
- [ ] **W28 완료** — 양 플랫폼과 모든 핵심 UI·DB/보관/분석 gate가 통과하고 실제 사용 안내/알려진 제약이 정리되어 있다. 배포/중앙 운영은 자동 착수하지 않는다.

## 8. 필수 시나리오 추적

| DATA_DESIGN §11 항목 | 담당 작업 |
|---|---|
| 1 교차 project/case/version/action/FK | W04–W06, W18–W19 |
| 2 event/finish/recovery/승인 멱등 | W08, W14, W16, W19 |
| 3 재녹화 실패/중단/반려 시 기존 승인 유지 | W16, W19 |
| 4 저장 선행·완결/근거/trial/review 승인 조건 | W13–W19 |
| 5 승인/default/pin rollback·GC/철회 경합 | W19, W26–W27 |
| 6 기존 suite/queued RUN 고정·철회/no fallback | W19–W22 |
| 7 복구 manifest/version·기존 hash 불변 | W14, W16, W27 |
| 8 만료 뒤 facts·승인/lineage·backup/restore | W06, W24, W26 |
| 9 rerun/attempt·기간/분모/결과 합계 | W17, W22–W24 |
| 10 verification/cohort 변경 차이 | W05, W24 |
| 11 같은 case의 다른 실행 근거 혼입 거부 | W06, W18–W19 |
| 12 provenance와 active protection·GC 경쟁 | W06, W19, W26 |
| 13 과거 as_of·늦은 비용·payload 만료 | W06, W15, W24–W26 |
| 14 합성 데이터 부하 | W27 |
| 15 package0..1/비순환·원자 materialization | W06, W16, W29–W30 |
| 16 순수 replay0/명시 verifier | W15, W17, W29–W30 |
| 17 미dispatch/한도·동일 target/중복 healing | W13, W31 |
| 18 FAIL latch/치유 PASS/unassisted | W17, W23–W24, W31 |
| 19 원본 불변·수정제안→새 전체 REC/OFF trial/승인 | W16, W18–W19, W31 |
| 20 역할/치유 facts·cohort/as_of | W06, W15, W24–W26, W32 |
| 21 code/driver/VM·model 경계 | W01, W07–W09, W29 |
| 22 월3,000 TC 비용·시간·저장량 | W32, W28 |

DESIGN의 P0 요구 R01–R17·R21–R35는 위 W01–W32와 연결한다. P1 요구 R18–R20은 아래 후속 범위다. UI/검증 기준 변경이 생기면 W28 및 해당 상세 단위를 함께 수정한다.

## 9. 진행 상태 갱신·작업 기록

현재 작업: **없음 — 제품 구현 요청 전**. 다음 순서: **W01**. 진행률: **W 완료 0/32**.

권장 상태는 `미착수 / 진행 중 / 검증 중 / 완료 / 차단`이다. 체크되지 않은 작업은 미완료이며, 진행/검증/차단은 아래 기록에서 설명한다. 날짜/담당/기한을 추정해 완료로 채우지 않는다. 차단이면 원인·필요 조건·영향받는 다음 작업을 남기고 선행이 충족된 독립 작업만 진행한다.

| 날짜 | 작업 ID | 상태 | 변경 파일 / 검증 근거 | 남은 제약 / 다음 행동 |
|---|---|---|---|---|
| 2026-10-31 | 문서 준비 | 완료 | v0.6 재생/치유 반영·T0–T14 및32개 W 연결. 제품 W 완료 수에는 제외 | 다음 구현 단위 W01 |

작업을 완료할 때 그 W의 하위 체크·완료 체크와 단계 요약/현재 작업/완료 수를 함께 갱신한다. 검증 기록은 `docs/validation/`의 해당 근거를 연결한다. 체크 후 결함이 발견되어 완료 기준을 잃으면 체크를 해제하고 재개 사유를 기록한다.

## 10. MVP 이후 별도 계획으로 다룰 범위

다음 항목은 T11/P1이며 **32개 제품 작업의 완료율에 포함하지 않는다.**

- [ ] 중앙 API/PostgreSQL·여러 PC worker·TLS/팀 운영·클라우드 browser/device farm.
- [ ] 일반 Skill Factory 추천/일반화·범위가 넓은 자동 코드 수정. 승인 CUAWright 코드 격리/direct replay·모델0회는 W29의 MVP다.
- [ ] 선택 API/DB oracle 확장과 read 권한/allowlist.
- [ ] 수동 화면 조작 녹화·영상/trace/logcat·pause/resume·부분 action 재녹화/병합.
- [ ] 예약/CI/알림·TC CSV import·PDF 자동 생성.

후속 기능은 별도 요구/설계와 검증 기준을 정한 뒤 새로운 작업 단위로 추가한다.
