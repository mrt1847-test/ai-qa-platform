# RX87 B1 · Android replay의 claim 한도·현재 제어

기존 ANDROID_RUNTIME_TASKS B의 첫 구현 단위다. B0.6 commit 뒤 실행한다. 제품 기대: 승인 plan을 반복하는 gesture의 AI actor0, claim 한도와 현재 서버 fence를 실제 native 전송 직전에 지킨다. 다음 B2 승인 check/expected/target, C/D episode/model/native recovery는 완료로 세지 않는다.

Files: 새 worker/replay_limits.py(고정 caps validation), android_jobs.py(handler·adapter callback 연계·context), adapters/mobile_agent_android.py(replay_step optional native callback), worker/runtime.py(선택 route에만 control binding), tests/integration/test_rx87_replay_control.py.

1. RED: 실제 admitted regression claim의 max_actions를 handler가 소비하지 않음, capture/journal/spool 동안 timeout/cancel 후 gesture 발생, 재사용 guard 누적/고정 시간. 실제 claim은 healing OFF로 서버 재접수 fixture를 쓴다. legacy 개발 fixture는 별도 seam이다.
2. frozen ReplayLimits(max_actions,max_model_calls,timeout_seconds) 반환. caps가 없는 legacy snapshot만 None; 일부 caps/잘못된 type/bool/NaN은 reject. worker 값은 낮추기만 한다. ON pin은 resolve_claim_healing_pin으로 detached 검증. 정상 typed ON은 C 포트 없을 때 명시 healing_runtime_unavailable, fixture 성공을 가장하지 않는다.
3. guard.begin_attempt/reset counter+claim-relative injected/real monotonic. preflight noncharging before_lookup; journal/정제 뒤 실제 native callback에서 fresh checkpoint→최종 시간/취소/guard 차감1. 시작하지 않은 sanitizer/parse/native-boundary 차단을 unknown으로 기록하지 않으며 진짜 native timeout은 unknown/no re-click.
4. Android trial/regression route에만 기존 WorkerAttemptKeepalive 연결. 다른 Web route가 Android recording callback 때문에 잘못 control 대상이 되지 않게 purpose 선택. control close/실패 latch는 기존 runtime 공통 종료를 재사용한다. 정상 runtime API fixture와 legacy replay/check/QA 회귀→one fresh review→필수 RED/GREEN 수정1회→full exact baseline 비교→인계/큐/master commit.

Review focus: 다른 route로 control 바인딩, 시계/guard claim 간 누적, capture/parse/spool/journal/remote wait 사이의 취소, 전송 전 실패와 진짜 native unknown, ON 정책 환경변수 우회/필요 없는 paid actor 호출. max_model_calls는 local cap metadata이며 실제 verifier/healer 서버 quota는 C에서 연결한다.
