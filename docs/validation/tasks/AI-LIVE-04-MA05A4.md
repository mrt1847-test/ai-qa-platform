# AI-LIVE-04-MA05A4 · worker finish 없는 서버 녹화 종료

2026-11-17 Asia/Seoul, BASE7c9d0fb original master. 정상 browser/worker API·임시 DB·fake clock로 검증했다. 실제 모델/ADB/PC 전원 조작0. 전체 RX87·87/99·49/53는 유지한다.

## 구현

`store.queue._finish_abandoned_recording`은 해당 project/job의 recording 목적·recording ID·일치하는 terminal job status를 확인하고 a1의 incomplete-only 저장 helper를 호출한다. reconcile_stored가 lost로 만든 경우와 cancel_job이 queued→cancelled로 바꾼 경우만 같은 transaction에서 실행한다. REC는 stopped/interrupted/stored/incomplete이며 manifest/version/package/approval을 만들지 않는다. stopped는 서버의 새 녹화 접수 종료이고 실제 기기 정리 증거가 아니다. 손실 자원의 quarantine/no-resume은 그대로다.

queued/live generation 보존, 다른 REC·기존 terminal REC·case 승인/버전 pointer·trial/regression QA는 바꾸지 않는다. 반복 reconcile/취소 receipt 재확인은 불변이다. 늦은 worker error finish는 ACK facts만 확인하고 이미 interrupted인 녹화를 error나 새 source로 바꾸지 않는다. 서버 ACK PNG는 PC offline에서도 조회한다.

## 검증·검토

새 public-API 테스트5개 RED: queued 취소·lease 만료·watchdog 만료·PC offline·session 변경 모두 job 종료 후 REC가 open/running/local이었다. 수정 뒤 a4/a1/RX01/RX38 **20pass27.08s**. 한 fresh reviewer Critical/Important0, 추가 review pass 없음.

최종 관련: `test_ma05_server_stop.py`, `test_ma05_failure_state.py`, `test_rx_01.py`, `test_rx_38.py`, `test_rx_73.py`, `test_w09.py`, W08_01/02/04/05 → **30 passed30.58s**. W08_03 등 기존6개 전체 회귀 실패는 기존 기준선에 남기고 전체 green으로 표시하지 않는다. 실제 전원 종료/독립 호스트 수용은 아니다.

## 다음

MA05b1: 실패본의 검토 링크가 다른 최신/승인 후보를 가리키는 UI를 수정한다. 해당 녹화의 timeline/log와 재녹화 경로를 제공하고 완전 저장 후보는 정확한 version으로 검토한다. MA05b 전체 사후 승인/AI0 실행은 별도 검증이며 완료로 계산하지 않는다.
