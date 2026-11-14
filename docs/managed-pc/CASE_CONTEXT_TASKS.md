# RX87 B2.1 · 고정 case 검증·대상 metadata 공급

Goal: 실제 claim HTTP 응답에 실행 소유의 case version/check/expected/target 정보를 함께 제공한다. B2.2 worker 소비·선택 앱 launch·검사 단계 매핑과 C/D는 별도이며, 공급만으로 검증/앱 제어가 완료되지 않는다.

Files: 새 recording/case_context.py(immutable version에서 metadata 조회/정규 JSON hash), api/worker.py(claim DTO 필드), tests/integration/test_rx87_case_context.py. 기존 승인/package/원본/finish digest/schema migration을 바꾸지 않는다.

- [x] 실제 정상 API recording claim에서 case_context 누락을 RED로 확인한다. 현재 입력 version의 goal/check/expected만 쓰며 최신 draft를 조회하지 않는다.
- [x] load_case_context(connection, receipt) -> dict|None. project/job/attempt/generation으로 현재 receipt 소유를 확인하고 recording.input_case_version_id 또는 trial/regression case_run.case_version_id에 정확히 join한다. immutable version의 source hash·검사·path/대상, claim package id/hash, scope를 case-context-v1과 context_hash로 전달한다. resource_probe/app_install은 None이다.
- [x] context는 current 실행 허가가 아니다. HTTPS claim source와 고정 version/owner에 묶인 metadata이며 기존 lease/checkpoint가 별도 권한이다. main claim/finish digest를 임의 변경하지 않는다. secret_refs는 참조만, raw secret/settings 전체·키 값·모델 호출0이다. Android package 문자열도 아직 shell/driver에 전달하지 않는다.
- [x] 같은 claim 재조회·다른 최신 draft·서로 다른 owner/version·입력 위조가 원래 context를 바꾸지 않는지 확인한다. replay query는 ITEM version이며 recording 원본을 잘못 소비하지 않는다. target/check metadata를 이후 worker가 소비해야 한다는 한계를 명시한다.
- [x] fresh review→필수 수정1회→집중/전체 기존 baseline 비교→인계/큐/master commit. B1 full과 I/O 파일을 건드리지 않고 공급 helper부터 준비한다.

Review focus: latest draft/다른 project 또는 owner join, JSON alias/secret plaintext 유출, replay package와 version 불일치, old receipt의 metadata 변동, case_context 자체를 실행 권한으로 오해하는 소비자. worker consume/step mapping 미구현을 숨기지 않는다.

완료2026-11-14(core_contract/supplier): [인계](../validation/tasks/RX-87-B2-CONTEXT.md). 새14·집중80·JS32·전체 기존9failed879passed1skipped. 다음 [worker 소비](CASE_CONTEXT_CONSUMER_TASKS.md).
