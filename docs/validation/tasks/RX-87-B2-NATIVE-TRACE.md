# RX87 B2.3b0 · Android 원본 동작 보존/정확 재생

2026-11-15, 기준 master c4b62ed. 새 기록의 native v2 codec/producer/compiler/claim witness/worker 소비를 구현했다. 기존 text 상수·Enter 누락·swipe 시간/방향 추정·physical 이중 rescale을 보완했다. 상위RX87/B2.3b logical mapping/UI/실 hierarchy·정규화 결과/C/D는 미완료다.

## 저장과 소비

- 모든 typed native param과 geometry를 strict/frozen tuple로 roundtrip한다. bool/NaN/extra/중복 JSON key/ID·count·bounds/unused 값은 거절한다. 한 동작이라도 trace에서 빠지면 completed source를 만들지 않는다. v2 표식이 남아 있으면 legacy로 강등하지 않는다. v1 저장 bytes를 바꾸지 않는다.
- v2 source count/final_seq와 ACK source artifact의 REC/project/recording job/attempt/generation/hash/length/media/role를 대조한다. 모델/이미지와 실제 native 동작 전체 일치에 대한 제품 assertion을 뜻하지는 않는다.
- package hash에 source manifest hash/raw mapping hash/physical plan hash/compiler+lock/step mapping hash가 들어간다. 정상 공급자는 witness와 별도 hash 고정 case_context.replay_compiler_ref를 보낸다. worker는 witness를 재compile하고 표시 plan/owner/hash를 대조한다. v2 witness/plan 누락은 실행 전 거절한다.
- capture 원본의 정제/전체 geometry를 먼저 검사한 뒤 physical identity frame으로 바꾸므로 model dims가 달라도 실제 기록 argv와 재생 argv가 같다. 다른 physical size/rotation은 stored gesture0이다. 앱 준비1회는 선행될 수 있다. actor AI는 재생0이다.

## 검증과 판단

Codec 부재RED8→GREEN8, producer/compiler/missing witnessRED3→GREEN, 실제 Store supplierRED1→GREEN, exact native replayRED2/geometry negativeRED2→GREEN. count/duplicateJSON/boolboundsRED3→GREEN. 초기 집중76passed46.74s. 이전 전체9failed1014passed1skipped495.35s는 실패 node9가 check-coverage full과 일치했으며 신규 실패0이었다. JS32passed207ms. 이것은 리뷰 수정 전 결과이며 전체 green은 아니다.

첫 reviewer는 사용량 제한으로 결과를 내지 못했다. 재개 후 native+OpenAI smoke를 묶어 fresh review1회 완료, Important6/Minor1. Minor UUID 정수의 AttributeError는 정상 finish가 없는 handler 탈출이므로 Important로 재분류해 같은 수정 배치에 포함했다. downgrade/witness/compiler/원본 geometry/source ACK 결합 및 smoke source hash/native ACK/부분 message 응답을 RED12로 재현하고 한 수정 배치로 해결했다. 최종 집중102passed57.24s(실제 API claim/녹화/trial/승인/회귀 RX71/RX77 포함). fixture source의 immutable ready metadata를 UPDATE하려다 검사1실패가 있었으며, INSERT 시점에 정확한 source metadata를 만드는 선택 파라미터로 fixture를 고쳤다. 불변 trigger는 유지했다. 재리뷰·추가 유료 모델 호출·전체 무변경 검사 반복은 하지 않았다. 후속 context/admission 회귀 결과는 같은 작업 로그에 기록한다.

Rulings: source 직렬화부터 고친 이유는 logical binding이 잘못된 native 위치에 연결되지 않게 하기 위해서다(비용: binding/UI 일정 지연). legacy v1은 손실값을 복구하지 못하므로 재녹화가 필요할 수 있다. RX77의2,5/5,10 expected는 잘못된 이중 rescale을 고정한 값이어서 원본25,50/50,100으로 바꾸고 별도 exact argv 검사를 추가했다. 기존 전체9개 결함은 이번에 해결했다고 하지 않으며, 관련 집중 검사와 이미 확보한 전체 기준선을 구분한다. 실제 모델 최초 단일 동작은 AI-LIVE-01 별도 인계이며 제품 전체 수용을 대체하지 않는다. 리뷰의 나머지 보류는 정상 OpenAI 공급자 연결/자율 다단계/logic binding/실제 검사·정규화 저장/실기기 전체 수용이다. 미룬 Minor 없음.

다음 B2.3b: 저장 원본의 native action ID에 logical step 검증 시점을 명시 연결하고, 원본 승인/FAIL을 바꾸지 않는 새 후보/검토 UI·저장·정규화 결과를 구현한다. 정상 OpenAI provider factory/비밀 참조/admission/계측 연결도 실제 시험의 후속이다. 사용자 metadata-load.md는 수동 복원/커밋하지 않는다. 로그 .review-work/native-trace/{focus,full,js}.log 및 .review-work/openai-smoke/{review-red,review-green,verified-focus,context-regression}.log.

추가 영향 검증: 고정 case metadata·recording pin·모델 admission·observation 관련 회귀99passed81.80s. 이번 변경 뒤 전체 재실행은 하지 않았으므로 전체 결과는 앞 baseline과 구분한다.
