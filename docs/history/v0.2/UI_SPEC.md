# 웹 관리 UI 명세·와이어프레임 v0.2

개정일: 2026-10-30 (Asia/Seoul). **설계 문서이며 프런트엔드 제품 코드는 없다.** [DESIGN.md](DESIGN.md)의 데이터·상태·API가 기준이고, [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)의 T2A/T5–T7A/T9로 구현·검증한다. 모든 경로/버튼/API는 제안 플랫폼 계약이다.

## 1. 정보 구조와 공통 화면 계약

상단: 프로젝트 선택 / 로컬 프로그램 연결 상태 / 현재 worker / 설정. 프로젝트 내부 메뉴: **환경·연결 → 앱 빌드 → 테스트 → 실행·대기열 → 검토 → 회귀 묶음 → 결과·비교**. 첫 사용은 작업 순서에 맞는 안내를 보여주고 장식용 대시보드를 우선하지 않는다. 클라우드 목록·예약·CI·알림은 MVP 메뉴에서 실행 기능으로 노출하지 않는다.

| ID | 화면/UI route | 목적·진입 |
|---|---|---|
| UI-01 | `/projects`, `/projects/{id}/environments` | 첫 설정 또는 프로젝트 전환, 대상/변수·권한 범위 관리 |
| UI-02 | `/projects/{id}/connections` | 환경 화면/실행 전 차단 안내에서 worker·기기 진단 |
| UI-03 | `/projects/{id}/app-builds` | Android 환경 설정/실행 설정에서 앱 선택·선택 업로드·설치 |
| UI-04 | `/projects/{id}/tests` | 테스트 자산 검색·분류·상세 진입 |
| UI-05 | `/tests/{id}/edit?version={id}` | 생성/복제/새 revision 작성·구조화 계획 검토 |
| UI-06 | `/versions/{id}/trial-setup` | 편집/검토 화면의 시범 실행 설정 |
| UI-07 | `/projects/{id}/runs` | 단일·묶음 child·관리 작업을 구분한 실행/대기열 |
| UI-08 | `/runs/{id}` | 진행·증거·판정·취소·새 재실행 |
| UI-09 | `/versions/{id}/review` | trial 결과에서 정의·manifest·근거 검토, 승인/반려 |
| UI-10 | `/projects/{id}/suites`, `/suites/{id}` | 승인 버전 구성·순서·기본값·묶음 실행/결과 |
| UI-11 | `/projects/{id}/results`, `/comparisons` | 이력 필터·단계/화면/판정·시간/비용 비교·내보내기 |
| UI-12 | `/projects/{id}/settings` | 역할별 모델·키 참조·연결 확인·기본 한도·보관·worker 설정 |

모든 화면은 다음 공통 상태를 상속하고 아래 명세의 특수 상태를 추가한다.

| 상태 | 화면 반응·조작 조건 | 복원/오류 계약 |
|---|---|---|
| 빈 데이터 | 이유와 해당 권한이 있는 첫 생성/연결 CTA | 최근 결과 없음은 미실행이며 PASS로 표시하지 않음 |
| 로딩 | 목록 skeleton/진행 표시, 제출 버튼 중복 비활성 | 기존 서버 데이터를 삭제하지 않고 갱신 중 표시 |
| 입력 오류 | 필드별 422/코드·수정 안내, 입력값 보존 | secret input은 응답에 다시 채우지 않음 |
| 연결 끊김 | 마지막 갱신 시각/stale 표시, mutation 차단 | GET만 backoff 조회, POST 재시도는 사용자 명시+같은 idempotency key |
| 권한 부족 | 접근 사유 403, 읽기 가능한 영역만 표시 | URL 직접 접근도 서버 검사, 버튼 숨김만으로 통제하지 않음 |
| 실행 불가 | offline/busy/unauthorized/미지원·미승인/한도 등 구체 사유 | 환경 수정/연결 진단 링크, 자동 다른 기기/경로 선택 없음 |
| 저장 충돌 | 409와 서버 revision/비교 링크 | 로컬 편집을 조용히 덮지 않고 복사/비교 후 새 revision |

편집 미저장 표시와 페이지 이탈 확인을 제공한다. 새로고침 때 서버에 저장한 revision과 URL의 filter/tab/selected step을 복원한다. **미저장 원문은 서버 기록으로 복원된다고 보장하지 않는다.** 자동 저장가 필요하면 명시 draft 저장 API의 결과를 표시하며 secret을 localStorage에 보관하지 않는다. 실행 spec·승인 version은 읽기 전용이다. 실행 중 수정은 별도 새 draft로만 가능하고 해당 run에는 반영하지 않는다. 실행/저장 버튼은 응답 대기 중 비활성화하고 idempotency/expected revision은 서버가 확인한다.

모든 버튼의 기본 성공 동작은 API 응답의 객체 ID로 이동/해당 부분 갱신, 실패 동작은 공통 오류 표시다. 숨겨진 pause/resume/화면 직접 클릭 기능은 없다. UI-08은 증거를 조회할 뿐 테스트 브라우저/ADB를 직접 조작하지 않는다.

## 2. 화면별 명세

### UI-01 프로젝트·환경

- 목록 컬럼: 이름/ID, Web·Android 대상 수, 보관 상태, 수정일. 환경은 이름·kind·URL/package·기본 worker/resource·revision·사전 조건을 표시한다.
- 입력: 프로젝트 이름·설명/허용 대상, 환경 URL 또는 package/activity, 변수 schema/default, 비밀값 **참조**, locale/viewport/OS·앱 조건, reset/cleanup·한도. 환경 변경은 revision으로 저장한다.
- **생성/저장**: editor 이상, 유효 입력일 때 POST/PATCH projects/environments. 성공 후 대상 상세/환경 목록 갱신. **보관**: owner/editor와 사용 영향 확인 후 archive API. 기존 실행 이력은 유지하며 새 선택에서 제외한다.
- **연결 확인/첫 테스트**: 연결 화면/작성 화면으로 이동. 등록 환경 0개면 환경 등록 안내. 잘못된 URL/package·참조 불명은 필드 오류. 활성 run이 있는 환경을 편집해도 기존 snapshot은 불변이다.

### UI-02 연결·기기

- 컬럼: worker ID/name/OS/last_seen/enable/capabilities, resource ID/serial/ADB 상태·점유 run·OS API/ABI·해상도/회전·앱 버전·브라우저 가능 여부. heartbeat 시각과 stale을 표시한다.
- **새로 확인/진단**: POST resource diagnostics, 202 관리 job을 UI-07/08에서 추적. 실제 raw shell 입력창은 없다. **복구 확인**: quarantine 원인·이전 runner 종료/IME·정리 근거를 owner가 확인한 뒤 recover API. 증거 없는 강제 ready 전환은 금지한다.
- **worker 연결/비활성**: UI-12의 enrollment/worker 설정으로 이동. USB unauthorized면 기기에서 RSA 승인 안내, offline이면 케이블/전원/드라이버 확인 안내, busy면 점유 run 링크. reconnect는 즉시 새 테스트 실행을 뜻하지 않는다.

### UI-03 앱 빌드

- 두 탭: **설치된 앱**(기기·package·version·known/unknown hash·호환 상태) / **등록 APK**(build ID·파일명·package·versionCode/name·SHA-256·minSdk·ABI·검사 상태·크기·보관 상태).
- **앱 선택**: ready 기기의 허용 package를 환경에 저장. 업로드 불필요. **APK 등록**: 단일 APK 선택→제한 업로드→해시/metadata 검사 job. `uploading/inspecting/ready/rejected/unknown`을 구분하고 ready 전 설치 버튼 비활성.
- **설치**: 선택 build+ready resource+권한+OS/ABI/설치 policy 확인 후 installations API. 대상 기기·덮어쓰기/데이터 초기화 효과를 명시한다. 기본은 데이터 유지·초기화 없음이며 실행마다 재설치하지 않는다. **보관**: app-build archive, 참조 파일 삭제 없음.
- signature/downgrade 불일치·디스크 부족·미지원 split APK는 사유를 표시한다. 설치 중 취소는 관리 job 상세에서 처리하고 불명 상태는 진단 후 재시도한다.

### UI-04 테스트 목록 — 와이어프레임 1

```text
+--------------------------------------------------------------------+
| 프로젝트 [QA 데모 v]                 연결: 로컬 worker 정상 [설정] |
| 테스트 [새 테스트]    검색 [이름/ID/태그________] [검색] [초기화]     |
| 대상 [전체 v] 태그 [ ] 우선순위 [ ] 승인 [ ] 최근 판정 [ ] [정렬 v] |
+--------------------------------------------------------------------+
| 이름 / ID       | 대상 | 태그·우선 | 승인 version | 최근 결과 | 수정 |
| 장바구니 / T01  | Web  | smoke P1  | v3 승인     | FAIL [보기]| 22:00|
| 메모 / T02      | APK  | smoke P1  | 검토 대기   | 미실행     | 21:50|
| 선택 항목: [열기] [복제] [보관]            페이지 [이전] [다음]      |
+--------------------------------------------------------------------+
```

- **검색/필터/정렬/이전·다음**: GET tests(query/cursor), URL과 목록 갱신. 보관 항목은 기본 숨김, show archived로 조회. 검색 결과 0개와 전체 빈 상태를 구분한다.
- **새 테스트**: POST tests→새 draft UI-05. **열기**: 선택 test/version의 상세/편집. **복제**: 새 ID/draft 생성, tag/정의 복제 가능·승인은 미복제. **보관**: history 영향 안내 후 archive. editor 미만은 mutation 불가.
- 최근 결과는 version·환경을 함께 표시한다. 다른 version의 PASS를 현재 draft 결과처럼 보이지 않게 한다. 로딩 중 중복 생성 비활성, 보관 참조 오류는 이력 링크로 설명한다.

### UI-05 테스트 작성·편집 — 와이어프레임 2

```text
+--------------------------------------------------------------------+
| < 테스트 목록   장바구니 / T01   draft v4  [미저장] [이전 버전 비교] |
| 이름 [ ] 대상 [Web v] 태그 [smoke] 우선순위 [P1 v]                  |
+------------------------------+-------------------------------------+
| 자연어 원문                  | 구조화 계획                         |
| [목적/조건/행동/기대_______] | 목적 [ ] 사전 조건 [ ] 데이터 [ ]  |
|                              | S1 검색       기대 C1 [편집]        |
| [AI 구조화 제안]             | S2 지정 버튼  기대 C2 [편집]        |
| 제안 상태: 검토 필요         | [단계 추가] [삭제] [위로] [아래로]  |
+------------------------------+-------------------------------------+
| 필수 경로 [ ] 보조 행동 [ ] reset/cleanup [ ] 시간·호출·비용 [ ]   |
| 모호함: C2의 확인 문구/근거 필요                                   |
| [초안 저장] [시범 실행 설정] [새 초안으로 복사]                     |
+--------------------------------------------------------------------+
```

- **구조화 제안**: 저장한 source revision으로 structure job 등록. 반환한 새 revision을 diff로 표시하고 사용자가 수락/수정한다. pending 중 같은 요청 재제출 방지. 자동으로 필수 기대 결과를 삭제하지 않는다.
- **단계 추가/삭제/순서**: 현재 편집 buffer만 변경, 저장 시 새 version을 생성한다. check/path 참조 불명은 저장 validation으로 표시한다. 원문도 보존한다.
- **초안 저장**: version POST + expected_latest_revision. 저장된 ID/hash/시각 표시. **시범 실행 설정**: 저장 완료·모호함 없음·필수 checks 존재 시 UI-06. 미저장/needs_review면 비활성 사유 표시.
- **비교/새 초안**: version diff 조회, 승인/실행 중 version은 수정 버튼 대신 새 revision 생성. 원래 run과 승인 version에는 변경이 적용되지 않는다.

### UI-06 시범 실행 설정

- 화면/모달 필드: exact version/hash, engine/model binding, 환경 revision, worker/resource와 latest state, Android 설치 package/build·install/reset policy, variables/secret refs, timeout/action/retry/model/비용 한도. 입력 검증 후 준비 영향 요약을 보여준다.
- **실행**: editor·저장된 유효 정의·호환 resource·필수 key ref·예산 예약 가능 조건에서 POST runs(purpose=trial), 202 후 UI-08로 이동. label은 “시범 실행”이며 승인 전 회귀로 표시하지 않는다.
- **연결 진단/앱 관리**: UI-02/03. **돌아가기**: 편집 화면, 실행하지 않음. 상태 갱신 사이 기기 점유 race는 서버 409로 안내하고 이중 실행하지 않는다. limits 확대는 새 version 검토가 필요하다.

### UI-07 실행 목록·대기열

- 컬럼: run/job ID, purpose(시범/회귀/관리), suite/entry, test/version, 상태·별도 verdict, target/resource, queue/start/duration, 비용 상태. status/verdict/기간/환경 필터, server sort와 cursor paging.
- **취소**: queued/preparing/running만 활성, cancel_requested이면 처리 중 표시. 관리 작업도 같은 진행 계약을 쓰되 verdict는 “해당 없음”. **상세**: UI-08. **묶음 상세**: UI-10의 고정 실행 snapshot.
- 데이터가 없으면 테스트 작성/묶음 구성 안내, worker 없으면 queue가 멈춘 이유 표시. last_seen stale과 진행 중을 동시 표시하고 탭 재접속 후 서버 목록을 다시 읽는다.

### UI-08 실행 상세·증거 — 와이어프레임 3

```text
+--------------------------------------------------------------------+
| run-100 / T01 v3   진행: running   판정: 미확정   [취소]             |
| 환경·기기·앱/모델/engine hash  | 시간 42s / 한도600s | 비용 partial  |
+----------------+------------------------------+--------------------+
| 승인 단계      | 행동 전 PNG | 행동 후 PNG    | 기대 C2            |
| S1 satisfied   | [이미지]    | [이미지]       | 상품 추가 확인     |
| S2 선택 >      | [맞춤] [100%] [확대/축소]    | 실제: 추가 알림    |
| S3 not_run     | [전체 화면 보기] [이전/다음] | 판정·근거·오류     |
+----------------+------------------------------+--------------------+
| 실제 행동: click / target / label·좌표계 / 전달 결과                |
| 이벤트 seq·시각 | retry/복구 전 실패 | 모델 호출·비용 | 정리 상태     |
| [검토로 이동] [버전 보기] [새 재실행] [결과 비교] [결과 내보내기]   |
+--------------------------------------------------------------------+
```

- **취소**: 기존 API 상태에 따라 활성; finalizing부터 비활성(정리 중), server 409면 현재 상태 갱신. 취소 요청을 완료/원상복구로 오인하지 않도록 명시한다.
- **단계/이벤트/전후 선택**: GET events/artifacts, URL step/cursor 보존. 화면은 원래 해상도·회전·마스킹 영역을 표시한다. fit/100%/배율·pan·전체 화면 보기는 조회만 수행하며 Android 크기와 관계없이 읽을 수 있다. PNG 만료는 410/만료일·check 요약을 표시하고 빈 화면으로 숨기지 않는다.
- **검토로 이동**: trial terminal인 version의 UI-09. **새 재실행**: terminal에서 reruns API, 결과 불명 side effect가 있으면 먼저 검토/초기화 조건을 요구한다. 같은 parent 실패를 덮지 않는다. **비교/내보내기**: UI-11/API.
- 폴링은 2초·server cursor로 event 복원, terminal 후 중지. 관리 탭 종료는 취소가 아니다. PC 중단 복귀 시 lost/quarantine/새 실행 안내를 표시한다. 모델 대기 중도 취소 가능하고 스크린샷 미리보기 갱신은 모델 호출이 아니다.

### UI-09 검토·승인 — 와이어프레임 4

```text
+--------------------------------------------------------------------+
| T01 v4 / manifest hash...   검토 대기   [이전 승인 v3과 비교]       |
+-----------------------------+--------------------------------------+
| 정의: 원문·단계·필수 경로   | trial: run-104 completed / PASS      |
| 기대 결과·reset·한도        | 실제 경로·check·전후 증거 [열기]     |
| prompt/model/engine/patch   | 누락/복구·정리·사용량 상태           |
| dependency·환경 제약 diff  | 승인 근거 hash 일치: 예              |
+-----------------------------+--------------------------------------+
| 검토 사유 [________________________________________________]       |
| [승인] [반려] [수정할 새 초안]     이력: 검토자·시각·사유           |
+--------------------------------------------------------------------+
```

- **승인**: reviewer 권한, exact manifest의 해당 플랫폼 completed/PASS trial·필수 evidence ready·미해결 조건 없음·사유 입력 때 approvals API. 성공 시 승인 badge/actor/time, 묶음 추가 링크. 동작/검증 조건까지 승인하며 이전 결과만 승인하는 화면이 아니다.
- **반려**: review_pending이고 reason 필수일 때 rejections API. rejected 상태·검토자/시간/사유 표시. **수정할 새 초안**: 기존 반려/승인 내용 불변, 새 revision으로 UI-05.
- **차이/증거 열기**: diff와 UI-08. 부족한 증거·BLOCKED/INCONCLUSIVE/FAIL은 승인 비활성 사유다. 이미 approved인 버전을 단순 반려로 바꾸지 않고 revoke 절차를 사용한다. viewer는 읽기 전용이다.

### UI-10 회귀 묶음 — 와이어프레임 5

```text
+--------------------------------------------------------------------+
| 기본 회귀 / suite-smoke   구성 revision2   [새 묶음] [보관]         |
| 기본 데이터 [ ] 실패 정책 [계속 / non-PASS에서 중단 v]             |
+--------------------------------------------------------------------+
| 순서 | entry | 테스트·정확한 승인 version | 환경·기기 | 데이터      |
| 1    | E1    | 장바구니 v3 / hash...     | Web-local | SKU=QA-100  |
| 2    | E2    | 메모 v2 / hash...         | USB-phone | prefix=QA   |
| [항목 추가] [제거] [위로] [아래로] [버전 교체] [구성 저장]         |
| [묶음 실행 설정/시작]   ※ 미저장·미승인·권한/호환 오류면 비활성    |
+--------------------------------------------------------------------+
| 실행 suite-run-12   상태 running / 판정 미확정   [묶음 취소]        |
| 총2 / 실행1 / PASS1 FAIL0 BLOCKED0 unknown0 / 미실행1 / 취소0       |
| E1 run-100 PASS [증거] | E2 run-101 queued [상세]                   |
| [실패 항목 새 실행] [전체 새 실행] [결과 비교] [내보내기]           |
+--------------------------------------------------------------------+
```

- **추가/제거/순서/버전 교체**: 승인된 exact version picker 사용, 현재 buffer 변경. **구성 저장**: 새 suite_version POST와 expected revision, 성공 후 digest 표시. 승인 취소/보관 항목은 오류를 표시하고 저장/실행에서 재검사한다.
- **묶음 실행**: 저장한 revision/digest·해석된 environment/resource/data/install/limits snapshot을 확인하고 POST suite-runs. 전체 slot1·순차 규칙을 표시한다. UI는 실행 snapshot을 read-only로 보여주며 편집은 새 구성 revision에만 적용된다.
- **묶음 취소**: queued/running parent에서 API, 시작 안 한 child도 미실행/취소로 표시. **실패 항목 새 실행/전체 새 실행**: 새 run 또는 새 suite_run, 원래 결과는 불변. 승인 취소·불명 외부 상태는 재실행 조건 확인 전 비활성.
- 정책 중단·기기 고장으로 미실행인 항목도 남긴다. 필수 전체 PASS가 아니면 초록 전체 성공 badge를 표시하지 않는다. 비어 있는 묶음은 항목 추가 안내, 새로고침 시 server snapshot·child 결과를 복원한다.

### UI-11 결과·이력 비교

- 필터: test/version/suite/env/resource/기간/FAIL·BLOCKED·INCONCLUSIVE, 표: first/retry/recovery, engine/model/app version, 시간/비용 계측 상태/정리. 최대 비교 run 5개를 제안한다.
- **비교**: 같은 project 권한 내 selected IDs로 comparisons API, 단계 alignment와 전후 PNG·check expected/observed·판정·시간·비용 diff. 환경/version 차이는 배너로 표시한다.
- **내보내기**: exports API→job 완료 후 artifact 다운로드. 마스킹 JSON/CSV와 ID/hash·manifest 요약을 포함하며 secret 원문·hidden reasoning은 제외한다. CSV는 수식 실행 문자를 안전하게 처리한다. 증거 만료/사용량 null을 0/정상으로 치환하지 않는다.

### UI-12 설정

- 입력: role/provider/model revision/endpoint 종류·주소/key ref, image/action 호환 상태, 기본 한도·보관·총 용량, worker 등록/enable/scope. 실제 key 값은 write-only 등록 필드 또는 OS secret store 초기 설정으로 받고 read API에서 다시 보내지 않는다.
- **모델 binding 저장**: 새 binding revision; 기존 승인 manifest 변경 없음, 새 실행에 사용하려면 해당 version 재검토. **연결 확인**: 모델 호출/예상 비용을 표시한 명시 버튼, model_check job 반환. key 미설정/정책 미승인 시 비활성.
- **비밀 참조 등록/교체**: secret-refs write-only API, 응답은 참조 ID/설정 여부뿐. **기본 설정 저장**: settings PATCH, 기존 run 한도 확대 없음. **worker 등록 token 발급/비활성**: owner만 수행, 기존 작업 정리 정책 표시. 미등록이면 안전한 첫 설정 안내.

## 3. 핵심 사용자 동선 — 저장/API/성공·실패 연결

| 흐름 | 화면 이동과 발생 API | 저장되는 데이터 | 성공/실패 후 화면 |
|---|---|---|---|
| 첫 설정 | UI-01 project/env POST → UI-02 worker/resource GET/diagnostics → UI-12 model binding/check → UI-04 새 테스트 | project/env revision, worker/resource inventory, model binding/check run | ready 후 UI-05. 불충분 조건이면 해당 설정/진단으로 돌아갈 링크, 실행 비활성 |
| 테스트 구축 | UI-05 test/version POST → structure job → 새 revision diff/수정/저장 → UI-06 trial POST → UI-08 evidence → UI-09 approve/reject | raw/plan revisions, manifest, trial run/check/artifact, review decision | approved면 묶음 추가; rejected면 reason과 새 draft. trial FAIL은 증거 상세 유지 |
| 회귀 운영 | UI-10 승인 항목 추가/순서/저장 → env/resource 확인 → suite-runs POST → summary → child UI-08 → reruns/새 suite-run | suite_version, resolved suite_run, child run snapshot·판정 | 실패 위치·미실행 이유 표시, 재실행은 새 ID로 연결 |
| 테스트 변경 | UI-09/04 승인 version에서 UI-05 새 draft → diff/수정/trial/reapproval → UI-10 version 교체/새 구성 저장 | 새 test_version/review와 suite_version, 이전 run 참조 유지 | 새 suite run부터만 새 버전. 승인 실패면 이전 구성 유지 |
| 장애 대응 | UI-06/07/08 차단 사유 → UI-02 진단/복구 → UI-03 설치 상태 확인 → 새 run 요청 | 관리 job/cleanup proof·resource generation, 새 run | ready 확인 후 명시 실행. 절전/결과 불명은 자동 정상 완료·중간 재개 금지 |

## 4. 화면 조작–API–데이터–워커 추적표

모든 API는 `/api/v1` prefix를 붙인다. 상세 body/state는 DESIGN §8을 따른다. “없음”은 서버 저장/조회만 하는 조작이며 UI에서 엔진을 직접 부르는 뜻이 아니다.

| 화면·핵심 조작 | API | 데이터 | 워커 동작/검증 |
|---|---|---|---|
| UI-01 프로젝트 생성/수정/보관 | POST projects, PATCH projects/{id}, POST archive | projects/audit | 없음, 새 작업 선택 차단 |
| UI-01 환경 등록/수정/보관 | POST environments, PATCH env, POST archive | environments revision | 다음 preflight에 snapshot 적용 |
| UI-02 상태 조회/진단 | GET workers/resources/apps, POST diagnostics | inventory·관리 run | resource_probe, 읽기 허용 명령만 |
| UI-02 quarantine 복구 | POST resources/{id}/recover | cleanup proof/generation/audit | 이전 runner 종료·IME/연결 확인 |
| UI-03 설치 앱 선택 | PATCH environment | package/constraint revision | 다음 run installed metadata 대조 |
| UI-03 APK 등록/업로드/검사 | POST app-builds, PUT content | build/artifact·관리 run | app_inspect, hash/metadata/호환 검사 |
| UI-03 설치/초기화 | POST app-builds/{id}/installations | setup policy·관리 run/session | app_install, 독점 lease·명시 정책·설치 후 probe |
| UI-03 빌드 보관 | POST app-builds/{id}/archive | archived metadata | 실행 참조의 파일 삭제 안 함 |
| UI-04 검색/필터/정렬/페이지 | GET projects/{id}/tests | read projection/URL query | 없음 |
| UI-04 생성/복제/보관 | POST tests/clone/archive | 새 test/draft·tags/priority·archive | 없음, 승인은 복제 안 함 |
| UI-05 원문/단계/기대/순서 저장 | POST tests/{id}/versions | immutable revision/hash | schema/path reference validation |
| UI-05 AI 구조화 | POST versions/{id}/structure | source run·새 proposed revision | structure role, 기기 제어 없음 |
| UI-05 버전 비교/새 초안 | GET version diff, POST versions | source ref/diff/new revision | 없음 |
| UI-06 시범 실행 | POST runs(purpose=trial) | spec·run/job | lease→environment prepare→agent→validator |
| UI-07 목록/상세/취소 | GET runs, POST cancel | status/cancel audit | 새 행동 중지·정리/격리 |
| UI-08 단계/화면/로그·비용 보기 | GET run/events/artifacts/content | cursor·check·artifact·usage | spool/진행 업로드, 미리보기 모델 호출 없음 |
| UI-08 단일 재실행 | POST runs/{id}/reruns | 새 run, rerun_of_run_id | side effect/reset 안전성 재확인 |
| UI-09 승인/반려/revoke | POST approvals/rejections/revoke | append-only review record | revoke된 진행 작업 취소, 승인 근거 PASS/hash 검사 |
| UI-10 묶음 생성/구성/버전 교체/보관 | POST suites/versions/archive, PATCH suite metadata | immutable suite_version | 없음, 승인·schema 참조 검사 |
| UI-10 묶음 실행/상태 | POST suite-runs, GET suite-run | resolved snapshot/child runs | 순차 claim·정리·failure policy |
| UI-10 묶음 취소/실패 항목 새 실행 | POST suite cancel, POST reruns 또는 새 suite-runs | child not_run·새 IDs/provenance | active cancel, 나머지 시작 차단, 과거 결과 보존 |
| UI-11 필터/비교/내보내기 | GET runs/comparisons, POST exports | 비교 projection·export artifact | export job, 마스킹·CSV 안전화 |
| UI-12 모델/설정 저장·키 참조 | POST/PATCH model-bindings/settings/secret-refs | binding revisions/설정·secret ref | key는 OS store, 원문 반환 없음 |
| UI-12 연결 시험·worker 등록/비활성 | POST checks/enrollment, PATCH workers/{id} | 관리 run/token hash/scope | model_check 또는 claim 차단/watchdog 정리 |

## 5. 문서 단계 완료 조건

12개 영역을 실제 데이터/API/worker 책임과 연결했고 필수 5개 화면을 텍스트 와이어프레임으로 제시했다. 향후 제품 합격은 **UI를 통해** 두 플랫폼에서 생성·검색·편집·복제·시범·반려/재승인·버전 비교·묶음·결과 내보내기까지 수행하는 T9 증거로 판정한다. 이 문서의 버튼/경로는 구현된 기능을 뜻하지 않는다.
