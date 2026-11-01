# D-2 · 환경·기기·앱·data·launcher UI · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료9 / 11**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W11-01](#w11-01) | [W10-10](04a-case-management-ui.md#w10-10), [W07-01](03-worker-and-sessions.md#w07-01), [W14-03](05a-action-evidence-and-models.md#w14-03) | 연결 자원 목록·현재 화면·기기에서 녹화 | complete |
| [W11-02](#w11-02) | [W11-01](04b-environments-and-launcher.md#w11-01) | Web·Android 환경 profile 편집 | complete |
| [W11-03](#w11-03) | [W11-02](04b-environments-and-launcher.md#w11-02) | data schema·행 편집·revision·연결 UI | complete |
| [W11-04](#w11-04) | [W11-03](04b-environments-and-launcher.md#w11-03), [W07-03](03-worker-and-sessions.md#w07-03) | 설치 앱 선택과 metadata inspect | not_started |
| [W11-05](#w11-05) | [W11-03](04b-environments-and-launcher.md#w11-03), [W14-03](05a-action-evidence-and-models.md#w14-03) | APK 제한 업로드·metadata·등록 UI | complete |
| [W11-06](#w11-06) | [W11-04](04b-environments-and-launcher.md#w11-04), [W11-05](04b-environments-and-launcher.md#w11-05), [W07-03](03-worker-and-sessions.md#w07-03) | 명시 설치·reset 영향과 사후 관찰 | not_started |
| [W11-07](#w11-07) | [W11-01](04b-environments-and-launcher.md#w11-01), [W09-03](03-worker-and-sessions.md#w09-03), [W08-05](03-worker-and-sessions.md#w08-05) | 환경 진단·quarantine·복구 UI | complete |
| [W11-08](#w11-08) | [W11-07](04b-environments-and-launcher.md#w11-07), [W10-09](04a-case-management-ui.md#w10-09) | 활동 이력·worker 범위·공간 설정 조회 | complete |
| [W12-01](#w12-01) | [W11-08](04b-environments-and-launcher.md#w11-08), [W00-04](00-bootstrap.md#w00-04) | 로컬 launcher·중복시작·상태 UI | complete |
| [W12-02](#w12-02) | [W12-01](04b-environments-and-launcher.md#w12-01) | polling·탭 재접속·선택 항목 복원 | complete |
| [W12-03](#w12-03) | [W12-02](04b-environments-and-launcher.md#w12-02) | PC 절전·복귀·종료 안내와 안전 종료 | complete |

<a id="w11-01"></a>

## W11-01 — 연결 자원 목록·현재 화면·기기에서 녹화

- [x] **W11-01 완료** — 상태: `complete`. 근거: [W11-01 인계](../validation/tasks/W11-01.md).
- **직접 선행:** [W10-10](04a-case-management-ui.md#w10-10), [W07-01](03-worker-and-sessions.md#w07-01), [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C12 / C14 + 직접 선행 receipt의 interface/제약. 추적: R02, R07, R14, R25, R27, UI-14.01, UI-05.01.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/environments.html`, `src/aiqa/api/resources.py`, `src/aiqa/web/templates/components/device_preview.html`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/resources; GET /api/v1/resources/{r}/preview -> ResourcePreviewView`
- **구현·화면·예외:** UI-14 Web/Android·ready/busy/offline/unauthorized/quarantine·OS/geometry/build/마지막수신·점유 RUN 링크를 표시한다. 현재 화면은 정제된 최근관찰 artifact/시각이며 기기선택 즉시 live 제어가 아니다. busy 면 소유 세션의 권한내 preview 만, 새 capture 는 인증된 resource_probe job 이다. 이 기기로 녹화는 UI05 step1 을 선택해 연다.
- **검증 전제:** API/DB에 격리된 inventory/정제 PNG fixture를 넣어 Web/Android·busy·미관찰/만료·권한 거부를 실제 browser에서 확인한다. production adapter 부재는 unavailable로 표시한다.
- **작업 순서:** `test_w11_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "management_tab_is_test_browser": False,
  "stale_timestamp_visible": True,
  "unauthorized_preview_denied": True,
  "preview_raw_control": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-02"></a>

## W11-02 — Web·Android 환경 profile 편집

- [x] **W11-02 완료** — 상태: `complete`. 근거: [W11-02 인계](../validation/tasks/W11-02.md).
- **직접 선행:** [W11-01](04b-environments-and-launcher.md#w11-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R01, R14, R25, UI-14.02.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/environment_editor.html`, `src/aiqa/api/resources.py`, `src/aiqa/domain/environments.py`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/environments; POST /api/v1/environments/{e}/versions -> EnvironmentRevisionView`
- **구현·화면·예외:** Web URL allowlist/1280×720/DPR1/ko-KR/Asia-Seoul 와 Android package/portrait/geometry·setup/reset/cleanup·계정 ref·한도를 새 revision 으로 저장한다. 미지원 multitab/file/rotation 을 선택 가능 기능처럼 보이지 않는다.
- **검증 전제:** 허용/범위밖 URL·package·미지원 capability·env 변경 뒤 과거 RUN snapshot 을 확인한다.
- **작업 순서:** `test_w11_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "out_of_scope_blocked": True,
  "unsupported_selectable": False,
  "old_snapshot_unchanged": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-03"></a>

## W11-03 — data schema·행 편집·revision·연결 UI

- [x] **W11-03 완료** — 상태: `complete`. 근거: [W11-03 인계](../validation/tasks/W11-03.md).
- **직접 선행:** [W11-02](04b-environments-and-launcher.md#w11-02)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R22, R32, UI-14.03.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/datasets.html`, `src/aiqa/api/datasets.py`, `src/aiqa/domain/datasets.py`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `GET/POST /api/v1/projects/{p}/datasets; POST /api/v1/datasets/{d}/versions -> DatasetVersionView`
- **구현·화면·예외:** UI-14 data 이름/schema/행 ID/값/secret refs·case 연결·유효성·revision diff 를 편집한다. 새 revision 이후 이전 RUN 의 data snapshot 은 불변이다. TC CSV import 는 포함하지 않는다.
- **검증 전제:** 필수열 누락·중복 rowID·다른 project secret·새 revision·수행 snapshot 을 확인한다.
- **작업 순서:** `test_w11_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "invalid_row_status": 422,
  "duplicate_row_id_rejected": True,
  "old_run_values_unchanged": True,
  "secret_plaintext_returned": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-04"></a>

## W11-04 — 설치 앱 선택과 metadata inspect

- [ ] **W11-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-04.md`(구현 때 생성).
- **직접 선행:** [W11-03](04b-environments-and-launcher.md#w11-03), [W07-03](03-worker-and-sessions.md#w07-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R02, R05, R23, UI-14.04.
- **검증 등급:** `live_integration`. 환경: `local_python`, `usb_android`.
- **변경 파일:** `src/aiqa/environments/app_builds.py`, `src/aiqa/api/app_builds.py`, `src/aiqa/web/templates/app_builds.html`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `inspect_installed_app(resource_id: UUID, package: str) -> InstalledAppView`
- **구현·화면·예외:** host worker 가 allowlist 안 installed package/version/API/ABI 를 읽고 기본 use_installed 로 선택한다. byte hash 확인 불가는 unknown, 업로드 APK 와 같은 package/version 만으로 동일 build 로 판정하지 않는다. app_inspect 는 저장 metadata 검사만이며 live ADB 가 필요한 관찰은 resource_probe session 을 쓴다.
- **검증 전제:** APK 없이 앱선택·hash unknown·hash 필수 case·미허용 package·offline 을 확인한다.
- **작업 순서:** `test_w11_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "apk_required": False,
  "unknown_hash": "unknown",
  "hash_required_unknown_blocked": True,
  "unapproved_package_inspected": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-05"></a>

## W11-05 — APK 제한 업로드·metadata·등록 UI

- [x] **W11-05 완료** — 상태: `complete`. 근거: [W11-05 인계](../validation/tasks/W11-05.md).
- **직접 선행:** [W11-03](04b-environments-and-launcher.md#w11-03), [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R14, R23, UI-14.05.
- **검증 등급:** `tool_integration`. 환경: `local_python`, `apk_metadata_tools`.
- **변경 파일:** `src/aiqa/api/app_builds.py`, `src/aiqa/environments/app_builds.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/web/templates/app_builds.html`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/app-builds -> JobReceipt; inspect_apk(input: ApkInspectionSpec) -> AppBuildView`
- **구현·화면·예외:** 단일 APK 만·500MB/전체 20GB·generated key/hash·ZIP traversal/bomb 제한을 적용하고 SDK metadata 도구로 package/version/minSdk/ABI/서명상태를 분석한다. 도구없음/unknown 은 ready 금지·앱코드 API 실행 0 이다.
- **검증 전제:** 정상 APK·split/APKS·크기초과·ZIP 경로공격·분석도구없음·동일파일재전송을 확인한다.
- **작업 순서:** `test_w11_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "split_rejected": True,
  "traversal_rejected": True,
  "tool_missing_ready": False,
  "uploaded_code_executed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-06"></a>

## W11-06 — 명시 설치·reset 영향과 사후 관찰

- [ ] **W11-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-06.md`(구현 때 생성).
- **직접 선행:** [W11-04](04b-environments-and-launcher.md#w11-04), [W11-05](04b-environments-and-launcher.md#w11-05), [W07-03](03-worker-and-sessions.md#w07-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R11, R14, R23, UI-14.06.
- **검증 등급:** `live_integration`. 환경: `local_python`, `usb_android`.
- **변경 파일:** `src/aiqa/environments/app_builds.py`, `src/aiqa/api/app_builds.py`, `src/aiqa/web/templates/components/install_confirm.html`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/resources/{r}/app-installs -> JobReceipt; prepare_app(spec: AppPreparationSpec, session: SessionHandle) -> AppPreparationResult`
- **구현·화면·예외:** 명시 install_if_needed/force_reinstall/clear/logout 각각 영향·hash·대상기기를 확인한다. 기본 use_installed 는 설치 0, signature/downgrade 실패를 uninstall 로 우회하지 않는다. 설치 중 timeout 은 결과불명·재관찰이며 관리 QA=null 이다.
- **검증 전제:** 일치앱·업데이트거부·서명불일치·minSdk/ABI 불가·설치 timeout·reset 미선택을 검사한다.
- **작업 순서:** `test_w11_06`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_06 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "default_install_count": 0,
  "unrequested_uninstall": 0,
  "unrequested_clear": 0,
  "management_verdict": None
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-07"></a>

## W11-07 — 환경 진단·quarantine·복구 UI

- [x] **W11-07 완료** — 상태: `complete`. 근거: [W11-07 인계](../validation/tasks/W11-07.md).
- **직접 선행:** [W11-01](04b-environments-and-launcher.md#w11-01), [W09-03](03-worker-and-sessions.md#w09-03), [W08-05](03-worker-and-sessions.md#w08-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R02, R15, R25, R26, UI-14.07.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/resources.py`, `src/aiqa/web/templates/environments.html`, `src/aiqa/worker/resources.py`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/resources/{r}/probes; POST /api/v1/resources/{r}/recoveries -> JobReceipt`
- **구현·화면·예외:** VM/driver/IPC/broker·script 의 key/egress 차단·USB 권한/IME/capture·lease/cleanup 근거를 보여준다. 진단과 복구는 관리 job, ready 는 proof 뒤만. cloud/manualcontrol/pause 버튼은 없다.
- **검증 전제:** 테스트용 provider의 진단/복구 결과로 실제 job/상태/UI 경로를 확인하고, production에서는 미설정 provider가 명시 차단되는지 검사한다. VM/USB 실제 복구 proof는 W07-04에서 요구한다.
- **작업 순서:** `test_w11_07`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_07 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "vm_missing_web_ready": False,
  "recovery_requires_proof": True,
  "unsupported_buttons": 0,
  "diagnostic_qa": None
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w11-08"></a>

## W11-08 — 활동 이력·worker 범위·공간 설정 조회

- [x] **W11-08 완료** — 상태: `complete`. 근거: [W11-08 인계](../validation/tasks/W11-08.md).
- **직접 선행:** [W11-07](04b-environments-and-launcher.md#w11-07), [W10-09](04a-case-management-ui.md#w10-09)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R14, R15, R21, UI-15.03, UI-15.04.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/settings.html`, `src/aiqa/api/settings.py`, `src/aiqa/api/audit.py`. 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/audit; GET /api/v1/projects/{p}/storage; GET /api/v1/projects/{p}/workers; POST /api/v1/projects/{p}/worker-enrollments; POST /api/v1/workers/{w}/revoke -> CursorPage | StorageView | WorkerView`
- **구현·화면·예외:** UI-15 case/TC/suite/review/REC/RUN/env 변경 audit 필터·actor/time/reason 을 제공한다. worker enrollment/revoke·scope 와 공간/보호/삭제예정·한도상태를 표시한다. 실제 pin/GC/backup 조작은 W26 에서 연결하고 완료근거를 분리한다.
- **검증 전제:** 다른 project audit·worker 권한폐기·빈 공간/보호파일 초과표시·403·cursor 를 확인한다.
- **작업 순서:** `test_w11_08`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_08 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "foreign_audit_rows": 0,
  "revoked_worker_can_claim": False,
  "protected_space_visible": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w12-01"></a>

## W12-01 — 로컬 launcher·중복시작·상태 UI

- [x] **W12-01 완료** — 상태: `complete`. 근거: [W12-01 인계](../validation/tasks/W12-01.md).
- **직접 선행:** [W11-08](04b-environments-and-launcher.md#w11-08), [W00-04](00-bootstrap.md#w00-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R21, R26, UI-COMMON.04.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W27-02에서 별도로 요구한다.
- **실제 통합 담당:** [W27-02](10-retention-and-release-gates.md#w27-02). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/launcher.py`, `src/aiqa/api/lifecycle.py`, `src/aiqa/web/templates/connection.html`. 시험: `tests/acceptance/test_w12.py`.
- **입출력 계약:** `start_local_services(config: LauncherConfig) -> LocalServiceStatus; GET /api/v1/local-status`
- **구현·화면·예외:** 한 번 시작으로 API/worker 관리화면을 열고 독립 process 를 유지한다. port 충돌/이미실행/worker 없음/VM 미준비를 구별한다. 시작명령과 패키징은 이 작업산출에 포함하되 배포발행은 포함하지 않는다. W00-04의 검증된 API 시작 명령을 소비해 일상 launcher 수명 관리로 확장한다.
- **검증 전제:** 같은설정 두번 시작·다른 process port 사용·worker 실패·관리탭 종료를 확인한다.
- **작업 순서:** `test_w12_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w12.py::test_w12_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "api_instances": 1,
  "worker_instances": 1,
  "tab_close_cancels": False,
  "port_conflict_explained": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w12-02"></a>

## W12-02 — polling·탭 재접속·선택 항목 복원

- [x] **W12-02 완료** — 상태: `complete`. 근거: [W12-02 인계](../validation/tasks/W12-02.md).
- **직접 선행:** [W12-01](04b-environments-and-launcher.md#w12-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R10, R12, R26, UI-COMMON.05.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W27-02에서 별도로 요구한다.
- **실제 통합 담당:** [W27-02](10-retention-and-release-gates.md#w27-02). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/static/polling.js`, `src/aiqa/api/events.py`, `src/aiqa/web/templates/components/connection.html`. 시험: `tests/acceptance/test_w12.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/events?after_commit_seq={seq}; GET /api/v1/attempts/{a}/events?after_local_seq={seq}`
- **구현·화면·예외:** UI 2 초 poll·마지막수신·stale 를 표시한다. project commit cursor 와 attempt local_seq 를 따로 사용하고 조회는 mutation 재실행 0 이다. back/새로고침은 selected REC/ITEM/action 을 URL 로 복원한다.
- **검증 전제:** 조회연결끊김→재연결·page 숨김/복귀·탭닫기/열기·커서중복과 사건간 gap 을 확인한다.
- **작업 순서:** `test_w12_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w12.py::test_w12_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "poll_seconds": 2,
  "reconnect_mutations": 0,
  "selected_action_restored": True,
  "cursors_interchanged": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w12-03"></a>

## W12-03 — PC 절전·복귀·종료 안내와 안전 종료

- [x] **W12-03 완료** — 상태: `complete`. 근거: [W12-03 인계](../validation/tasks/W12-03.md).
- **직접 선행:** [W12-02](04b-environments-and-launcher.md#w12-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C11 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R15, R26, UI-COMMON.06.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W27-02에서 별도로 요구한다.
- **실제 통합 담당:** [W27-02](10-retention-and-release-gates.md#w27-02). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/launcher.py`, `src/aiqa/api/lifecycle.py`, `src/aiqa/worker/service.py`, `src/aiqa/web/templates/connection.html`. 시험: `tests/acceptance/test_w12.py`.
- **입출력 계약:** `stop_local_services(input: ServiceStopRequest) -> LocalServiceStatus; reconcile_after_resume() -> ReconciliationReport`
- **구현·화면·예외:** 진행작업이 있으면 종료/취소/정리영향을 보여주고 영구 flag 를 남긴다. PC 중단 동안 지속실행/즉시감지를 보장하지 않는다. 복귀 뒤 lost/불명·quarantine·새실행 안내로 연결하며 checkpoint 자동재개 0 이다.
- **검증 전제:** 테스트 서버/runner를 실제 시작·재시작하고 resume/lost 이벤트를 제어해 reconciliation을 검사한다. 사용자 PC를 강제 종료/절전하지 않으며 실제 환경 장애 수용은 W27-02에 남긴다.
- **작업 순서:** `test_w12_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w12.py::test_w12_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "automatic_resume": 0,
  "unknown_marked_success": False,
  "last_received_visible": True,
  "cleanup_or_quarantine": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
