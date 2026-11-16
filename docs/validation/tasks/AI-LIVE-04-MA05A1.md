# AI-LIVE-04-MA05A1 · 실패 녹화 저장·종료 상태

2026-11-17 Asia/Seoul. BASE820f2d4, original master. MA05a 중 서버 저장 상태만 분리했으며 RX87 전체 완료 수는 유지한다. 실제 upstream main + public auth/inventory/browser REC/true claim/runtime/finish/cleanup + 모의 OpenAI/ADB/app launch. 유료 모델/실기기 호출0.

## 구현·계약

- `recording.service.finish_incomplete_recording`은 인증된 attempt finish의 lease/owner/cursor 검사 뒤 같은 transaction에서 호출한다. REC만 stopped/error 또는 interrupted/stored/incomplete로 저장하며 case 승인/버전 pointer를 바꾸지 않는다. 여기서 stored는 서버 prefix 보관이며 누락된 증거를 완전하다고 주장하지 않는다. manifest/version/package/approval 생성0.
- 사용자 cancellation receipt를 먼저 확인해 일반 handler error로 돌아와도 interrupted로 남긴다. lost도 interrupted다. 기존 terminal REC 상태는 보존한다.
- `store.queue.finish_worker_attempt`은 첫 finish receipt를 불변으로 두고 같은 key/body만 재확인한다. 아직 lease가 살아 있어도 새 key로 completed를 제출하면409다. 성공 source 검증은 유지한다.
- `recording.service._seal`은 기존 same-key manifest receipt 조회 후 terminal 상태를 검사한다. 별도 browser stop/finish로 실패본에 complete source/draft를 만드는 경로도409다.
- 기존 recording page/timeline/artifact endpoint는 PC offline에서도 서버 ACK before PNG를 그대로 조회한다. 새 UI/디바이스 포트는 추가하지 않았다.

## 검증·검토

새 genuine API/runtime 상태6개 RED 뒤 초기 관련30pass. 추가 검증에서 active-lease new-key 성공 덮기 RED, actual cancellation CAS와 receipt 재확인을 확인했다. 한 fresh reviewer의 Important1(browser 재seal)을 public stop/finish RED2로 재현해 한 번의 보완 pass로 차단했다. timeline은200뿐 아니라 ma-action의 실제 before=stored를 검사한다. 최종 관련 명령/결과는 아래에 기록한다.

## 제한·다음

MA05a2의 ma-action planned/acknowledged/unknown 구분과 typed failure log는 미구현이다. 현재 before/proposal만 저장된 action이 observed로 보이는 gap은 다음 구현 대상으로 유지한다. 실패본에는 replay 후보가 없으므로 사람 승인이나 QA PASS 수용으로 계산하지 않는다. 실제 PC 전원 종료/과금/독립 호스트 수용은 별도다. generated metadata-load.md는 보존하며 이 변경에 포함하지 않는다.

최종 검증: `.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma05_failure_state.py tests/integration/test_ma04_mobile_runtime_handler.py tests/integration/test_ma04_engine_authority.py tests/integration/test_rx_38.py tests/integration/test_rx_73.py tests/integration/test_w16.py -q -p no:cacheprovider --tb=short` → **64 passed82.43s**. 전체 suite 재실행/전체 green 주장이 아니며 기존6개 회귀 실패는 기존 기준선을 따른다.
