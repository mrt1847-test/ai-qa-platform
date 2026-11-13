# 실행 준비 UI와 회귀 보완

2026-11-09 · 실행 순서는 [NEXT_ACTION](../../NEXT_ACTION.md)이 소유한다.
기존 승인/버전/자원/preview/멱등 API를 재사용한다. 운영 키·VM·독립 호스트는 로컬 구현의 선행이 아니다.

<a id="rx-79"></a>
## RX-79 · 저장한 묶음의 회귀 실행 준비

**직접 선행** RX-77, RX-78, UX-03. **계약** C00/C01/C04/C09/C14. **환경** local_python, local_browser.

**근거** RX-77은 정상 suite API를 사용했으나 일반 UI의 4단계 wizard는 실제 template 없이 items=[]를 작성한다. 묶음 목록/구성 화면에서 회귀 실행을 접수할 수 없다.

- [x] 목록·구성 화면에서 저장된 묶음 실행 준비 화면으로 진입한다. 개정·항목·승인본·환경·기기를 표시하고 0/100 초과 구성을 실행하지 않는다.
- [x] 이름·배포 라벨·실패 정책과 고정 suite_version_id로 기존 preview를 호출한다. 모든 항목을 표시하고 차단·누락·입력 변경은 접수를 막는다.
- [x] 명시 버튼으로 preview_hash와 전체 resolved_items를 기존 실행 API에 보낸다. 응답 유실 시 같은 본문/키로만 재확인하고 접수 후 실행 상세로 연결한다.
- [x] 부정/동시성 JS 검사와 프로젝트 범위/읽기 전용 GET·실제 브라우저 키보드 접수·DB 두 ITEM을 확인한다.

**산출물** suites.py, suite_execution.html/js, suite 목록/구성 링크, test_rx_79.py, suite_execution.test.cjs.
**인계** [RX-79](../validation/tasks/RX-79.md). 실제 AI/장치 수용은 RX-23/24에 유지한다.

<a id="rx-80"></a>
## RX-80 · 선택 케이스의 승인본 정식 실행 준비

**직접 선행** RX-79, RX-71. **계약** C00/C01/C04/C09/C14. **환경** local_python, local_browser.

**근거** cases.html/case_list.js의 유일한 실행 행동은 단일 시범이다. 정식 API는 selection을 지원하지만 목록에서 선택한 승인본을 실행 준비할 수 없다.

- [x] 목록의 선택 케이스 1~100개를 정식 준비 화면으로 넘긴다. 전체/검색/다른 페이지 케이스를 자동 추가하지 않는다. 미승인·보관·교차 프로젝트는 조용히 제외하지 않는다.
- [x] 각 케이스의 저장된 현재 승인본과 환경/기기/데이터를 초기값으로 표시한다. 유효 과거 승인 선택 정책을 보존하고, 미승인 항목에는 보완 경로를 제공한다.
- [x] 사용자가 각 항목의 대상·환경·데이터를 명시 선택하고 기존 preview→고정 ITEM 접수→실행 상세를 사용한다. regression만 허용하며 시범과 혼합하지 않는다. healing은 기본 OFF다.
- [x] RX-79와 응답 유실·입력 변경·미준비 차단 처리를 공유한다. 실제 브라우저에서 두 승인본 선택/사전 검사/접수와 DB 항목 고정을 확인한다.

**제외** 재실행 사유/원본 연결은 기존 rerun API가 소유한다. 새 reverification을 일반 regression 버튼으로 위장하지 않는다.
**예상 파일** executions.py, cases.html/case_list.js, 실행 준비 template/공유 JS, test_rx_80.py/JS 시험.
**완료 인계** docs/validation/tasks/RX-80.md.

<a id="rx-81"></a>
## RX-81 · 기존 회귀 실패의 원인 확인과 계약 동기화

**직접 선행** RX-78. **계약** C00/C01/C04/C09/C14. **환경** local_python.

**근거** 2026-11-09 RX-79 변경과 관계없는 W21-05에서 next_claim=None, recording_setup.test.cjs에서 종료 후 document.createElement 누락의 unhandledRejection을 각각 단독 재현했다. 기존 완료 이력을 취소하거나 실패를 삭제하지 않는다.

- [x] W21-05의 worker 자격·presence·claim 준비 계약을 실제 queue와 대조한다. fixture 문제면 올바른 credential/준비 상태로 수정하고 제품 결함이면 제품 경계를 수정한다. 검증 조건을 느슨하게 하지 않는다.
- [x] 녹화 UI 시험에서 존재하지 않는 DOM 노드를 반환하는 mock과 새 설치 앱 갱신의 비동기 작업을 확인한다. 실제 template에 맞는 DOM과 완료 대기를 제공한다.
- [x] 해당 단독 재현과 관련 Python/전체 JS 회귀를 다시 수행하고 원인·수정·부정 경계를 인계한다.

**완료 인계** docs/validation/tasks/RX-81.md.

<a id="rx-82"></a>
## RX-82 · 배포 라벨을 실행과 누적 결과에 보존

**직접 선행** RX-80, RX-72. **계약** C00/C01/C04/C09/C10/C14. **환경** local_python.

**근거** preview/UI에는 release_label이 있으나 _snapshot_limits가 이를 저장하지 않고 모든 item_finalizations 삽입은 빈 문자열을 고정한다. analytics는 jobs.limits의 release_label로 필터하므로 월간 배포별 회귀 이력을 모을 수 없다.

- [x] single/selection/suite의 명시 접수에서 라벨을 정규화하고 immutable job snapshot에 고정한다. preview 재검사에서도 라벨을 유지한다.
- [x] 정상 finish·실패/중단 후 NOT_RUN·사용자 취소·SKIPPED 모두 같은 저장 라벨로 결과를 남긴다. 중복 finish/취소는 라벨을 덮지 않는다.
- [x] API 접수→job 조회→각 종료 경계·배포 라벨별 누적 조회를 실제 DB로 확인한다. 기존 라벨 없는 과거 이력을 추정해 수정하지 않는다.
- [x] 기존 관련 실행/결과/분석 회귀를 통과하고 docs/validation/tasks/RX-82.md에 근거를 남긴다.

<a id="rx-83"></a>
## RX-83 · 일반 화면에서 배포별 누적 분석 조회

**직접 선행** RX-82. **계약** C00/C01/C09/C10/C14. **환경** local_python, local_browser.

**근거** analytics API는 release_label 등 필터를 지원하지만 HTML form은 라벨/포함/고급 조건과 submit이 없고 리포트 목록의 진입 링크도 없다. 매개변수 없는 일반 접근은 422다. 10자리 잘못된 날짜는 도메인에서 ValueError가 누출된다.

- [x] 리포트 목록에서 누적 분석으로 이동한다. 첫 진입은 현재 프로젝트 기록 번호와 최근 30일(KST)로 조회하고 실제 빈 표본을 0/비율 없음으로 표시한다. API의 명시 as_of 계약은 유지한다.
- [x] 기간·배포 라벨·목적·시범 포함·전체 관측/최근 완료를 사용자가 제출한다. 케이스/버전/환경/데이터/빌드/모델 조건과 as_of를 재조회·오류에서 보존한다.
- [x] 필터와 실제 표본/분모·미검증·비율·추세·시간·비용을 표시한다. 최신 기록 재조회는 다른 조건을 유지하고 기준 번호만 갱신한다. 읽기 전용이며 실행·AI 호출이 없다.
- [x] 잘못된 날짜/순서/기준은 422로 처리하고 HTML에 입력·수정 안내를 남긴다. API/HTML 두 경로, 실제 브라우저 필터 제출과 빈 결과를 확인한다.

<a id="rx-84"></a>
## RX-84 · 누적 분석의 기준 시점과 ITEM 생성 시점 정합성

**직접 선행** RX-83, RX-82. **계약** C00/C01/C09/C10/C14. **환경** local_python.

**근거** read_analytics는 finalized_seq를 읽지 않아 기준 시점 뒤의 FAIL/PASS를 현재 집계에 사용한다. skip/cancel/scheduler는 created_seq와 finalized_seq에 모두 종료 seq를 넣어 접수 시점 분모를 잃는다. query_observations는 진행 ITEM의 job commit_seq를 사용하지 않는다.

- [x] 결과 생성 시 job snapshot의 실제 접수 commit_seq를 created_seq로 보존한다. 정상 종료·실패 후 NOT_RUN·취소·skip 모두 적용한다. 없는 legacy 값은 기존 종료 seq로 남기고 과거 이력 UPDATE는 하지 않는다.
- [x] 누적 비율·통과/복구·latest_terminal·시간은 created≤as_of인 분모와 finalized≤as_of인 결과만 사용한다. 미래 terminal을 당시 진행 상태로 보며, 전체 관측 표본과 기준 시점 분모를 구분한다.
- [x] 정상 접수했으나 미종료인 ITEM도 job commit_seq≤as_of이면 관측 목록의 분모에 포함한다. legacy 생성 시점 불명은 임의로 확정하지 않는다.
- [x] API/실제 종료 경계·as_of0/종료 전/종료 후·latest_terminal·늦은 비용 회귀를 검증하고 인계한다.

<a id="rx-85"></a>
## RX-85 · 누적 집계와 같은 조건의 표본 목록·결과 열기

**직접 선행** RX-84. **계약** C00/C01/C09/C10/C14. **환경** local_python, local_browser.
**근거** analytics UI에는 집계 수치만 있고 관측 API는 case/env/release_label/criteria를 읽지 않는다. 사용자가 배포별 집계에 들어간 실제 케이스와 근거를 확인할 수 없다.

- [x] 관측 API가 analytics와 같은 조건·as_of·latest_terminal을 사용한다. retry는 한 ITEM, rerun은 다른 ITEM을 유지하고 기준 밖 결과는 표시하지 않는다.
- [x] 분석 화면에 이름·목적·기준 시점 결과·분모 포함·attempt 수를 가진 표본 목록을 표시하고 현재 ITEM/실행 기록으로 이동한다. 상세는 현재 저장본임을 명시하고 도착 페이지에 실제 QA 결과 요약을 작업 상태와 분리해 표시한다.
- [x] 25/50/100개 페이지와 전체 수·이전/다음, 같은 조건/기준 번호 보존을 제공한다. 검색 조건 제출과 최신 재조회는 첫 페이지로 이동한다. 빈 목록·잘못된 페이지/크기는 복구 가능하게 처리한다.
- [x] 두 배포/서로 다른 조건·최신 완료·미래 결과·프로젝트 범위·키보드 페이지 이동을 실제 API/브라우저에서 확인한다.

<a id="rx-86"></a>
## RX-86 · 정식 실행의 명시 healing 요청과 승인 정책 해석

**직접 선행** RX-54, RX-84, RX-93. **계약** C00/C01/C04/C08/C09/C14. **환경** local_python.
**근거** preview_execution/_one_item/_snapshot_limits는 모든 요청을 OFF로 고정한다. 기존 resolver의 ON 기능을 정상 접수가 사용하지 않는다.

- [x] 기본 OFF·trial OFF를 유지하고 정식 regression/reverification의 명시 true만 해석한다. 잘못된 타입·승인 capability 없는 항목은 이유와 함께 차단한다.
- [x] 기존 resolve_healing_policy로 승인 scope/package와 서버의 binding revision·키 참조 존재/예산을 확인한다. client의 key_present 주장만 믿지 않고 secret 값을 UI/응답에 내보내지 않는다.
- [x] ITEM마다 resolved policy·binding·상한·ON/OFF를 preview hash/접수 snapshot/멱등 비교에 고정한다. running 변경 금지·legacy 재전송을 보존한다. RX-93의 request_caps는 내부 interface이며 기존 HTTP 계약에 자동으로 새 입력을 추가하지 않는다. OFF의 좁은 저장 한도와 과거 접수 receipt 재전송도 검사한다.
- [x] OFF 결정적 실행의 모델0, trial 강제OFF, 미승인/철회/키없음/예산/상한 초과, 복합 선택의 일부 불가, 변경된 preview를 fixture로 검증한다.
**인계** docs/validation/tasks/RX-86.md. 운영 키 수용 RX-23/24는 별도다.

<a id="rx-87"></a>
## RX-87 · Android worker의 승인 healing snapshot 소비

세부 구현은 [Android runtime 작업 단위](ANDROID_RUNTIME_TASKS.md)의 A→B→C→D 순서다. 부분 구현으로 상위 완료하지 않는다.

**직접 선행** RX-86, RX-94, RX-95, RX-96, RX-98, RX-99, RX-54, RX-75. **계약** C00/C01/C04/C05/C08/C09/C14. **환경** local_python.
**파일** worker/android_jobs.py, replay/android_runner.py, worker/runtime.py 및 관련 healing 포트.

- [ ] 정상 claim의 고정 policy를 Android replay context로 전달하고 OFF 정상 행동은 actor0으로 반복한다.
- [ ] RX-97의 녹화 action/timeout pin을 claim별 runtime cap으로 좁혀 소비하고 handler 재사용 시 이전 작업 한도/clock을 누적하지 않는다. 모델 호출량은 RX-98 서버 gate와 일치시킨다.
- [ ] 허용된 locator/레이아웃 실패만 기존 healing episode 포트로 연결한다. 실제 검증 실패·불명 dispatch·목표/expected 변경은 치유하지 않는다.
- [ ] episode1/모델2호출/30초·전체 상한과 중단·취소·임대·정리를 유지한다. 원본 package/FAIL 불변·성공 제안 분리.
- [ ] 모의 ADB/모델의 정상 API→claim→runtime으로 OFF0/ON허용/ON차단/소진/실패/정리 재사용을 검증한다.
**인계** docs/validation/tasks/RX-87.md. 실제 AVD·운영 키 수용은 RX-23.

<a id="rx-88"></a>
## RX-88 · Web worker의 승인 healing snapshot 소비

**직접 선행** RX-86, RX-94, RX-95, RX-96, RX-98, RX-99, RX-54, RX-76. **계약** C00/C01/C04/C05/C08/C09/C14. **환경** local_python, local_browser.
**파일** worker/web_jobs.py, worker/isolated_web.py, worker/web_vm_transport.py 및 기존 healing 포트.

- [ ] 고정된 policy를 승인 CUAWright code replay context로 전달한다. 기존 신뢰 driver/guest 경계와 network policy를 유지한다.
- [ ] Web 녹화/재생의 행동·시간 한도를 claim별 고정값으로 좁히고 모델 호출은 RX-98 또는 episode/check 전용 서버 gate를 사용한다. 녹화 authoring 권한을 replay actor로 재사용하지 않는다.
- [ ] selector/레이아웃의 허용 실패만 제한 episode에 연결한다. 임의 source 실행·target/expected 변경·불명 재클릭 금지.
- [ ] OFF0/검증 전용 호출/ON한도·실패·제안 분리·종료/정리/재접속을 정상 worker entry의 테스트 브라우저로 검증한다.
**인계** docs/validation/tasks/RX-88.md. VM 격리·운영 모델 수용은 RX-24.

<a id="rx-89"></a>
## RX-89 · 정식 준비 UI의 healing ON/OFF와 차단 이유

**직접 선행** RX-79, RX-80, RX-86, RX-87, RX-88. **계약** C00/C01/C08/C09/C14. **환경** local_python, local_browser.

- [ ] 묶음/선택 정식 준비에 기본 OFF 토글을 제공한다. ON의 승인 capability·키·예산·상한과 항목별 차단을 preview 결과로 표시한다.
- [ ] 변경 시 재검사, 명시 접수, 응답 유실의 동일 요청 복구, 진행 중 토글 금지를 유지한다. trial 토글은 계속 OFF다.
- [ ] 동일 승인본/기기에서 OFF 모델0과 ON 조건을 실제 UI·fixture runtime으로 확인하고 서버/worker 미지원 성공을 만들지 않는다.
**인계** docs/validation/tasks/RX-89.md.

<a id="rx-90"></a>
## RX-90 · 실행 준비의 공통 4단계와 최종 고정값 확인

**직접 선행** RX-89. **계약** C00/C01/C09/C14, UI_SPEC UI-09. **환경** local_python, local_browser.

- [ ] 단일/선택/묶음/재실행의 1대상→2환경·데이터→3사전 점검→4최종 확인을 공통 구성으로 연결한다. 기존 API/저장본/시범·정식 구분을 보존한다.
- [ ] 고정 버전·승인·환경·기기·배포·reset/실패 정책·행동/검증 AI·예상 호출 상한·healing 상한을 최종 확인에서 읽을 수 있게 한다. 추정 호출은 실제 비용이라고 표시하지 않는다.
- [ ] 이전/취소/수정·미저장·422/403/409/응답 유실·키보드·1024/1440에서 재검사와 최종 명시 접수를 검증한다.
- [ ] 명시 제외와 사유 UI가 남으면 backend/UI별 작은 후속 카드로 편성한다. 조용한 제외나 일부 실행 성공으로 처리하지 않는다.
**인계** docs/validation/tasks/RX-90.md.

<a id="rx-91"></a>
## RX-91 · 녹화 intent 검증 오류의 원자적 거절과 W31 fixture 동기화

**직접 선행** RX-85. **계약** C00/C01/C04/C05/C14. **환경** local_python.

**근거** 기존 W31-05는 script-hash 형식의 case content_hash를 seed해 새 녹화 intent 경계에서 IntentRejected가 HTTP500으로 누출된다. 원래 경계 거절을 완화하지 않는다.

- [x] 새 녹화·재녹화에서 intent 거절을422로 전달하고 transaction을 rollback한다. 새 version/recording/job/receipt나 head 변경을 남기지 않는다.
- [x] invalid intent를 주입한 정상 HTTP 요청의 동일 키 재시도도 무부작용422인지 확인한다. 오류 원문에 secret 값을 넣지 않는다.
- [x] W31 fixture의 version hash를 canonical SHA256으로 저장하고 기존 제안/재녹화·불변 원본 검사를 통과한다.
**인계** docs/validation/tasks/RX-91.md.
