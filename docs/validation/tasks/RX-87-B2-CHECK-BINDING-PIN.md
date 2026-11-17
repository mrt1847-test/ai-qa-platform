# RX87 B2.3b3a · exact package의 검증 연결 워커 pin

- 상태: complete (metadata 공급·검증 범위). BASE master ed8da99; 완료 revision은 이 파일을 포함한 로컬 커밋이다.
- 계약: C04/C05/C06/C14, CHECK_BINDING_RUNTIME_TASKS b3a. 선행 B2-CHECK-BINDINGS/native trace 및 MA05B13. DB migration/UI 변경 없음.
- 등급: 임시 DB/public execution preview·trial enqueue·worker claim API + 모의 native/관찰. 실제 모델/ADB/유료 API/승인 이벤트0. 실제 원본 전체 수용/validator 완료로 세지 않는다.

## 제공 interface

recording.check_bindings.load_runtime_check_binding_pin(connection,project,package_id)는 해당 package.source_manifest_id의 immutable annotation만 읽는다. 같은 녹화의 최신 head로 fallback하지 않는다. recording.case_context.load_case_context가 exact ITEM 버전/package의 case-context-v1에 optional check_bindings를 넣고 context_hash에 포함한다. annotation 없는 구 source/recording/Web는 새 데이터를 받지 않는다.

recording-check-binding-pin-v1: recording_id, manifest_id/hash, source_manifest_id/hash, input_case_version_id, source_content_hash, binding_hash, bindings(step_boundaries/check_targets). 예상값/native text literal/secret/model grant를 복사하지 않는다. candidate 버전 ID는 입력 버전과 다르지만 source content hash는 materialized 복사 원본과 일치해야 한다.

worker.check_binding_pin.resolve_claim_check_binding_pin(claim,case_context=...,native_source=...)는 Android replay/원본 native compiler·UUID·shape·source step/check/native IDs/순서·선택 package resource·binding hash·derived manifest hash·source content identity를 확인한다. resolved NativeSource가 이제 verified manifest_id/hash도 frozen으로 보존하므로 해석 후 raw claim을 바꿔 다른 annotation을 섞을 수 없다. 새 WorkerCheckBindingPin은 manifest_id/binding_hash/불변 boundaries/targets tuples다. 모델/승인/검증 PASS 권한이 아니다.

AndroidReplayHandler는 native source 해석 직후, 기기 준비/캡처/명령 전에 pin을 확인한다. 잘못된 supplied metadata는 check_bindings_invalid(더 이른 context/native 오류는 기존 reason)로 종료한다. 다음 claim 시작 시 pin·통계를 초기화한다. valid pin만으로 기존 required unknown을 PASS로 바꾸지 않으며 실제 평가/normalized 결과는 b3b/c다. Web/recording 컨텍스트는 Android annotation을 거절한다.

저장·투영·worker는 동일한 compact ensure_ascii=False UTF8 document131072-byte 한도를 쓴다. envelope 크기나 JSON escaping/whitespace 차이로 유효한 저장본을 거절하지 않는다. 기존 DB의 escaped JSON은 별도6배 decode 길이 guard 뒤 같은 논리 문서 한도로 검사한다. wire POST body128KiB 제한은 별도 기존 방어다.

## 검증·검토

초기 missing-interface RED2→12pass5.63s, 영향124pass55.39s. fresh review는 앞선 주기 quota로 실행이 끝나지 않아 완료로 세지 않았고, 새14:07 KST 예약 주기에서 같은 reviewer가 정상 재개했다. Important3(raw witness 치환/크기 단위/Web 수용)을 RED4로 재현해 한 수정 배치로 보완했다. Minor actual claim coverage도 public API의 미승인 annotation trial 접수→claim→worker 해석1pass로 보완했다. 같은 pass의 source content identity RED1도 보완했으며 re-review 없음.

near-limit ASCII/Unicode의 저장·투영 및 envelope/escaping 회귀, 합법 개별 ID 조합의 총 문서 초과 거절, old package 불변·foreign project·잘못된 pin side effect0·실제 저장 native5개 AI0 replay/필수unknown·재사용 초기화를 포함한다.

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_check_binding_pin.py tests/integration/test_rx87_case_context.py tests/integration/test_rx87_case_context_consumer.py tests/integration/test_rx87_native_trace.py tests/integration/test_rx87_check_bindings.py tests/unit/test_recording_check_bindings.py -q -p no:cacheprovider --tb=short
```

최종 **144 passed52.20s**. 실제 claim의 source는 기존 deterministic source DB fixture이며 실제 Mobile-Agent 전체 녹화/승인·실기기 QA 증거가 아니다. 테스트 수를 실제 앱 TC로 세지 않는다. 기존 전체6개 기준선/완료87/99·49/53·RX87 미완료를 유지한다.

## 다음

b3b에서 actual Android hierarchy 관찰과 binding 경계별 deterministic 검증을 연결하고 c가 check_results/ITEM에 정규화 저장한다. 현재 필수 검증은 평가되지 않으면 unknown이다. 이후 MA05b2 원본 저장본 사후 승인→동일 package AI0 여정을 재개한다. 운영 키/독립 호스트를 이 구현의 선행으로 요구하지 않는다. metadata-load.md는 기존 dirty 보고서로 보존·커밋 제외했다.
