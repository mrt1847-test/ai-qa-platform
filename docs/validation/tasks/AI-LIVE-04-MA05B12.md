# AI-LIVE-04-MA05B12 · 사람용 동작 타임라인·안전한 갱신

2026-11-17 Asia/Seoul, BASE00db8b9 original master. source/원본 ID/state/승인/모델·native 호출 계약을 바꾸지 않은 표시 개선이다. 실제 pinned main/public API+mock OpenAI·ADB이며 실제 과금/기기0이다. 전체 RX87 완료 수는 유지한다.

## 변경

`recording.timeline_display`는 공통 viewer가 owner/hash 확인한 saved log를16KiB 안에서만 JSON 해석한다. known ma-call/schema/state/call ID가 맞을 때 앱 준비/탭·입력·스와이프·키 전달/제어/AI 준비 실패를 표시한다. plain/없는·손상된·foreign/wrong state/unknown schema는 번호 기반 동작으로 남긴다. before/after/log가 실제 모두 stored인 경우만 화면·로그 수신이며 legacy before-only observed는 관찰 기록이다.

unknown은 탭 요청/전달 결과 확인 불가, native ACK만 있는 경우 전달 확인, not_sent는 전달 전 중단, control_unobserved는 제어 단계/화면 확인 중단이다. 좌표가 같은 swipe를 long press로 추정하지 않는다. nativeNone은 기다림/종료를 추측하지 않고 제어 단계다. 표시로 QA PASS나 실제 실행을 만들지 않는다.

`_TimelineEntry`/timeline JSON은 label/state_label/before_label/after_label/log_label/check_label을 additive로 제공한다. machine ID·state·원문은 보존한다. 제목은 동작 중심, 원본 참조는 tooltip/기존 상세와 URL에 남는다. SSR action ID는 URL 인코딩하며 server canonical selection과 같은 행을 poll 후에도 강조한다.

`recording_timeline.js`는 모든 수신 문자열을 DOM textContent/고정 속성으로 넣는다. nav 갱신 시 그 안의 동작에 둔 포커스만 복원하며 바깥 폼/버튼 포커스를 빼앗지 않는다. 필요한 refresh에는 같은 녹화의 presentation focus만 sessionStorage로 잇고 작업을 재개하지 않는다. UI asset tag는20261117-ma05b12로 갱신했다.

## 검증·검토

초기 API RED5, Chrome probe는 old innerHTML의 문자열 실행/injectedtrue와 포커스 소실을 재현했다. 구현 후 관련12pass37.61s·boundary15pass0.06s. 한 fresh reviewer Important4(legacy 수신 과장/control 실패 label/stale 선택·URL 인코딩/rounded swipe 추정)를 RED4와 stale-query Chrome RED로 확인해 한 fix pass로 보완했다. re-review 없음.

최종 unit/API/UI/이력/취소/PC 검토 관련8파일 **49 passed67.42s**. Chrome은 실패/완료 미승인/진행/중단·악성 문자열·stale 선택6조건 ×360/768/1440의18회에서 SSR/poll label 일치, 선택/Tab/focus 유지, injectionfalse, 가로 overflow0, pageerror0, 변경 요청0을 확인했다. 실제 Jinja 응답과 정적 자산/저장된 PNG·API fixture를 렌더한 grade이며 browser mutation E2E/실기기 수용은 아니다.

[화면·재현 코드·결과](../ux/ma05b12/). 먼저 test_ma05_timeline_display.py와 test_ma05_recording_review_ui.py로 ignored fixture를 생성하고 `node docs/validation/ux/ma05b12/browser.cjs`를 실행한다. 필요한 기존 Playwright 경로는 AIQA_PLAYWRIGHT_MODULE로 지정한다. 원본 샘플과 desktop 실패/mobile legacy 화면을 시각 확인했다. 전체 suite green/실제 앱 TC 수로 표시하지 않으며 기존6개 기준선은 유지한다.

## 다음·제한

현재 선택 증거 패널의 긴 ID/geometry 코드/hardcoded swipe 문구는 MA05b1.3이다. 일반 viewer는 helper 전 전체 artifact를 읽고 hash를 검사하므로16KiB는 JSON 해석 한도이지 전체 I/O 한도가 아니다. valid-hash 비UTF8 log 등 공통 log 읽기 오류를 어떻게 보존 표시할지는 b1.3에서 실제 API 재현 후 보완한다. source/기존 승인·actual actor AI0 정책은 유지한다.
