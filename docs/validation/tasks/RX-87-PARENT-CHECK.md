# RX-87 · 상위 체크 대조

- 상태: complete (core_contract). 부모 revision ed719d7. 이 파일을 포함한 커밋이 완료 revision이다.
- 새 실행 코드 없음. 기존 인계와 `android_jobs.py`의 판정 분기를 대조했다.
- 상위 RX-87과 RX-23 실기기 수용은 완료가 아니다.

## 닫은 항목

UI RX-87의 1·3·4·5번과 Android runtime B의 1·2번을 체크했다.

- OFF 반복과 ON pin 전달: [OFF claim](RX-87-CLAIM-OFF.md), [claim runtime](RX-87-CLAIM-RUNTIME.md), [재사용](RX-87-CLAIM-REUSE.md).
- locator만 복구, 검증 실패는 한 번: [D](RX-87-D-HEALING-RECOVERY.md), [OFF claim](RX-87-CLAIM-OFF.md).
- episode 상한, 취소·임대, package/FAIL 유지: [C](RX-87-C-HEALING-EPISODE.md), [취소·임대](RX-87-CLAIM-CANCEL.md).
- OFF0·ON 허용·ON 차단·소진·실패·정리 재사용: 위 claim 인계를 합친 로컬 증명이다. 한 번의 실기기 여정은 아니다.

## 열어 둔 항목

- UI RX-87 2번. handler 재사용과 시계 분리는 증명됐다. replay 모델 호출량이 RX-98 서버 gate와 같다는 증명은 없다.
- Android runtime B 3번. `require_case_context`가 켜진 replay만 서버 check pin을 평가한다. 꺼지면 `_verify_and_heal`이 `context.checks`를 판정에 쓴다.

## 다음

RX-98 호출량 일치와 fixture check 분리를 따로 구현한다. 그 전에 상위 RX-87을 완료로 세지 않는다.
