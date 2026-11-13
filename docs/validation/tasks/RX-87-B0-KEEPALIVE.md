# RX87 B0.3 · 녹화 제어 세션 인계

- 상태: complete(core_contract), Android recording 범위. 기준 master9e0293a, 2026-11-14. replay/Web lifecycle과 B/C/D·선택 앱 준비는 미완료다. 실제 모델 API/AVD/배포/설치 없음.
- WorkerAttemptKeepalive는 10초 간격 heartbeat→fresh checkpoint→같은 job/generation renew만 수행한다. model/device 호출0, action/model quota 차감0이다. 실제 관리 API·DB와 제어된 서버 시각으로 최초45초 임대 이후60초까지 유지되는 것을 검증했다. 취소 확인 뒤 새 갱신0, 전송 실패는 현재 session에 latch하며 연결 복구로 재개하지 않는다.
- foreground와 background 모두 실패를 확인하면 현재 세션의 새 작업을 차단한다. 이미 전송된 HTTP는 소급 취소하지 못하므로 완료/종료를 기다린다. close 기본15초 안에 제어 thread join을 확인하지 못하면 worker가 새 claim을 중단하고 finish/cleanup/release proof를 전송하지 않는다. 과거 attempt 자동 재개0이다.
- runtime은 ACK 뒤 Android recording handler가 있을 때만 keeper를 시작한다. handler 반환/예외 뒤 제어 세션을 닫고, 성공 종료 확인 후에만 evidence/finish/cleanup을 처리한다. 세션 실패 때 completed 녹화는 error/evidence incomplete/review false/mapping{}로 바꾸며 저장된 증거는 보존한다. 다른 job/replay/Web에 recording controller를 잘못 시작하지 않는다.
- 0동작 finish의 빈 last_ack_hash 때문에 오류 종료도422가 되는 문제를 실제 서버에서 재현했다. final_seq=last_ack_seq=0이고 hash가 빈 경우만 canonical empty prefix로 표현한다. 서버의 실제 prefix 비교는 그대로이며 nonzero evidence gap은 거절된다. finish receipt는 테스트 PASS/승인이 아니다.
- HTTPX0.28.1의 설치된 Client 원문 docstring에서 thread 공유 지원을 확인했다. controller는 worker DB에 접근하지 않는다.
- 새13건: standalone6·runtime4·리뷰 interleaving3. missing-module/foreground latch/runtime lifecycle/빈 prefix422/동시 실패 RED 후 수정했다. 집중37passed(36.53s), 최종 전체9failed802passed1skipped(442.69s), 기존9 node와 정확히 같다. 전체 green은 아니다. 로그 .review-work/attempt-keepalive/final-full.log.
- 별도 리뷰 Important1: foreground 실패와 background heartbeat/checkpoint 경합에서 실패 후 renew가 한 번 더 시작될 수 있었다. heartbeat/checkpoint/이미 진행 중 renew의3개 순서를 RED→GREEN으로 확인하고 각 I/O 뒤 stop+failed를 다시 검사했다. 새 renew는 차단하며 진행 중이던 renew 뒤에도 성공으로 반환하지 않는다. 수정 후 재리뷰는 하지 않았다. Minor 없음.
- 판단: control 실패를 latch한다(일시적 연결 장애라도 현재 attempt는 명시 새 실행이 필요). 진행 중 HTTP를 소급 취소했다고 주장하지 않고 joined shutdown을 요구한다(종료 지연/실패 때 자원 반환을 중단). transport 실제 취소·AVD/실 모델·replay/Web·target/B/C/D에 대한 리뷰 판단 유보는 미완료로 둔다(실환경 수용 보장 없음).
- 다음 B0.4: 단계별 evidence commit의 같은 key/변경되는 now와 ACK 유실 복구를 실제 코드에서 RED2로 확인했다. 동작/모델을 재실행하지 않는 증거 확인만 보완한다. 상위 RX87은 in_progress다.
