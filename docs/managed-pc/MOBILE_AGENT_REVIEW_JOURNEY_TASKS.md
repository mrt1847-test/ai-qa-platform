# MA05b · 원본 저장본 검토·사후 승인·AI0 실행

Required: superpowers:executing-plans inline/TDD. Spec C05/C06와 기존 sample UI/검토·승인 계약을 유지한다. 직접 선행 MA05a1~4 인계, 범위별 소유 코드만 읽는다. 실제 키/기기를 선행으로 요구하지 않는다.

## MA05b1 · 저장된 녹화에 정확히 묶인 검토 UI

Confirmed gap: recording.html은 materialized_version_id가 없어도 case/review 링크를 보낸다. 실패 REC에는 새 source/version이 없으므로 링크가 다른 최신/기존 승인 후보를 열 수 있다. 현재 페이지에는 내부 package/compiler 설명과 raw completion code도 노출된다. 새 화면을 만들지 않고 기존 sample 기반 레이아웃/타임라인/키보드 흐름을 유지한다.

- [x] RED: 정상 API+원본 main의 native/model 실패 뒤 저장본 페이지를 열면 다른 candidate/base 승인을 여는 링크가 없어야 한다. 해당 timeline/PNG/log와 케이스에서 명시 재녹화할 경로는 남는다. PC offline에서도 검토 내용 조회는 가능하다.
- [x] 후보 version이 실제로 materialized된 경우만 그 exact version으로 검토 링크를 보낸다. 승인 가능 여부는 기존 package/complete/evidence/trial gate를 따른다. 실패본에 후보를 임의 생성하거나 오래된 version을 fallback으로 넣지 않는다.
- [x] 상태/다음 행동을 사용자 용어로 표시하고 compiler/package 구현 설명은 사용자 흐름에서 제거한다. raw machine completion code는 data attribute/JSON 계약으로 유지해 polling/선택 행동이 깨지지 않게 한다.
- [x] 정상 완료/미승인/실패/중단/진행 중과 offline을 확인한다. 기존 구성에서 세 폭 화면과 키보드 링크 이동을 검증한다. 기능/API·UI 영향 회귀, 한 fresh review/한 fix pass, 인계/큐/master commit.

## MA05b1.2 · 수신 타임라인의 사람용 동작·상태

직접 선행 b1 인계. 소유 recording._recording_timeline/_TimelineEntry, 필요한 read-only display helper, recording.html, recording_timeline.js. 실제 화면에서 ma UUID·observed/unknown/stored가 주 정보이고 polling이 nav를 재생성한다.

- [x] RED 정상 원본 저장 log의 앱 준비/탭/입력/스와이프/제어/모델 준비 실패·unknown ACK를 구분한 사람이 읽을 label/state를 검사한다. unknown은 실제 탭 성공으로 표시하지 않는다. legacy/plain/missing/corrupt log는 번호 기반 기본 표시로 남기고 동작을 추정하지 않는다.
- [x] 보관·hash/owner 검증된 saved log만 읽어 표시 정보를 만든다. model/native 호출0, source/원본 raw IDs/state/JSON/승인 의미 불변, 표시 필드는 additive다. 긴 참조는 기본 제목에서 빼고 기존 상세/URL/보조 참조로 보존한다.
- [x] SSR와 poll의 동작/증거 상태 표현·선택 highlight를 동일하게 유지한다. poll은 DOM textContent로 untrusted error/step/action 문자열을 넣고 innerHTML로 실행하지 않는다. 악성 HTML 모양의 timeline 문자열도 텍스트로만 보여야 한다.
- [x] 현재 snapshot 브라우저 helper로 poll 후3폭/Tab/선택 및 변조 텍스트 안전 렌더를 검사한다. 관련 API/UI 회귀·한 fresh review/한 fix pass·인계/큐/master commit. 실제 유료/기기0.

## MA05b1.3 · 선택 행동의 명령·좌표·근거 상세

직접 선행 [b1.2](../validation/tasks/AI-LIVE-04-MA05B12.md). 소유 공통 _ActionView/_viewer/_log/evidence_panel과 기존 REC·ITEM viewer 테스트, 필요한 read-only typed display helper다. 화면의 긴 ID/geometry 코드가 주 내용이고 '이 행동의 swipe 좌표는 없습니다'가 hardcoded다. 새 모델/기기를 부르지 않는다.

- [ ] RED 실제 saved tap/text/key/swipe source 또는 failure log를 선택해 요청/전달/관찰 상태와 명령을 읽을 수 있어야 한다. unknown은 실제 tap/성공으로 표시하지 않는다. swipe 두 점이 있을 때 정확히 표시하며 coincident endpoint를 long press로 추정하지 않는다. control/legacy/missing/corrupt는 알 수 없는 동작·좌표를 만들지 않는다.
- [ ] native 종류/값은 bounded known saved schema+same action/call/before hash로 확인하고 geometry는 해당 저장 관찰에 묶여 확인된 경우만 사용한다. 비율 추정·source/package/원본 명령 재작성 금지. log/owner/hash가 불명하면 일반 기록과 사유로 낮춰 표시한다. Web/ITEM legacy는 Android로 추정하지 않는다.
- [ ] 공통 viewer의 valid-hash 비UTF8 log·읽기 race를 실제 API로 재현한다. 페이지500 대신 읽기 불가/증거 확인 필요를 표시하고 원본 파일/metadata를 삭제·수정하지 않는다. ready/승인을 꾸미지 않는다.
- [ ] 선택 패널의 사용자용 동작·전달·좌표를 먼저 보여주고 raw ID/시각/geometry/log는 접을 수 있는 근거로 보존한다. 현재 이미지 맞춤/100%/확대/이동/전체보기와 선택·키보드를 유지한다. REC뿐 아니라 ITEM/trial 공통 표시·offline·실제 파일 상태를 회귀한다.
- [ ] actual API/mock driver+3폭 Chrome/키보드·한 fresh review/한 fix pass·인계/큐/master commit. 완료 수는 유지하고 이후 b2의 check 소비/사후 승인/AI0 선행을 대조한다.

## MA05b2 · 정상 source→검토→사후 승인→동일 package AI0

먼저 현재 source/check binding/evaluator/trial 준비 조건을 실제 코드로 대조한다. 원본 main이 만든 서버 manifest/package를 사용하고 fixture가 만든 별도 표시 코드/force approval로 갈아끼우지 않는다. 저장 후 browser review/실제 승인 API actor 이벤트와 같은 package ITEM/trial/regression의 deterministic native·actor AI0·healing OFF를 확인한다. 검증 AI는 승인된 지점/예산만 허용한다. 논리 check 소비가 미구현이면 B2.3b/C/D의 구체 구현 단위를 먼저 편성하며 외부 환경 대기로 숨기거나 assertion/승인 gate를 완화하지 않는다.

전체 MA05/RX87 완료는 별도 수용이다. 실제 paid/device/월3000건 비용은 최종 기능 뒤 독립 수용으로 남긴다.

MA05b1 완료: [인계](../validation/tasks/AI-LIVE-04-MA05B1.md), 관련45pass54.49s + Chrome12 renders/keyboard. b1.2/1.3/b2와 전체 RX87은 미완료다.

MA05b1.2 완료: [인계](../validation/tasks/AI-LIVE-04-MA05B12.md), 관련49pass67.42s + Chrome18회/안전 텍스트/선택·포커스. 다음 b1.3이다.
