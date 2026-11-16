# AI-LIVE-04-MA05B1 · 녹화 저장본에 묶인 검토 UI

2026-11-17 Asia/Seoul, BASE6c1312a original master. UI_SPEC UI06/07·prototype/screenshots/review-desktop.png의 QA Studio 헤더/카드/패널·타임라인 구성을 유지한 국소 수정이다. source/승인/모델/driver 계약은 바꾸지 않았다.

## 변경

후보가 materialized되지 않은 실패/open REC는 다른 최신/승인 후보로 가는 case/review 링크를 만들지 않는다. offline_gate도 None으로 최신 version을 선택하는 fallback 없이 실제 produced version이 있을 때만 계산한다. 재녹화는 이 REC의 produced version 또는 자신의 input version을 base로 지정하고 준비 페이지로만 이동한다. 실제 녹화/승인은 자동 실행하지 않는다.

녹화 상태·서버 보관·화면/로그·후보 상태를 나눠 사용자 용어로 표시한다. compiler/package 내부 설명은 기본 흐름에서 제거했다. machine data-completion-status/타임라인 선택/파라미터·API 의미는 유지한다. 화면/로그 수신 카드는 complete flag뿐 아니라 비어 있지 않은 해당 타임라인의 before/after/log가 모두 실제 stored인지 확인한다. 빈 legacy stop, missing/corrupt는 확인 필요다. 이 카드는 동작 증거 상태이며 QA/논리 Check PASS가 아니다.

## 검증·검토

실제 정상 API+원본 main/mock OpenAI·ADB로 같은 case의 정상 source→별도 실패 REC/PC offline을 만들고 잘못된 review 링크 및 상태 표시 RED4를 재현했다. 관련19pass/old W16 phrase1fail 뒤 structured approval flag+DB 승인None으로 검사하여42pass44.26s. 한 fresh reviewer Important1(legacy stop 빈 타임라인의 완료 오표시)을 빈 stop/missing/corrupt RED3로 보완, 한 fix pass/no re-review. 최종 관련6개 파일 **45 passed54.49s**.

실제 Jinja 응답·타임라인·정제 artifact를 fixture로 저장하고 설치된 headless Chrome에서 제품의 실제 정적 자산을 렌더링했다. 실패/완료 미승인/진행/중단4상태 ×360/768/1440의12회에서 가로 overflow0, pageerror0, 변경 요청0. header case→rerecord→exact review의 실제 Tab 이동을 확인했다. 최종 재실행도12회 통과했다. live 브라우저 mutation E2E나 실기기/유료 수용은 아니다.

재현: `.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma05_recording_review_ui.py -q -p no:cacheprovider`로 ignored snapshot을 만든 뒤 `node docs/validation/ux/ma05b1/browser.cjs`. Playwright module이 기본 Node 경로에 없으면 AIQA_PLAYWRIGHT_MODULE로 기존 설치 경로를 지정한다. 새 설치/사용자 브라우저 프로필을 사용하지 않는다.

[화면·결과](../ux/ma05b1/)에 실패360/768/1440, 완료1440 PNG와 browser-report.json을 남겼다. 실제 source/승인 생성 수를 UI 검사에서 늘리지 않으며 기존6개 전체 회귀 실패 기준선과 RX87 완료 수는 유지한다.

## 다음

MA05b1.2는 원본 UUID/dispatch code가 주로 보이는 타임라인을 사람용 동작/전달 상태로 정리하고 poll 후에도 유지한다. MA05b1.3은 선택 행동의 typed 명령·좌표/실제 swipe 유무를 정직하게 표시한다. 공통 evidence_panel의 현재 hardcoded swipe 문구/긴 참조는 그대로 남아 있으며 이번 완료 범위가 아니다. 그 뒤 b2의 실제 승인/같은 package AI0 여정과 logical check 소비 선행을 확인한다.
