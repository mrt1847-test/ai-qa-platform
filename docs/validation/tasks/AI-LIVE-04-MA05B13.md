# AI-LIVE-04-MA05B13 · 저장 명령·좌표·근거 상세

- 상태: complete (이 세부 구현 범위). 기준 master `01797e9`; 완료 revision은 이 파일을 포함한 로컬 커밋이다.
- 선행: MA05B12 인계, MOBILE_AGENT_REVIEW_JOURNEY_TASKS MA05b1.3. 계약 C05/C06. DB migration/API route/원본 명령·source·승인 정책 변경 없음.
- 등급: actual pinned original main + public API/runtime, mock OpenAI/ADB/앱 준비. 유료 AI·실기기·사람 승인 0. RX87 전체 및 기존 완료 수는 유지한다.

## 구현

`recording.action_evidence_display.describe_action_evidence`와 공통 `_ActionView.detail`은 선택한 행동의 요청/전달/관찰 사실, 저장 명령·좌표를 표시한다. known log는16KiB 이내, 동일 action/call/state와 before hash를 확인한다. REC owner/attempt/job/원본 engine·ACK before·모델 관찰 geometry/hash를 묶고 완료된 same worker/policy 모델 receipt를 로컬 pinned parser로 대조한다. 모델 API·기기 호출 없이 원본 typed native와 정확히 같을 때만 명령을 표시한다. missing/foreign/legacy/ITEM 또는 근거 충돌이면 번호 기반 기록으로 남고 좌표를 추정하지 않는다.

탭은 저장 physical 좌표, swipe는 두 점과 duration, 입력은 글자 수, 키는 코드/뒤로가기를 보여준다. 원본 swipe 변환 결과 `(9,40)→(79,179)`를 임의 `(10,40)→(80,180)`으로 바꾸지 않는다. unknown은 요청이며 기기 성공/검증 PASS가 아니다. native 없는 제어 단계와 동작 생성 전 실패도 실행했다고 표시하지 않는다. 입력 원문은 기존 접힌 로그에서 확인한다.

공통 evidence_panel은 사용자용 동작·상태·명령을 먼저, raw ID/서버 보관 시각/실제 bound before 캡처 시각/원문 로그는 접어서 보존한다. 서버 stored_at을 캡처 시각으로 부르지 않는다. 기존 이미지 맞춤·100%·확대·이동·전체보기/선택/키보드는 유지했다.

`api.artifacts._state/_log`는 path resolution/read 실패와 유효 hash의 비UTF8를 안전하게 표시한다. `_log`는 실제 decode하는 두 번째 read도 hash를 검사해 읽기 사이 변화를 표시한다. 파일·ready metadata·승인/source는 수정하지 않는다. timeline의 읽기 불가 log는 missing/읽기 불가이며 증거 수신 완료를 만들지 않는다. optional protocol import 실패와 유효하지 않은 과거 명령도 generic 확인 필요로 낮춰 전체 페이지500을 막는다.

## 검증·검토

초기 RED5(상세 없음/비UTF8 crash), 원본 receipt 대조 RED3. 한 fresh reviewer의 Important3을 RED7(모듈/invalid plan 예외, owner/frame 전 제목 해석, 두 path resolution IO)로 재현해 한 fix pass로 보완했다. re-review 없음. Minor인 per-action pinned protocol 재컴파일은 request-local 재사용 후속으로 남긴다. 전역 캐시로 원본 pin 재검증을 생략하지 않는다.

최종 명령:

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma05_action_detail.py tests/integration/test_ma05_timeline_display.py tests/integration/test_ma05_recording_review_ui.py tests/integration/test_w16.py tests/acceptance/test_w18.py -q -p no:cacheprovider --tb=short
node --test tests/web/evidence_viewer.test.cjs
node docs/validation/ux/ma05b13/browser.cjs
```

결과: **41 passed92.17s**, JS **2 passed**. 별도 Chrome은 unknown tap/swipe/text/key/읽기 불가5조건×360/768/1440 **15회**에서 명령 표시·refs/log Enter 펼침·이전/다음 화살표·맞춤/100%/확대/이동/전체보기 진입·종료를 확인했다. 가로 overflow/pageerror/변경 요청0. [코드·화면·결과](../ux/ma05b13/). 실제 SSR/정적 자산/저장 API·PNG fixture를 별도 headless Chrome context에서 렌더했으며 실제 사용자의 브라우저나 실행 PC를 제어하지 않았다. 작은 합성 PNG의 이동 모드/이벤트 확인이며 큰 실 캡처의 물리 이동 수용으로 과장하지 않는다. mobile swipe 화면을 시각 확인했다.

## 다음·제한

MA05b2에서 정상 원본 source→사후 검토/승인→동일 package AI0의 실제 선행을 확인한다. 현재 logical binding worker 소비·실제 validator/normalized 결과 저장이 없으면 B2.3b3/c부터 구체 구현한다. 승인/required check를 완화해 통과시키지 않는다.

16KiB는 해석 한도이며 공통 viewer의 전체 파일 읽기·hash 검사는 유지한다. generic Web/ITEM의 좌표 상세 해석은 이 범위가 아니다. 기존 전체 회귀6개 기준선은 유지하며 전체 suite green/실제 앱 TC/live 수용으로 표시하지 않는다. 기존 dirty metadata-load.md는 수정·커밋하지 않았다.
