# AI-LIVE-04-MA04B1 · 녹화 증거 전송 복구

2026-11-16 Asia/Seoul. 원본 master BASE4d5be4e. 실제 모델/기기 호출0. 전체 RX87 및 87/99·49/53 완료 수는 유지한다.

StepEvidenceCommitter에 mobile namespace(80 logical turns+source=81, 기존 step/prepare51 유지)와 선택 pending_path를 추가했다. 정제된 events/artifacts·고정 clock/key·ACK를 atomic write/file lock으로 보존한다. 모델·capture·native 실행은 이 복구 경로에 없다. ACK 응답 유실이나 ACK journal 저장 실패 후 새 committer가 정확히 같은 metadata만 전송하며 cached server ACK와 기존 artifact를 재사용한다. 같은 객체에서도 disk write 실패를 우회해 HTTP를 보내지 않는다.

owner(project/job/attempt/generation/worker/namespace), 최대8MB/81개, 중복 JSON key, full-state checksum, strict numeric type, pending-last/연속 turn·event cursor, artifact 수·ACK scope를 검사한다. checksum은 우발 변경/손상 검출이며 hostile host 인증이 아니다. timezone 없는 clock과 lock acquisition 오류도 전송 전에 거절한다. 서버의 원본 history/native proof 검증을 대체하지 않는다.

검증: 초기 RED6→GREEN6, disk 재시도 RED1 수정. fresh review Important3/Minor1에 대해 RED12→단일 fix pass(재리뷰0). 마지막 회귀는 unit delivery/정상 marked model port+ASGI lost ACK/기존 RX87 evidence/model port **37 passed**. 비어 있지 않은 event prefix도 재시작 후 contiguous_seq=2와 원래 payload/key/time을 유지한다. 모델1회에 총3 artifact(before/after/log), 복구 시 추가 모델0. 실제 유료 API·ADB·사람 승인 수용이나 전체 suite 통과를 뜻하지 않는다.

Ruling: durable state는 정제 증거 metadata와 ACK만 보관한다. 비용: native ACK prefix의 독립 fsync·after capture/source seal은 MA04b2에서 별도로 연결해야 하며 metadata 복구가 녹화를 재개하지 않는다.

변경: worker/step_evidence.py, tests/unit/test_mobile_evidence_delivery.py, tests/integration/test_ma04_mobile_evidence_delivery.py. 상세 작업: MOBILE_AGENT_EVIDENCE_DELIVERY_TASKS.md.

다음: MA04b2 원본 subprocess capture/native coordinator. physical ACK를 after capture 전에 원본/journal에 보존하고 같은 turn after/log ACK 전 다음 모델을 막는다. MA04c runtime/admission 전까지 기존 default는 보존한다.
