# 문서 검증 기록 · v0.8

> 아래는 2026-10-31 계획 정적 검증의 역사적 기록이다. 현재 구현과 2026-11-01 제품 보완 검증은 [최신 결과](../validation/reviews/2026-11-01-remediation-result.md)를 따른다. 정적 검증의 Current/complete 수를 현재 실행 상태로 사용하지 않는다.

기준일: 2026-10-31. [기계 검사 결과](VALIDATION_RESULT.json) · [선행/차단 수정](SCHEDULING.md) · [검토36건](REVIEW.md).

## 검사 범위

| 항목 | 이번 개정 기준 |
|---|---|
| 작업 | 33W·163leaf·15영역, 기존 complete1/blocked1 보존 |
| Current | W00-01, 다음 후보8개 |
| 최소 기반 | package/lock/pytest→API/settings→template/static→실제 HTTP 시작/종료 |
| 선행 | 직접 의존48개 교정, ID/순환/카드·색인 대조 |
| 차단 독립성 | VM/USB/model/APK 도구 부재를 가정해 독립 core 경로의 계획상 도달성 검사 |
| 완료 의미 | core_contract와 live/final·parent_gate_tasks를 구별 |
| 요구/시나리오 | R35(P0 32/P1 3)·UI94·UI21/DATA22/실행10 원문·담당 유지 |
| 새 live gate | W31-07, 기존 치유의 실제 조건 보존 |
| 기존 산출물 | src/tests/patches/원본 SOURCE·두 인계의 개정 전후 hash 대조 |
| 문서 형식 | local file/anchor·fence·JSON/Python 예시·공백/인코딩 검사 |

정적 검사의 오류/개수/위상 순서와 독립성 시뮬레이션 결과는 JSON에 기록한다.
시뮬레이션은 앞으로 core 구현/검사를 통과한다고 가정한 **계획상 도달성**이다. 지금125개 구현이 끝났거나 즉시 실행 가능하다는 뜻이 아니다.
core의 실제 API/DB/파일 검증도 아직 대부분 미실행이며 기존 W01-01 외의 완료를 만들지 않았다.

## 실제 상태 보존

W01-01 source 조사 complete와 W01-02 VM 부재 blocked는 실제 기존 인계/색인에 따라 보존한다.
오래된 큐의0완료 표시를 그대로 적용해 완료 작업을 다시 만들지 않는다.
새 W00/치유 통합 gate는 미착수다. 차단된 integration과 최종 MVP 수용은 core 진척으로 통과하지 않는다.

## 이번 변경에서 실행하지 않은 것

제품 코드 작성·의존성 설치·서버 시작·DB migration·기기/VM/model 실행·배포는 하지 않는다.
미래 카드의 pytest 명령과 bootstrap 설치/CLI는 구현 때의 기준이다.
실제 검증은 각 작업의 지정 scope/인계에서 수행한다. 기존 코드/검사 파일을 삭제하거나 false PASS로 바꾸지 않는다.

## 후속 변경

카드/TASK_INDEX/인계/진행률/Current를 함께 갱신한다.
외부 차단은 대기에 남기고 준비된 독립 후보를 선택하며, 진짜 선행·live gate·QA/원본 불변식은 지운 적이 없다.
최종 출시는 원래 UI/DB/정확성/격리/비용 시나리오와 필수 실제 근거까지 모두 충족해야 한다.
