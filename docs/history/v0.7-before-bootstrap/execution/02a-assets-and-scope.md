# B-1 · 권한·케이스·TC·환경·data · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 10**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W04-01](#w04-01) | [W03-03](01-foundation-probes.md#w03-03) | 비동기화 DB·migration·단일 writer 기반 |
| [W04-02](#w04-02) | [W04-01](02a-assets-and-scope.md#w04-01) | 프로젝트 저장과 scope·actor·commit clock |
| [W04-03](#w04-03) | [W04-02](02a-assets-and-scope.md#w04-02) | 로컬 browser 인증·CSRF·worker scope |
| [W04-04](#w04-04) | [W04-03](02a-assets-and-scope.md#w04-03) | OS secret ref 저장·교체·조회 경계 |
| [W05-01](#w05-01) | [W04-04](02a-assets-and-scope.md#w04-04) | canonical hash 와 stable step/check projection |
| [W05-02](#w05-02) | [W05-01](02a-assets-and-scope.md#w05-01) | 새 케이스·불변 revision·CAS 분기 |
| [W05-03](#w05-03) | [W05-02](02a-assets-and-scope.md#w05-02) | readiness 와 편집 후 package 무효화 계약 |
| [W05-04](#w05-04) | [W05-03](02a-assets-and-scope.md#w05-03) | 선택 TC 버전·참조·명시 import 제안 |
| [W05-05](#w05-05) | [W05-04](02a-assets-and-scope.md#w05-04) | 환경·data·모델 binding의 불변 revision |
| [W05-06](#w05-06) | [W05-05](02a-assets-and-scope.md#w05-05) | 분류 metadata·복제·보관과 목록 query |

<a id="w04-01"></a>

## W04-01 — 비동기화 DB·migration·단일 writer 기반

- [ ] **W04-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W04-01.md`(완료 시 생성).
- **직접 선행:** [W03-03](01-foundation-probes.md#w03-03)
- **읽기:** CONTRACTS C00 / C01 / C02 + 직접 선행 receipt의 interface/제약. 추적: R01, R10, R12.
- **변경 파일:** `src/aiqa/store/database.py`, `migrations/env.py`, `src/aiqa/api/app.py`. 담당 시험: `tests/integration/test_w04.py`.
- **입출력 계약:** `open_store(config: StorageConfig) -> Store; migrate_store(store: Store) -> SchemaRevision`
- **구현·화면·예외:** %LOCALAPPDATA%/AIQA/에 DB/artifacts/spool 을 분리하고 API 만 SQLite writer 가 된다. 연결마다 foreign_keys=ON·WAL·짧은 transaction 을 적용한다. 설치 설정과 비동기화 경로 검사를 포함한다.
- **검증 전제:** 임시 LOCALAPPDATA 로 migration→project row 저장→API 재시작→조회하고 worker 의 DB 직접 접근 경로가 없는지 검사한다.
- **작업 순서:** `test_w04_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w04.py::test_w04_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "foreign_keys": 1,
  "restart_preserves_row": True,
  "worker_opens_db": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w04-02"></a>

## W04-02 — 프로젝트 저장과 scope·actor·commit clock

- [ ] **W04-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W04-02.md`(완료 시 생성).
- **직접 선행:** [W04-01](02a-assets-and-scope.md#w04-01)
- **읽기:** CONTRACTS C00 / C01 / C02 + 직접 선행 receipt의 interface/제약. 추적: R01, R12, R14.
- **변경 파일:** `src/aiqa/store/models.py`, `src/aiqa/domain/projects.py`, `src/aiqa/api/catalog.py`, `migrations/versions/0001_projects.py`. 담당 시험: `tests/integration/test_w04.py`.
- **입출력 계약:** `create_project(actor: Actor, input: ProjectCreate) -> ProjectView; next_commit_seq(tx: Transaction, project_id: UUID) -> int`
- **구현·화면·예외:** 프로젝트 이름/key/description/target 과 actor/audit·project_commit_clock 을 저장한다. key 중복 409, composite project FK, 변경과 seq 배정은 같은 transaction 이다.
- **검증 전제:** project A/B 생성 후 key 중복과 A 경로/B child ID 를 요청하고 rollback 때 seq/row 를 확인한다.
- **작업 순서:** `test_w04_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w04.py::test_w04_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "duplicate_key_status": 409,
  "cross_project_denied": True,
  "rollback_partial_rows": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w04-03"></a>

## W04-03 — 로컬 browser 인증·CSRF·worker scope

- [ ] **W04-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W04-03.md`(완료 시 생성).
- **직접 선행:** [W04-02](02a-assets-and-scope.md#w04-02)
- **읽기:** CONTRACTS C00 / C01 / C02 + 직접 선행 receipt의 interface/제약. 추적: R14, R21.
- **변경 파일:** `src/aiqa/api/auth.py`, `src/aiqa/api/app.py`, `src/aiqa/store/models.py`, `migrations/versions/0001b_auth_workers.py`. 담당 시험: `tests/integration/test_w04.py`.
- **입출력 계약:** `bootstrap_browser_session(nonce: str, origin: str) -> BrowserSession; authorize_browser(request: Request, project_id: UUID, operation: str) -> Actor; authorize_worker(token: str, job: JobRef) -> WorkerScope`
- **구현·화면·예외:** 127.0.0.1 bind·개인 browser session·Origin/CSRF·project scope 와 별도 worker enrollment/token 을 구현한다. launcher 일회용 nonce 는 URL fragment 로만 전달하고 동일 Origin bootstrap 에서 소비하며 60 초 만료·1 회 사용이다. 원문 query/log/localStorage 기록·임의 CORS·worker token 의 승인 API 사용을 금지한다. 은닉 404/권한 403 은 C01 이다. worker/enrollment/token reference 기본 schema도 이 단계에서 저장한다. 자원 alias/physical key는 W06-10, lease/job/attempt는 W06-02의 후속 schema다.
- **검증 전제:** 누락 CSRF·외부 Origin·잘못된 project·worker token 의 approval mutation 을 실제 API 에 요청한다.
- **작업 순서:** `test_w04_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w04.py::test_w04_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "csrf_rejected": True,
  "foreign_origin_rejected": True,
  "worker_approval_denied": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w04-04"></a>

## W04-04 — OS secret ref 저장·교체·조회 경계

- [ ] **W04-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W04-04.md`(완료 시 생성).
- **직접 선행:** [W04-03](02a-assets-and-scope.md#w04-03)
- **읽기:** CONTRACTS C00 / C01 / C02 + 직접 선행 receipt의 interface/제약. 추적: R13, R14.
- **변경 파일:** `src/aiqa/security/secrets.py`, `src/aiqa/api/secret_refs.py`, `src/aiqa/store/models.py`, `migrations/versions/0001c_secret_refs.py`. 담당 시험: `tests/integration/test_w04.py`.
- **입출력 계약:** `put_secret(actor: Actor, input: SecretInput) -> SecretRefView; resolve_secret(ref: SecretRef, scope: RuntimeScope) -> SecretValue`
- **구현·화면·예외:** 원문은 OS secret store 에만 한 번 쓰고 metadata/revision/availability 만 반환한다. ref rotation 은 audit·run snapshot 에 revision 을 남기되 원문 또는 원문 hash 를 definition/로그/브라우저 저장에 두지 않는다.
- **검증 전제:** secret 생성→조회→교체와 타 project resolve·예외 로그를 검사한다.
- **작업 순서:** `test_w04_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w04.py::test_w04_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "read_returns_plaintext": False,
  "db_has_plaintext": False,
  "cross_project_resolve": False,
  "revision_changes": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w05-01"></a>

## W05-01 — canonical hash 와 stable step/check projection

- [ ] **W05-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W05-01.md`(완료 시 생성).
- **직접 선행:** [W04-04](02a-assets-and-scope.md#w04-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 + 직접 선행 receipt의 interface/제약. 추적: R03, R08, R28.
- **변경 파일:** `src/aiqa/domain/hashing.py`, `src/aiqa/domain/versions.py`, `src/aiqa/contracts/cases.py`. 담당 시험: `tests/integration/test_w05.py`.
- **입출력 계약:** `canonical_hash(body: JsonObject, schema_version: str) -> str; verification_digest(definition: CaseDefinition) -> str`
- **구현·화면·예외:** canon-json-v1(UTF8/key 정렬/compact/유한수/decimal 문자열)을 고정한다. step/check ID·semantic hash projection 은 원본 JSON 과 같은 transaction 이다. 이름/태그/TC pointer·secret 원문·파일 가용성은 content hash 밖이다.
- **검증 전제:** key 순서만 다른 JSON·NaN·동일 의도의 좌표 변경·expected 변경을 비교한다.
- **작업 순서:** `test_w05_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w05.py::test_w05_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "key_order_same_hash": True,
  "nan_rejected": True,
  "expected_change_new_digest": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w05-02"></a>

## W05-02 — 새 케이스·불변 revision·CAS 분기

- [ ] **W05-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W05-02.md`(완료 시 생성).
- **직접 선행:** [W05-01](02a-assets-and-scope.md#w05-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 + 직접 선행 receipt의 interface/제약. 추적: R03, R08, R28.
- **변경 파일:** `src/aiqa/domain/versions.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/models.py`, `migrations/versions/0002_cases.py`. 담당 시험: `tests/integration/test_w05.py`.
- **입출력 계약:** `save_case_revision(actor: Actor, case_id: UUID, input: CaseRevisionInput, expected_head: UUID | None) -> CaseVersionView`
- **구현·화면·예외:** draft 저장은 모호한 정의도 허용하되 readiness 이유를 반환한다. content UPDATE/DELETE 금지, revision 배정/parent/base 소속/단계 projection/latest pointer CAS 를 원자 처리한다. 명시 branch 는 head 를 덮지 않는다. case metadata가 참조하는 folder/tag 기본 테이블도 0002_cases에 먼저 만든다. W05-06은 편집/query/index 서비스다.
- **검증 전제:** TC=null 초안 저장·동시 expected_head 저장·다른 case parent·직접 content UPDATE 를 시도한다.
- **작업 순서:** `test_w05_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w05.py::test_w05_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "null_tc_saved": True,
  "stale_head_status": 409,
  "foreign_parent_denied": True,
  "content_update_denied": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w05-03"></a>

## W05-03 — readiness 와 편집 후 package 무효화 계약

- [ ] **W05-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W05-03.md`(완료 시 생성).
- **직접 선행:** [W05-02](02a-assets-and-scope.md#w05-02)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 + 직접 선행 receipt의 interface/제약. 추적: R03, R08, R30, R34.
- **변경 파일:** `src/aiqa/domain/readiness.py`, `src/aiqa/contracts/cases.py`. 담당 시험: `tests/integration/test_w05.py`.
- **입출력 계약:** `compute_case_readiness(version: CaseVersion, facts: ReadinessFacts) -> CaseReadiness`
- **구현·화면·예외:** saved/recordable/replayable/reviewable/formal_runnable 을 구별하고 C03 이유 코드를 돌려준다. 검증/절차/정책 의미 편집은 package=null 새 draft 다. raw/승인 code inplace 수정 금지, 전체 REC 로 새 package 를 얻는다. package_rebuild 는 동일 source 재컴파일이다.
- **검증 전제:** 모호한 draft·package 없음·미승인 ready 후보·유효 승인본·내용 편집본을 각각 조회한다.
- **작업 순서:** `test_w05_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w05.py::test_w05_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "draft_save_allowed": True,
  "no_package_trial": False,
  "unapproved_trial": True,
  "unapproved_formal": False,
  "edited_package": None
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w05-04"></a>

## W05-04 — 선택 TC 버전·참조·명시 import 제안

- [ ] **W05-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W05-04.md`(완료 시 생성).
- **직접 선행:** [W05-03](02a-assets-and-scope.md#w05-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C12 + 직접 선행 receipt의 interface/제약. 추적: R21, R24, R28.
- **변경 파일:** `src/aiqa/domain/tcs.py`, `src/aiqa/domain/versions.py`, `src/aiqa/api/tcs.py`, `src/aiqa/store/models.py`, `migrations/versions/0002b_optional_tcs.py`. 담당 시험: `tests/integration/test_w05.py`.
- **입출력 계약:** `save_tc_revision(input: TcRevisionInput) -> TcVersionView; set_tc_reference(case_id: UUID, tc_version_id: UUID | None) -> CaseMetadataView`
- **구현·화면·예외:** TC CRUD/revision/clone/archive와 참조 metadata/audit를 구현한다. 연결/해제/TC 수정/보관은 case hash/approval/default 변경0이다. 명시 import 제안·수락의 영속 transaction은 jobs schema 뒤 W06-09가 담당한다.
- **검증 전제:** 승인 케이스의 TC 연결/편집/보관/해제와 다른 project 참조 거부를 연속 실행한다.
- **작업 순서:** `test_w05_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w05.py::test_w05_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "reference_only_new_case_versions": 0,
  "approval_unchanged": True,
  "foreign_tc_reference_denied": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w05-05"></a>

## W05-05 — 환경·data·모델 binding의 불변 revision

- [ ] **W05-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W05-05.md`(완료 시 생성).
- **직접 선행:** [W05-04](02a-assets-and-scope.md#w05-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C06 + 직접 선행 receipt의 interface/제약. 추적: R01, R22, R32.
- **변경 파일:** `src/aiqa/domain/datasets.py`, `src/aiqa/domain/environments.py`, `src/aiqa/api/resources.py`, `src/aiqa/store/models.py`, `migrations/versions/0002c_environment_data_bindings.py`, `src/aiqa/domain/model_bindings.py`. 담당 시험: `tests/integration/test_w05.py`.
- **입출력 계약:** `save_dataset_revision(input: DatasetRevisionInput) -> DatasetVersionView; save_environment_revision(input: EnvironmentRevisionInput) -> EnvironmentRevisionView; save_model_binding_revision(input: ModelBindingInput) -> ModelBindingView`
- **구현·화면·예외:** data row stable ID·schema/hash·secret ref revision 과 Web/Android 환경 revision 을 불변 저장한다. row 값은 승인 schema 안에서만 허용하고 env allowlist/viewport/locale/reset/limits 를 버전 고정한다. model_bindings/binding_revisions도 같은 자산 schema 단계에서 생성하고 role/provider/endpoint/model/key ref/prompt hash/tariff·호환 검사 상태를 저장한다. 실제 호출은 W15다.
- **검증 전제:** data schema 오류·다른 project secret·새 data/env revision 저장 뒤 과거 ref 를 조회한다.
- **작업 순서:** `test_w05_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w05.py::test_w05_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "invalid_rows_status": 422,
  "foreign_secret_denied": True,
  "old_revisions_unchanged": True,
  "model_binding_revisions_immutable": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w05-06"></a>

## W05-06 — 분류 metadata·복제·보관과 목록 query

- [ ] **W05-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W05-06.md`(완료 시 생성).
- **직접 선행:** [W05-05](02a-assets-and-scope.md#w05-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 + 직접 선행 receipt의 interface/제약. 추적: R21, R24, R28.
- **변경 파일:** `src/aiqa/domain/catalog.py`, `src/aiqa/api/cases.py`, `src/aiqa/api/catalog.py`, `src/aiqa/store/models.py`, `migrations/versions/0002d_catalog_indexes.py`. 담당 시험: `tests/integration/test_w05.py`.
- **입출력 계약:** `list_cases(query: CaseListQuery) -> CursorPage[CaseListRow]; clone_case(input: CloneCaseInput) -> CaseView; archive_case(case_id: UUID, expected_revision: int) -> CaseView`
- **구현·화면·예외:** 폴더·태그·우선순위·담당자 metadata 와 목록 검색/필터/sort allowlist/25 기본 100 최대 cursor 를 지원한다. 복제는 새 AUT/draft 와 provenance 만, approval0. 보관은 정의/과거 RUN 삭제 0 이며 진행 작업 충돌을 표시한다.
- **검증 전제:** 검색/분류/page·보관 목록·승인본 복제·활성 REC 보관을 요청한다.
- **작업 순서:** `test_w05_06`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w05.py::test_w05_06 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "clone_approvals": 0,
  "archived_history_readable": True,
  "active_recording_archive_status": 409
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
