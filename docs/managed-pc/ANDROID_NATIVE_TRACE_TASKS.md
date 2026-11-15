# RX87 B2.3b0 · 기록한 native 동작의 정확 재생

> REQUIRED SUB-SKILL: executing-plans inline/TDD, 마지막 fresh review1회/필수 수정1회. BASE c4b62ed, master. Spec B2.3 logical mapping 전제·C00/C04/C05/C14, 사용자 AI 녹화 후 AI 없는 재생 목표.

코드에서 확인한 선행 결함: text seal target이 실제 값 대신 text 상수, Enter 등의 key는 trace에서 누락, swipe renderer가 방향/시간을 추정하며 type을 아예 생략, 이미 physical인 좌표를 Mobile-Agent replay에서 다시 model→physical로 rescale한다. logical mapping을 이 원본 위에 연결하면 잘못된 동작에 연결된다. 먼저 새 녹화의 native trace v2를 고친다. 기존 v1 source/package/승인/FAIL bytes는 수정하지 않는다.

Architecture: replay/android_native_trace.py가 validated TypedAndroidAction+source physical geometry를 frozen tuple로 직렬화/검사하고, 새 android-native-trace-v2 이벤트는 실제 literal/key/duration/좌표를 보존한다. compiler는 v2에서 고정 physical: 표시 plan과 별도 compiler/lock ref를 사용한다. claim은 immutable mapping+source manifest ID/hash+package ID/hash/project의 native_source witness를 공급한다. worker는 witness를 재compile해 package hash/표시 plan/owner pin을 대조하고 geometry를 일치시킨 뒤 identity physical frame에서 기존 typed driver를 호출한다. actor/model 호출0이다. 선언된 v2가 손상/누락되면 legacy로 강등0. 명시 v1/no-schema 경로는 기존 개발·이력 호환으로 유지하며 정확한 새 입력 의미를 추측해 업그레이드하지 않는다.

- [x] 1 pure native event codec/TDD: tap/type/swipe/key/back의 모든 유효 native 매개변수·geometry roundtrip, bool/NaN/extra fields/count/중복 ID/line/bad geometry/secret marker 거절. v2 NativeActionCount==events count, source stroke geometry peraction. unsupported native를 생략한 completed source를 만들지 않는다.
- [x] 2 producer/compiler: 새 녹화 v2 root+actual action param; 모든 dispatched action이 trace에 있거나 source unavailable. 기존 v1 compiler는 그대로, v2 CodeHash/MappingHash/refs는 정확한 physical plan과 일치. legacy body bytes를 변경하지 않는다.
- [x] 3 server claim pin/API/worker snapshot에 native_source witness 연결, 재조회 동일·project/digest/scope/response mutation 분리. NativeSource가 있으면 항상 검증, physical: plan인데 witness 없으면 전송0. 같은 geometry에서 원래 recording argv==replay argv 및 replay AI0; 다른 geometry/package/malformed는 native0. 기존 no-source 개발 fixture 호환.
- [x] 4 집중·전체 baseline9/JS32·fresh review1+한 TDD 수정 pass·인계/NEXT/master commit. 실제 AI/device 수용은 별도이며 literal은 기존 typed driver의 비민감 허용 입력만 지원한다. 대상 SecretRef pixel coverage 차단은 유지한다. 임의 shell/새 helper/설치 없음.

Review focus: physical 좌표의 이중 rescale; source literal/키/시간 누락; v2→v1 downgrade; package witness와 source/current geometry 불일치; ACK/journal 뒤 codec 오류의 이전 evidence 유실. B2.3b mapping/UI와 B2.3c 실제 validator/normalized 저장은 다음이다.

완료 근거/리뷰 수정/관련 검증 범위: [인계](../validation/tasks/RX-87-B2-NATIVE-TRACE.md). 전체 green은 아니며 기존 baseline9를 보존한다. source/compiler/context 계약과 정상/개발 seam의 경계를 기록했다.
