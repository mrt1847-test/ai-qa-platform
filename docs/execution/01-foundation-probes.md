# A · 공개 코드·모델·연결 탐색 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 11**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W01-01](#w01-01) | 없음 | 공개 원본과 출력·쓰기 경계 목록 |
| [W01-02](#w01-02) | [W01-01](01-foundation-probes.md#w01-01) | 같은 PC VM 과 신뢰 driver 통신 탐색 |
| [W01-03](#w01-03) | [W01-02](01-foundation-probes.md#w01-02) | Web authoring 산출물에서 계측 IPC 로 변환 탐색 |
| [W01-04](#w01-04) | [W01-03](01-foundation-probes.md#w01-03) | Web 직접 replay 가능성과 채택 판정 |
| [W02-01](#w02-01) | [W01-04](01-foundation-probes.md#w01-04) | 지정 USB 기기 관찰과 serial 경계 |
| [W02-02](#w02-02) | [W02-01](01-foundation-probes.md#w02-01) | 좌표 변환과 tap·swipe·back 탐색 |
| [W02-03](#w02-03) | [W02-02](01-foundation-probes.md#w02-02) | 한글·비밀 참조 입력과 IME 복구 |
| [W02-04](#w02-04) | [W02-03](01-foundation-probes.md#w02-03) | Android authoring trace 와 replay 지원표 |
| [W03-01](#w03-01) | [W02-04](01-foundation-probes.md#w02-04) | 역할별 모델 binding 호환 판정 |
| [W03-02](#w03-02) | [W03-01](01-foundation-probes.md#w03-01) | 출처·패치·dependency lock 결정 |
| [W03-03](#w03-03) | [W03-02](01-foundation-probes.md#w03-02) | P0 탐색 gate 와 다음 모델 인계 |

<a id="w01-01"></a>

## W01-01 — 공개 원본과 출력·쓰기 경계 목록

- [ ] **W01-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W01-01.md`(완료 시 생성).
- **직접 선행:** 없음. 현재 설계/원본 source만 확인.
- **읽기:** CONTRACTS C00 / C01 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R04, R14, R17.
- **변경 파일:** `third_party/cuawright/SOURCE.json`, `patches/cuawright/README.md`, `docs/validation/web-source.md`. 담당 시험: `tests/integration/test_w01.py`.
- **입출력 계약:** `inspect_cuawright_source(source: EngineRef) -> SourceInventory(files, code_outputs, writers, action_calls)`
- **구현·화면·예외:** 기존 조사 SHA 35dbcf389ce2d9a77eb22f539c79a1274ea53559 의 실제 파일/함수/line 을 기록한다. 원본 code 생성·직접 Playwright·LLM helper·PNG/debug writer 를 구별하고 각 hook 후보를 명시한다. 제품 API 에서 생성 코드를 실행하지 않는다.
- **검증 전제:** 지정 SHA 와 원본 LICENSE 를 읽고 inventory 의 각 위치를 실제 파일과 대조한다.
- **작업 순서:** `test_w01_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w01.py::test_w01_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "sha": "35dbcf389ce2d9a77eb22f539c79a1274ea53559",
  "all_locations_exist": True,
  "unclassified_writers": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w01-02"></a>

## W01-02 — 같은 PC VM 과 신뢰 driver 통신 탐색

- [ ] **W01-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W01-02.md`(완료 시 생성).
- **직접 선행:** [W01-01](01-foundation-probes.md#w01-01)
- **읽기:** CONTRACTS C00 / C01 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R14, R17, R25, R34.
- **변경 파일:** `src/aiqa/worker/isolated_web.py`, `src/aiqa/replay/driver.py`, `src/aiqa/replay/ipc.py`, `docs/validation/web-isolation.md`. 담당 시험: `tests/integration/test_w01.py`.
- **입출력 계약:** `probe_web_isolation(config: VmProbeConfig) -> IsolationProbeReport`
- **구현·화면·예외:** 동일 PC disposable Linux VM 에서 Chromium·driver 와 별도 script 권한/네트워크를 마련한다. driver 만 browser/CDP handle 을 갖고 IPC 는 typed action 만 받는다. 정확한 VM 제품/버전·필요 권한·준비·파기 방법을 이 탐색의 ADR 에 고정한다. 미지원이면 차단 근거를 남긴다.
- **검증 전제:** 합성 script 로 CDP·model endpoint·호스트 credential mount·subprocess 우회를 시도하고 실제 네트워크/권한 거부 근거를 수집한다.
- **작업 순서:** `test_w01_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w01.py::test_w01_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "driver_ipc": True,
  "direct_cdp": False,
  "script_model_network": False,
  "host_secret_access": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w01-03"></a>

## W01-03 — Web authoring 산출물에서 계측 IPC 로 변환 탐색

- [ ] **W01-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W01-03.md`(완료 시 생성).
- **직접 선행:** [W01-02](01-foundation-probes.md#w01-02)
- **읽기:** CONTRACTS C00 / C01 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R04, R07, R29, R34.
- **변경 파일:** `src/aiqa/adapters/cuawright_web.py`, `patches/cuawright/action_hooks.md`, `docs/validation/web-actions.md`. 담당 시험: `tests/integration/test_w01.py`.
- **입출력 계약:** `probe_web_authoring(fixture: WebProbeFixture, binding: ModelBinding) -> AuthoringProbeReport`
- **구현·화면·예외:** 합성 로그인 페이지에서 CUAWright code 를 얻고 raw→제한 IPC 변환 가능 범위를 기록한다. tap/type/scroll 마다 전후 정제 capture·source line mapping 을 얻으며 compound helper 내부 동작을 누락하지 않는다.
- **검증 전제:** 합성 단계 하나가 입력/탭/스크롤 3 행동을 수행하도록 하고 실제 driver dispatch 와 capture 수를 대조한다.
- **작업 순서:** `test_w01_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w01.py::test_w01_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "actions": 3,
  "before_png": 3,
  "after_png": 3,
  "mapped_actions": 3,
  "raw_unhooked_actions": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w01-04"></a>

## W01-04 — Web 직접 replay 가능성과 채택 판정

- [ ] **W01-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W01-04.md`(완료 시 생성).
- **직접 선행:** [W01-03](01-foundation-probes.md#w01-03)
- **읽기:** CONTRACTS C00 / C01 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R04, R17, R34.
- **변경 파일:** `docs/validation/web-spike.md`, `tools/validation/probe_web.py`. 담당 시험: `tests/integration/test_w01.py`.
- **입출력 계약:** `probe_web_replay(bundle: ProbeBundle) -> ReplayProbeReport`
- **구현·화면·예외:** 원본 authoring 과 별개로 같은 IPC 산출물을 모델 credential 제거/endpoint 차단 상태에서 재생한다. 가능 범위·불가 문법·patch/compiler/lock 초안을 기록한다. 탐색 bundle 은 정식 approval package 가 아니다.
- **검증 전제:** 새 context 에서 동일 합성 기대를 확인하고 생성 script 의 숨은 model 호출을 주입해 거부한다.
- **작업 순서:** `test_w01_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w01.py::test_w01_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "actor_calls": 0,
  "checks_passed": True,
  "bypass_rejected": True,
  "production_approved": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w02-01"></a>

## W02-01 — 지정 USB 기기 관찰과 serial 경계

- [ ] **W02-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W02-01.md`(완료 시 생성).
- **직접 선행:** [W01-04](01-foundation-probes.md#w01-04)
- **읽기:** CONTRACTS C00 / C01 / C05 + 직접 선행 receipt의 interface/제약. 추적: R02, R05, R14.
- **변경 파일:** `src/aiqa/adapters/mobile_agent_android.py`, `docs/validation/android-observation.md`. 담당 시험: `tests/integration/test_w02.py`.
- **입출력 계약:** `probe_android_observation(serial: str) -> AndroidProbeReport`
- **구현·화면·예외:** Mobile-Agent SHA 81fa28b564ef7a695521500bc15a0e1324b2b394 의 함수/line 과 host Windows ADB 경계를 조사한다. 지정 serial 만 관찰하고 unauthorized/offline/locked/FLAG_SECURE 를 구별한다. raw shell 은 열지 않는다.
- **검증 전제:** 지정/미지정 serial·권한 없음·capture 불가 fixture 와 실기기 상태를 대조한다.
- **작업 순서:** `test_w02_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w02.py::test_w02_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "serial_pinned": True,
  "unknown_serial_rejected": True,
  "secure_capture_bypassed": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w02-02"></a>

## W02-02 — 좌표 변환과 tap·swipe·back 탐색

- [ ] **W02-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W02-02.md`(완료 시 생성).
- **직접 선행:** [W02-01](01-foundation-probes.md#w02-01)
- **읽기:** CONTRACTS C00 / C01 / C05 + 직접 선행 receipt의 interface/제약. 추적: R05, R07, R29.
- **변경 파일:** `src/aiqa/adapters/mobile_agent_android.py`, `patches/mobile-agent/coordinates.md`, `docs/validation/android-actions.md`. 담당 시험: `tests/integration/test_w02.py`.
- **입출력 계약:** `transform_point(point: ModelPoint, capture: CaptureGeometry) -> DevicePoint`
- **구현·화면·예외:** 원본/모델 입력 크기·inverse transform·rotation·content bounds 를 저장한다. 승인 세로 조건의 tap/swipe/back 만 argument list 로 dispatch 하고 매 행동 전후 PNG 를 정제한다.
- **검증 전제:** 1080×2400→540×1200 모델 입력의 (270,600)을 변환하고 범위 밖·회전 변경·미지원 action 을 거부한다.
- **작업 순서:** `test_w02_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w02.py::test_w02_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "device_point": [
    540,
    1200
  ],
  "outside_rejected": True,
  "rotation_change_stops": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w02-03"></a>

## W02-03 — 한글·비밀 참조 입력과 IME 복구

- [ ] **W02-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W02-03.md`(완료 시 생성).
- **직접 선행:** [W02-02](01-foundation-probes.md#w02-02)
- **읽기:** CONTRACTS C00 / C01 / C05 + 직접 선행 receipt의 interface/제약. 추적: R05, R11, R14.
- **변경 파일:** `src/aiqa/environments/usb_android.py`, `patches/mobile-agent/input.md`, `docs/validation/android-input.md`. 담당 시험: `tests/integration/test_w02.py`.
- **입출력 계약:** `probe_android_input(serial: str, input_ref: SecretRef | LiteralInput) -> InputProbeReport`
- **구현·화면·예외:** ADB Keyboard 의 한글 입력 지원과 이전 IME 복구를 확인한다. 허용된 입력 action 에서만 host 가 secret ref 를 해석한다. 성공/취소/입력 오류 모두 finally 복구하고 복구 불명은 quarantine 이다.
- **검증 전제:** 합성 앱에 한글 문자열과 secret ref 를 입력하고 취소/예외를 주입해 IME 와 저장 파일을 검사한다.
- **작업 순서:** `test_w02_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w02.py::test_w02_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "korean_input_ok": True,
  "secret_in_saved_files": False,
  "ime_restored_or_quarantined": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w02-04"></a>

## W02-04 — Android authoring trace 와 replay 지원표

- [ ] **W02-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W02-04.md`(완료 시 생성).
- **직접 선행:** [W02-03](01-foundation-probes.md#w02-03)
- **읽기:** CONTRACTS C00 / C01 / C05 + 직접 선행 receipt의 interface/제약. 추적: R05, R12, R17.
- **변경 파일:** `docs/validation/android-spike.md`, `tools/validation/probe_android.py`. 담당 시험: `tests/integration/test_w02.py`.
- **입출력 계약:** `probe_android_plan(trace: AuthoringTrace) -> AndroidPlanProbeReport`
- **구현·화면·예외:** Mobile-Agent 관찰/행동 trace 를 tap/type/swipe/back plan 으로 투영해 신뢰 runner 로 재생 가능한지 확인한다. UI hierarchy 가용성·좌표 고정 조건·USB 단절 후 결과 불명을 명시한다.
- **검증 전제:** model loop 없이 합성 plan 을 실행하고 dispatch 뒤 USB timeout 에서 같은 action 재전달이 없는지 확인한다.
- **작업 순서:** `test_w02_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w02.py::test_w02_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "actor_calls": 0,
  "post_dispatch_retry": 0,
  "supported_actions": [
    "tap",
    "type",
    "swipe",
    "back"
  ]
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w03-01"></a>

## W03-01 — 역할별 모델 binding 호환 판정

- [ ] **W03-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W03-01.md`(완료 시 생성).
- **직접 선행:** [W02-04](01-foundation-probes.md#w02-04)
- **읽기:** CONTRACTS C00 / C01 / C06 / C07 + 직접 선행 receipt의 interface/제약. 추적: R03, R13, R14.
- **변경 파일:** `src/aiqa/models/compatibility.py`, `docs/validation/model-compatibility.md`. 담당 시험: `tests/integration/test_w03.py`.
- **입출력 계약:** `check_binding(binding: ModelBinding, fixture: CompatibilityFixture) -> CompatibilityReport`
- **구현·화면·예외:** provider·endpoint 종류·model alias/actual model·image/좌표/action schema·parse/timeout/usage 누락을 검사한다. authoring/verifier/healer 를 동일 모델이라는 이유로 호환으로 간주하지 않는다.
- **검증 전제:** 유효 image/action·잘못된 action·usage 누락·timeout 응답을 입력해 role 별 supported/error 를 관찰한다.
- **작업 순서:** `test_w03_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w03.py::test_w03_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unknown_action_dispatched": False,
  "missing_usage": None,
  "role_results_separate": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w03-02"></a>

## W03-02 — 출처·패치·dependency lock 결정

- [ ] **W03-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W03-02.md`(완료 시 생성).
- **직접 선행:** [W03-01](01-foundation-probes.md#w03-01)
- **읽기:** CONTRACTS C00 / C01 / C06 / C07 + 직접 선행 receipt의 interface/제약. 추적: R14, R17, R34.
- **변경 파일:** `pyproject.toml`, `third_party/mobile_agent/SOURCE.json`, `patches/README.md`, `docs/decisions/0001-upstream-runtime.md`. 담당 시험: `tests/integration/test_w03.py`.
- **입출력 계약:** `resolve_engine_refs(reports: list[ProbeReport]) -> EngineAdoptionDecision`
- **구현·화면·예외:** 두 원본 SHA/LICENSE/NOTICE·원본 포함 방식·patch 순서·compiler/driver/broker 경계·실행 가능한 Python/dependency/model lock 을 명시한다. 현 조사만으로 최신 HEAD/Windows 호환을 주장하지 않는다.
- **검증 전제:** 깨끗한 임시 작업 경로와 한글/공백 경로에서 채택 lock·patch 적용/출처 해시를 대조한다.
- **작업 순서:** `test_w03_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w03.py::test_w03_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "source_hashes_verified": True,
  "license_records": 2,
  "clean_reproduction": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w03-03"></a>

## W03-03 — P0 탐색 gate 와 다음 모델 인계

- [ ] **W03-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W03-03.md`(완료 시 생성).
- **직접 선행:** [W03-02](01-foundation-probes.md#w03-02)
- **읽기:** CONTRACTS C00 / C01 / C06 / C07 + 직접 선행 receipt의 interface/제약. 추적: R16, R17, R34.
- **변경 파일:** `docs/validation/upstream.md`, `docs/validation/compatibility-matrix.md`. 담당 시험: `tests/integration/test_w03.py`.
- **입출력 계약:** `evaluate_upstream_gate(reports: list[ProbeReport]) -> GateDecision`
- **구현·화면·예외:** Web/Android·매 action capture·Web 격리·AI 형식·직접 replay 의 실제 근거를 합친다. 불가 항목은 차단과 설계 변경 필요 사항으로 남기며 격리/재생을 제거해 통과시키지 않는다.
- **검증 전제:** 필수 근거 하나 누락/부정 시험 미실행/실기기 없는 결과를 gate 입력으로 사용한다.
- **작업 순서:** `test_w03_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w03.py::test_w03_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "missing_evidence_passes": False,
  "mock_only_passes": False,
  "next_requires_gate": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
