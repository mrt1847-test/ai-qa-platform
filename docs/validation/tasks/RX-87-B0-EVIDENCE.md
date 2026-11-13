# RX87 B0.4 · 증거 ACK 복구 인계

- 상태: complete(core_contract), 기준 mastere393efb. 2026-11-14. 실제 모델 API/AVD/배포/설치 없음. C00/C04/C05/C08/C14.
- StepEvidenceCommitter는 runtime의 현재 attempt/step writer다. 같은 key의 events/artifacts·최초 now를 고정하고 SHA256 body fingerprint로 바뀐 입력을409로 거절한다. ACK된 단계는 작은 receipt/hash만 보관하고 PNG payload를 해제한다. 하나의 pending 단계만 허용하며 미확인 prefix를 건너뛰지 않는다.
- timeout/명시 transient 오류만 같은 key/본문으로 추가1회 확인한다. auth/TLS/409/422/429는 반복하지 않는다. device/model/attempt는 재시작하지 않는다. 매 HTTP 재전송의 body/time/키가 같다. 현재 control/lease 권한은 checkpoint/keeper가 따로 확인하며 cache된 ACK를 다음 동작 허가로 쓰지 않는다.
- ACK attempt/lateFalse/int contiguous prefix·hash·artifact UUID 수를 검사한다. ACK copy의 외부 변이는 내부 cache에 영향을 주지 않는다. source commit에서도 앞 prefix를 잃지 않는다. 재시도는 증거 저장 확인뿐이며 실제 vendor model quota를 추가 소비하지 않는다.
- TDD: 실제 API/정제 PNG에서 helper 재확인409와 commit 후 ReadTimeout을 RED2로 확인했다. 원래 native1 이후 prefix 유실로 error였던 녹화가 동일 저장 receipt를 받아 click→finish를 완료한다. native1·local author2·실제 provider0·events2가 유지된다. 추가15 guard 테스트는 비재시도 오류/횟수2·입력/ACK 변조·pending 제외·receipt alias를 검증한다. 신규17건과 관련 집중27passed(21.22s), 확대39passed(7.33s).
- RX33 기존 MockTransport가 job_id를 attempt_id로 반환하고 source upload에서 prefix를0으로 되돌리던 부분을 실제 계약에 맞게 보완했다. ACK 전 actor0/ACK 실패0/정상 action1 기대를 유지했으며 실제 gate를 완화하지 않았다.
- 별도 리뷰 Critical/Important/Minor 없음. 실제 환경·전체 회귀·기존 API evidence clock/I/O는 판단 유보로 남겼다. 이 카드로 증거 API의 동기 파일 I/O/worker-time 권한까지 해결했다고 보고하지 않는다.
- 최초 전체10failed818passed1skipped(401.64s)의 추가1은 기존 artifact 동시 쓰기 테스트 barrier다. 제품 artifacts/files 코드는 변경하지 않았다. 전역 os.fsync hook이 다른 durability 작업까지 barrier에 참여시키는 경로를 별도 RED로 확인한 뒤 artifact 모듈에만 hook을 한정했다. 두 writer의 동일 bytes/독립 temp/정리 assertion을 유지하고 양쪽 future 오류를 수집한다. 원 간헐 실패의 외부 fsync 발생원까지 확인한 것은 아니다. 최종 전체9failed819passed1skipped(378.07s), 기존9 node와 정확히 같으며 전체 green은 아니다. 로그 .review-work/step-evidence-retry/final-full.log.
- 판단: evidence-only 추가 HTTP1회로 ACK 유실을 확인한다(전송 횟수/지연이 최대1회 늘어남). 큰 payload는 한 pending만 보관하고 ACK 후 해제한다(프로세스 재시작으로 과거 실행을 자동 재개하지 않음). cache된 저장 receipt와 실행 권한은 분리한다(다음 action에는 fresh checkpoint 필요). 테스트의 global OS monkeypatch를 모듈 단위로 좁힌다(외부 durability 동작을 이 barrier로 관찰하지 않음).
- 다음 B0.5: 기존 evidence API의 worker now 기반 lease/late 판정과 token-purpose 불일치를 실제 API에서 RED2로 재현했다. 서버 transaction 시각·job purpose를 기준으로 보완하고 기존 receipt 재조회는 유지한다. 기존 ASGI/DB writer 중 파일 I/O는 별도 B0.6이며 외부 환경 대기가 아니다. B/C/D 및 replay/Web·target도 미완료다.
