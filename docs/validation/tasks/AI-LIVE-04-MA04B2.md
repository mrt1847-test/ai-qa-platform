# AI-LIVE-04-MA04B2 · 원본 녹화 session coordinator

2026-11-16 Asia/Seoul. 원본 master BASE567cb27. 실제 유료 모델/ADB 호출0. 전체 RX87·87/99·49/53는 유지한다.

worker/mobile_agent_recording.py의 MobileAgentRecordingSession은 실제 pinned upstream main subprocess의 capture/model/native callbacks를 정상 server-owned model API와 deterministic driver에 연결한다. child는 worker token/API key 없이 실행하고, 서버는 같은 call/attempt의 원본 대화·관찰·이력을 검증한다. worker가 자체 계획 루프로 원본 engine을 대체하지 않는다.

각 실제 native는 fresh capture/geometry/frame guard→planned/STARTED fsync→최종 checkpoint→단일 OS send 순이다. ACK는 journal/native-prefix.json에 저장하고 parent에 반환한 뒤 다음 capture에서 after/log를 서버에 commit한다. 같은 turn의 ordered after/log ACK로 model pending을 해제하기 전 다음 모델 요청은 금지다. after capture/upload 실패에도 알려진 실행 수와 physical prefix를 보존하고 unknown은 재시도하지 않는다. wait/terminal도 전후 PNG/log 증거를 저장하지만 native/source 동작 수를 늘리지 않는다.

정상 원본 success·native1개 이상·모든 turn 증거 ACK·현재 source checkpoint·source-v2 upload ACK가 있어야 review_pending 결과와 compile-ready action_mapping을 만든다. 이는 사람 승인이 아니며 승인본 테스트 실행도 아니다. zero-native는 logical evidence만 남기고 no_native_actions로 replay 후보를 거절한다. 같은 attempt directory를 재사용해 녹화를 재시작할 수 없다. metadata 복구만 별도 committer.resume_pending으로 가능하다.

검증: 새 통합11개 + 원본 process/model port/durable evidence 총67passed88.69s. 실제 upstream main을 별도 child에서 실행하고 정상 ASGI model/evidence API를 통과했으며 OpenAI와 ADB만 fixture다. click→terminate, wait→click→terminate, known ACK 후 capture 실패, 불명 timeout, 화면 drift, STARTED 뒤 gate 거절, 동일 directory 재시도, source ACK/prefix 쓰기 실패, source current authority, zero-native 거절을 확인했다. 최종 리뷰 보완 결과는 아래와 같다.

Ruling: 현재 단위는 internal session이고 runtime handler/선택 앱 준비/current lease binder/접수 engine marker 등록은 MA04c에서 함께 연결한다. 비용: 일반 웹 접수의 default는 아직 이전 경로이며 이 내부 통합을 정상 웹 전체 녹화 완료로 해석할 수 없다.

Ruling: source-v2는 physical ACK만 포함한다. wait/terminal은 logical evidence로 보존하고 native0이며 zero-native replay 지원은 후속 명시 설계가 필요하다. 비용: 화면 확인만 하는 녹화는 증거가 있어도 이 단위에서 replay source로 승격하지 않는다.

다음: MA04c 정상 runtime handler·target preparation·lease/checkpoint와 명시 supported engine/admission 등록, finish receipt로 저장본 검토 대기를 연결. 이후 MA05 실제 사람 승인과 AI0 package 실행 여정을 별도 확인한다.

최종 fresh review Important4(critical/minor0)를 재현했다: cutoff1+추가8 RED. 단일 fix pass로 session monotonic cutoff를 final capture/source 뒤까지 적용하고, 차단/예외는 final_authority_refused로 이전 native/증거 수를 보존한다. blocking callback/capture와 source ACK 뒤 현재 권한을 재검사한다. source ACK 뒤 취소되면 artifact ID/ACK cursor는 남기되 mapping/review 후보를 만들지 않는다. journal ACK와 native-prefix를 독립 저장해 한쪽 쓰기 실패에도 다른 기록을 남긴다. worker owner를 생성자에서 검사해 잘못된 claim으로 모델/기기를 호출하지 않는다. 새 통합20passed73.02s. 재리뷰0, deferred minor0.

Final Ruling: 동일 attempt directory만 이 session에서 원자적으로 거절한다. MA04c의 trusted runtime은 runtime root 아래 attempt UUID별 canonical 경로를 선택해야 한다. 비용: 임의의 서로 다른 output 경로까지 이 helper가 전역 중복 실행을 막는 것은 아니며 hostile host 인증 수단도 아니다.

MA04c 소비 주의: parent allowed()는 local cancel/monotonic/keepalive 상태만 읽고 polling마다 HTTPS를 보내지 않는다. before_model은 기존 before_model, 최종 before_native만 기존 before_dispatch(동작 예산1회), 나머지 capture/초기 dispatch/finalization은 before_lookup 등 허용 phase로 매핑한다. trusted runtime이 선택 앱 준비·serial/case context를 검증하고 준비에 쓴 native/time 예산을 session에 포함시켜야 한다. 현재 session은 독립 실행의 claim cap을 소비하므로 준비를 앞에 추가하면서 전체 cap을 늘려서는 안 된다. canonical attempt 재실행 방지는 준비 동작 전부터 적용해야 한다.

최종 회귀: session20 + original process/model port/durable delivery/기존 RX87 step evidence **78passed124.50s**. 전체 suite를 재실행하지 않았으며 기존9개 baseline 실패 해결을 주장하지 않는다. 실제 기기/유료 모델/사람 승인 수용과 분리한다.

Result.artifact_ids는 session의 after/log/source commit ACK IDs다. model before PNG는 model port의 별도 commit/observation으로 이미 ACK돼 있다. MA04c finish consumer는 source/evidence witness가 요구하는 전체 ID 집합을 대조하고 필요하면 before artifact ID도 명시 전달해야 한다.
