# D-2 · 환경·기기·앱·data·launcher UI · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 11**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W11-01](#w11-01) | [W10-10](04a-case-management-ui.md#w10-10) | 연결 자원 목록·현재 화면·기기에서 녹화 |
| [W11-02](#w11-02) | [W11-01](04b-environments-and-launcher.md#w11-01) | Web·Android 환경 profile 편집 |
| [W11-03](#w11-03) | [W11-02](04b-environments-and-launcher.md#w11-02) | data schema·행 편집·revision·연결 UI |
| [W11-04](#w11-04) | [W11-03](04b-environments-and-launcher.md#w11-03) | 설치 앱 선택과 metadata inspect |
| [W11-05](#w11-05) | [W11-04](04b-environments-and-launcher.md#w11-04) | APK 제한 업로드·metadata·등록 UI |
| [W11-06](#w11-06) | [W11-05](04b-environments-and-launcher.md#w11-05) | 명시 설치·reset 영향과 사후 관찰 |
| [W11-07](#w11-07) | [W11-06](04b-environments-and-launcher.md#w11-06) | 환경 진단·quarantine·복구 UI |
| [W11-08](#w11-08) | [W11-07](04b-environments-and-launcher.md#w11-07) | 활동 이력·worker 범위·공간 설정 조회 |
| [W12-01](#w12-01) | [W11-08](04b-environments-and-launcher.md#w11-08) | 로컬 launcher·중복시작·상태 UI |
| [W12-02](#w12-02) | [W12-01](04b-environments-and-launcher.md#w12-01) | polling·탭 재접속·선택 항목 복원 |
| [W12-03](#w12-03) | [W12-02](04b-environments-and-launcher.md#w12-02) | PC 절전·복귀·종료 안내와 안전 종료 |

<a id="w11-01"></a>

## W11-01 — 연결 자원 목록·현재 화면·기기에서 녹화

- [ ] **W11-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-01.md`(완료 시 생성).
- **직접 선행:** [W10-10](04a-case-management-ui.md#w10-10)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C12 + 직접 선행 receipt의 interface/제약. 추적: R02, R07, R14, R25, R27, UI-14.01, UI-05.01.
- **변경 파일:** `src/aiqa/web/templates/environments.html`, `src/aiqa/api/resources.py`, `src/aiqa/web/templates/components/device_preview.html`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/resources; GET /api/v1/resources/{r}/preview -> ResourcePreviewView`
- **구현·화면·예외:** UI-14 Web/Android·ready/busy/offline/unauthorized/quarantine·OS/geometry/build/마지막수신·점유 RUN 링크를 표시한다. 현재 화면은 정제된 최근관찰 artifact/시각이며 기기선택 즉시 live 제어가 아니다. busy 면 소유 세션의 권한내 preview 만, 새 capture 는 인증된 resource_probe job 이다. 이 기기로 녹화는 UI05 step1 을 선택해 연다.
- **검증 전제:** WebVM 부재·Android 연결/끊김·busy·preview 없음/만료·선택바뀜·권한없는 점유화면을 검사한다.
- **작업 순서:** `test_w11_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "management_tab_is_test_browser": False,
  "stale_timestamp_visible": True,
  "unauthorized_preview_denied": True,
  "preview_raw_control": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-02"></a>

## W11-02 — Web·Android 환경 profile 편집

- [ ] **W11-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-02.md`(완료 시 생성).
- **직접 선행:** [W11-01](04b-environments-and-launcher.md#w11-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R01, R14, R25, UI-14.02.
- **변경 파일:** `src/aiqa/web/templates/environment_editor.html`, `src/aiqa/api/resources.py`, `src/aiqa/domain/environments.py`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/environments; POST /api/v1/environments/{e}/versions -> EnvironmentRevisionView`
- **구현·화면·예외:** Web URL allowlist/1280×720/DPR1/ko-KR/Asia-Seoul 와 Android package/portrait/geometry·setup/reset/cleanup·계정 ref·한도를 새 revision 으로 저장한다. 미지원 multitab/file/rotation 을 선택 가능 기능처럼 보이지 않는다.
- **검증 전제:** 허용/범위밖 URL·package·미지원 capability·env 변경 뒤 과거 RUN snapshot 을 확인한다.
- **작업 순서:** `test_w11_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "out_of_scope_blocked": True,
  "unsupported_selectable": False,
  "old_snapshot_unchanged": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-03"></a>

## W11-03 — data schema·행 편집·revision·연결 UI

- [ ] **W11-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-03.md`(완료 시 생성).
- **직접 선행:** [W11-02](04b-environments-and-launcher.md#w11-02)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R22, R32, UI-14.03.
- **변경 파일:** `src/aiqa/web/templates/datasets.html`, `src/aiqa/api/datasets.py`, `src/aiqa/domain/datasets.py`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `GET/POST /api/v1/projects/{p}/datasets; POST /api/v1/datasets/{d}/versions -> DatasetVersionView`
- **구현·화면·예외:** UI-14 data 이름/schema/행 ID/값/secret refs·case 연결·유효성·revision diff 를 편집한다. 새 revision 이후 이전 RUN 의 data snapshot 은 불변이다. TC CSV import 는 포함하지 않는다.
- **검증 전제:** 필수열 누락·중복 rowID·다른 project secret·새 revision·수행 snapshot 을 확인한다.
- **작업 순서:** `test_w11_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "invalid_row_status": 422,
  "duplicate_row_id_rejected": True,
  "old_run_values_unchanged": True,
  "secret_plaintext_returned": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-04"></a>

## W11-04 — 설치 앱 선택과 metadata inspect

- [ ] **W11-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-04.md`(완료 시 생성).
- **직접 선행:** [W11-03](04b-environments-and-launcher.md#w11-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R02, R05, R23, UI-14.04.
- **변경 파일:** `src/aiqa/environments/app_builds.py`, `src/aiqa/api/app_builds.py`, `src/aiqa/web/templates/app_builds.html`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `inspect_installed_app(resource_id: UUID, package: str) -> InstalledAppView`
- **구현·화면·예외:** host worker 가 allowlist 안 installed package/version/API/ABI 를 읽고 기본 use_installed 로 선택한다. byte hash 확인 불가는 unknown, 업로드 APK 와 같은 package/version 만으로 동일 build 로 판정하지 않는다. app_inspect 는 저장 metadata 검사만이며 live ADB 가 필요한 관찰은 resource_probe session 을 쓴다.
- **검증 전제:** APK 없이 앱선택·hash unknown·hash 필수 case·미허용 package·offline 을 확인한다.
- **작업 순서:** `test_w11_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "apk_required": False,
  "unknown_hash": "unknown",
  "hash_required_unknown_blocked": True,
  "unapproved_package_inspected": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-05"></a>

## W11-05 — APK 제한 업로드·metadata·등록 UI

- [ ] **W11-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-05.md`(완료 시 생성).
- **직접 선행:** [W11-04](04b-environments-and-launcher.md#w11-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R14, R23, UI-14.05.
- **변경 파일:** `src/aiqa/api/app_builds.py`, `src/aiqa/environments/app_builds.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/web/templates/app_builds.html`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/app-builds -> JobReceipt; inspect_apk(input: ApkInspectionSpec) -> AppBuildView`
- **구현·화면·예외:** 단일 APK 만·500MB/전체 20GB·generated key/hash·ZIP traversal/bomb 제한을 적용하고 SDK metadata 도구로 package/version/minSdk/ABI/서명상태를 분석한다. 도구없음/unknown 은 ready 금지·앱코드 API 실행 0 이다.
- **검증 전제:** 정상 APK·split/APKS·크기초과·ZIP 경로공격·분석도구없음·동일파일재전송을 확인한다.
- **작업 순서:** `test_w11_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "split_rejected": True,
  "traversal_rejected": True,
  "tool_missing_ready": False,
  "uploaded_code_executed": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-06"></a>

## W11-06 — 명시 설치·reset 영향과 사후 관찰

- [ ] **W11-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-06.md`(완료 시 생성).
- **직접 선행:** [W11-05](04b-environments-and-launcher.md#w11-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R11, R14, R23, UI-14.06.
- **변경 파일:** `src/aiqa/environments/app_builds.py`, `src/aiqa/api/app_builds.py`, `src/aiqa/web/templates/components/install_confirm.html`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/resources/{r}/app-installs -> JobReceipt; prepare_app(spec: AppPreparationSpec, session: SessionHandle) -> AppPreparationResult`
- **구현·화면·예외:** 명시 install_if_needed/force_reinstall/clear/logout 각각 영향·hash·대상기기를 확인한다. 기본 use_installed 는 설치 0, signature/downgrade 실패를 uninstall 로 우회하지 않는다. 설치 중 timeout 은 결과불명·재관찰이며 관리 QA=null 이다.
- **검증 전제:** 일치앱·업데이트거부·서명불일치·minSdk/ABI 불가·설치 timeout·reset 미선택을 검사한다.
- **작업 순서:** `test_w11_06`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_06 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "default_install_count": 0,
  "unrequested_uninstall": 0,
  "unrequested_clear": 0,
  "management_verdict": None
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-07"></a>

## W11-07 — 환경 진단·quarantine·복구 UI

- [ ] **W11-07 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-07.md`(완료 시 생성).
- **직접 선행:** [W11-06](04b-environments-and-launcher.md#w11-06)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R02, R15, R25, R26, UI-14.07.
- **변경 파일:** `src/aiqa/api/resources.py`, `src/aiqa/web/templates/environments.html`, `src/aiqa/worker/resources.py`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `POST /api/v1/resources/{r}/probes; POST /api/v1/resources/{r}/recoveries -> JobReceipt`
- **구현·화면·예외:** VM/driver/IPC/broker·script 의 key/egress 차단·USB 권한/IME/capture·lease/cleanup 근거를 보여준다. 진단과 복구는 관리 job, ready 는 proof 뒤만. cloud/manualcontrol/pause 버튼은 없다.
- **검증 전제:** VM 부재·driver 우회가능·USB unauthorized·IME 실패·stale recovery 와 실제 조치링크를 확인한다.
- **작업 순서:** `test_w11_07`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_07 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "vm_missing_web_ready": False,
  "recovery_requires_proof": True,
  "unsupported_buttons": 0,
  "diagnostic_qa": None
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w11-08"></a>

## W11-08 — 활동 이력·worker 범위·공간 설정 조회

- [ ] **W11-08 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W11-08.md`(완료 시 생성).
- **직접 선행:** [W11-07](04b-environments-and-launcher.md#w11-07)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R14, R15, R21, UI-15.03, UI-15.04.
- **변경 파일:** `src/aiqa/web/templates/settings.html`, `src/aiqa/api/settings.py`, `src/aiqa/api/audit.py`. 담당 시험: `tests/acceptance/test_w11.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/audit; GET /api/v1/projects/{p}/storage; GET /api/v1/projects/{p}/workers; POST /api/v1/projects/{p}/worker-enrollments; POST /api/v1/workers/{w}/revoke -> CursorPage | StorageView | WorkerView`
- **구현·화면·예외:** UI-15 case/TC/suite/review/REC/RUN/env 변경 audit 필터·actor/time/reason 을 제공한다. worker enrollment/revoke·scope 와 공간/보호/삭제예정·한도상태를 표시한다. 실제 pin/GC/backup 조작은 W26 에서 연결하고 완료근거를 분리한다.
- **검증 전제:** 다른 project audit·worker 권한폐기·빈 공간/보호파일 초과표시·403·cursor 를 확인한다.
- **작업 순서:** `test_w11_08`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w11.py::test_w11_08 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "foreign_audit_rows": 0,
  "revoked_worker_can_claim": False,
  "protected_space_visible": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w12-01"></a>

## W12-01 — 로컬 launcher·중복시작·상태 UI

- [ ] **W12-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W12-01.md`(완료 시 생성).
- **직접 선행:** [W11-08](04b-environments-and-launcher.md#w11-08)
- **읽기:** CONTRACTS C00 / C01 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R10, R21, R26, UI-COMMON.04.
- **변경 파일:** `src/aiqa/launcher.py`, `src/aiqa/api/lifecycle.py`, `src/aiqa/web/templates/connection.html`. 담당 시험: `tests/acceptance/test_w12.py`.
- **입출력 계약:** `start_local_services(config: LauncherConfig) -> LocalServiceStatus; GET /api/v1/local-status`
- **구현·화면·예외:** 한 번 시작으로 API/worker 관리화면을 열고 독립 process 를 유지한다. port 충돌/이미실행/worker 없음/VM 미준비를 구별한다. 시작명령과 패키징은 이 작업산출에 포함하되 배포발행은 포함하지 않는다.
- **검증 전제:** 같은설정 두번 시작·다른 process port 사용·worker 실패·관리탭 종료를 확인한다.
- **작업 순서:** `test_w12_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w12.py::test_w12_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "api_instances": 1,
  "worker_instances": 1,
  "tab_close_cancels": False,
  "port_conflict_explained": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w12-02"></a>

## W12-02 — polling·탭 재접속·선택 항목 복원

- [ ] **W12-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W12-02.md`(완료 시 생성).
- **직접 선행:** [W12-01](04b-environments-and-launcher.md#w12-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R07, R10, R12, R26, UI-COMMON.05.
- **변경 파일:** `src/aiqa/web/static/polling.js`, `src/aiqa/api/events.py`, `src/aiqa/web/templates/components/connection.html`. 담당 시험: `tests/acceptance/test_w12.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/events?after_commit_seq={seq}; GET /api/v1/attempts/{a}/events?after_local_seq={seq}`
- **구현·화면·예외:** UI 2 초 poll·마지막수신·stale 를 표시한다. project commit cursor 와 attempt local_seq 를 따로 사용하고 조회는 mutation 재실행 0 이다. back/새로고침은 selected REC/ITEM/action 을 URL 로 복원한다.
- **검증 전제:** 조회연결끊김→재연결·page 숨김/복귀·탭닫기/열기·커서중복과 사건간 gap 을 확인한다.
- **작업 순서:** `test_w12_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w12.py::test_w12_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "poll_seconds": 2,
  "reconnect_mutations": 0,
  "selected_action_restored": True,
  "cursors_interchanged": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w12-03"></a>

## W12-03 — PC 절전·복귀·종료 안내와 안전 종료

- [ ] **W12-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W12-03.md`(완료 시 생성).
- **직접 선행:** [W12-02](04b-environments-and-launcher.md#w12-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C11 + 직접 선행 receipt의 interface/제약. 추적: R11, R15, R26, UI-COMMON.06.
- **변경 파일:** `src/aiqa/launcher.py`, `src/aiqa/api/lifecycle.py`, `src/aiqa/worker/service.py`, `src/aiqa/web/templates/connection.html`. 담당 시험: `tests/acceptance/test_w12.py`.
- **입출력 계약:** `stop_local_services(input: ServiceStopRequest) -> LocalServiceStatus; reconcile_after_resume() -> ReconciliationReport`
- **구현·화면·예외:** 진행작업이 있으면 종료/취소/정리영향을 보여주고 영구 flag 를 남긴다. PC 중단 동안 지속실행/즉시감지를 보장하지 않는다. 복귀 뒤 lost/불명·quarantine·새실행 안내로 연결하며 checkpoint 자동재개 0 이다.
- **검증 전제:** REC/RUN 진행중 절전/강제종료→복귀와 정상안전종료를 구분한다.
- **작업 순서:** `test_w12_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w12.py::test_w12_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "automatic_resume": 0,
  "unknown_marked_success": False,
  "last_received_visible": True,
  "cleanup_or_quarantine": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
