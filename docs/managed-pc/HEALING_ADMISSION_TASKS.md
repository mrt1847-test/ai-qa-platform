# Healing 접수 선행 작업

Updated: 2026-11-09. 실행 순서는 NEXT_ACTION.md만 관리한다. 운영 키·독립 PC/VM 없이 로컬 fixture로 구현하며 실제 모델 수용 RX-23/24를 완료로 바꾸지 않는다.

근거: 구조화 editor API는 extension을 보존하지만 공통 settings normalizer는 복구 binding 참조/개정을 버리고, 설정 화면은 이를 입력할 수 없다. limits extension은 검증 없이 저장된다. RX-86의 정책 해석·접수·claim을 한 번에 바꾸지 않도록 아래로 나눈다.

<a id="rx-92"></a>
## RX-92 · 복구 모델 연결·개정과 한도의 설정 저장 왕복

**선행** RX-54/RX-91. **계약** C00/C01/C08/C09/C14. **환경** local_python/local_browser.

- [x] 공통 settings normalizer가 healing_policy.model_binding_ref / binding_revision의 문자열을 보존한다. 값이 없던 OFF 케이스에 키를 요구하거나 자동 ON하지 않는다. 키 원문/클라이언트 key_present를 자격 증명으로 취급하지 않는다.
- [x] 기존 케이스 limits의 budget/currency/max_actions/max_model_calls 및 복구 전역 상한을 검증·보존한다. timeout만 수정해도 누락된 값이 기본값으로 덮이지 않는다. 비유한 비용·음수·분수 행동/호출·잘못된 타입은422이며 새 버전을 쓰지 않는다.
- [x] 케이스 설정 화면에 복구 연결 참조와 고정 개정을 추가하고 조회→수정→저장→충돌 비교→재조회에서 유지한다. 저장은 새 초안이며 승인본/기존 실행과 OFF 기본값은 유지한다.
- [x] 실제 API/임시 DB·JS 제출/충돌·브라우저/키보드로 확인한다. model binding의 실제 존재·역할·키 유효 판정은 RX-93이며 입력만으로 준비 완료라고 표시하지 않는다.

**인계** docs/validation/tasks/RX-92.md.

<a id="rx-93"></a>
## RX-93 · 승인 정책의 서버 binding·키 개정 해석

**선행** RX-92. **계약** C00/C01/C08/C09/C14. **환경** local_python.

- [x] 승인된 case settings와 explicit 요청을 받아 기존 resolve_healing_policy를 사용하는 서버 해석 경계를 만든다. OFF/trial OFF는 healing key 없이 유지한다.
- [x] ON은 동일 프로젝트·healing 역할·명시 binding revision의 실제 메타데이터와 그 고정 secret ref/revision의 availability를 확인한다. 최신 개정으로 대체하거나 client healer_key_present를 믿지 않는다.
- [x] 승인 scope/caps·전역 budget·요청 상한을 좁혀 immutable resolution/hash와 비밀값 없는 binding pin/차단 이유를 반환한다. 승인·기록·키 메타데이터를 수정하거나 모델을 호출하지 않는다.
- [x] 교차 프로젝트/잘못된 역할/개정 없음/키 없음·폐기/예산0·비유한/승인 좁은 상한/OFF를 임시 DB로 확인한다.

**인계** docs/validation/tasks/RX-93.md. RX-86은 이 결과를 preview/admission/request hash·ITEM snapshot에 연결한다.

<a id="rx-94"></a>
## RX-94 · claim 시 고정 healing 정책·binding·키 재검사

**선행** RX-86/RX-93. **계약** C00/C01/C08/C09/C14. **환경** local_python.

- [ ] claim 전에 ON ITEM의 고정 binding/key 개정과 승인 policy/hash를 재검사한다. 접수 이후 폐기·역할/정책/개정 불일치면 행동 전에 fail closed한다.
- [ ] OFF/legacy snapshot은 기존 결정적 경로와 같은 키 없는 동작을 유지한다. ON을 OFF로 조용히 낮추거나 최신 binding으로 갈아타지 않는다.
- [ ] 정상 queue claim/변경 후 거절/임대·접수 불변을 임시 DB로 증명하고 Android/Web runtime 소비에 필요한 안전한 pin interface를 인계한다.

**인계** docs/validation/tasks/RX-94.md.
