# 뼈대 우선·차단 독립 진행 · v0.8

> 아래는 원래 W163개 설계의 변경 이력이다. 최신 Android 에뮬레이터 개발/누락 UI 작업은 [보완 카드](11-development-follow-ups.md)를 별도로 따르며 USB/양 플랫폼 live gate를 대신하지 않는다. 현재 완료 수와 실행 순서는 NEXT_ACTION/WORK_PROGRESS를 따른다.

기준일: 2026-10-31. [Current 큐](../../NEXT_ACTION.md) · [뼈대4개](00-bootstrap.md) · [공통 계약 C13/C14](CONTRACTS.md).
이 개정은 문서 변경이다. 기존 probe code/완료·차단 인계는 수정하지 않았다.

## 1. 보존한 실제 상태

- W01-01은 [기존 인계](../validation/tasks/W01-01.md)의 complete를 유지한다. 원본 조사를 다시 만들지 않는다.
- W01-02는 [기존 차단 인계](../validation/tasks/W01-02.md)와 [환경 기록](../validation/web-isolation.md)을 보존한다. VM이 없는 실제 환경을 준비된 것으로 바꾸지 않는다.
- 패키지/probe/test 코드가 이미 일부 있으므로 W00은 재사용·최소 확장한다. 기존 파일을 빈 scaffold로 덮지 않는다.
- 추가 작업: W00-01–04(최소 실행 기반)와 W31-07(이전 healing 카드의 실제 수용 분리).
- 전체는 **33개 W / 163개 leaf / 15개 영역 문서**, 기존 완료는 **1개**다. 분모만 조정하고 완료를 새로 만들지 않는다.

## 2. 실행 경로

`W00-01 → W00-02 → W00-03 → W00-04 → W04-01`부터 진행한다.
DB/버전/schema→queue/control→관리 UI/data→증거 저장/정책→review/preview/분석/보관의 core 계약은 VM 부재와 독립이다.
engine capture·실제 replay·trial·healing/회귀·실제 비용·MVP 최종 gate는 필요한 환경이 갖춰진 뒤 통과한다.

차단이면 NEXT_ACTION 외부 대기에 ID/원인/조건/evidence를 남기고 준비된 독립 후보를 Current로 옮긴다.
가까운 Next가 전부 막혀도 전체 TASK_INDEX의 준비 후보를 검사한다.
조건을 만족하는 후보가 없을 때만 대기한다. 낮은 번호를 무조건 기다리거나 blocked를 완료로 바꾸지 않는다.

## 3. 직접 선행 수정 내역

모든 변경은 완료 기록을 되돌리는 것이 아니라 아직 미완료인 consumer의 진짜 계약 의존을 명시한 것이다.
W01-01의 완료/source 인계와 W01-02의 차단 사실은 그대로다.

| 작업 | 이전 직접 선행 | 수정 직접 선행 | 현재 검증 등급 |
|---|---|---|---|
| W01-02 | W01-01 | W01-01, W00-04 | live_integration |
| W03-02 | W03-01 | W03-01, W00-01 | adoption_gate |
| W04-01 | W03-03 | W00-04 | core_contract |
| W07-02 | W07-01 | W07-01, W01-02 | live_integration |
| W07-03 | W07-02 | W07-01, W02-04 | live_integration |
| W07-04 | W07-03 | W07-02, W07-03, W09-03 | live_integration |
| W08-01 | W07-04 | W06-09, W00-04 | core_contract |
| W10-01 | W09-04 | W06-09, W04-03, W00-03 | core_contract |
| W11-01 | W10-10 | W10-10, W07-01, W14-03 | core_contract |
| W11-04 | W11-03 | W11-03, W07-03 | live_integration |
| W11-05 | W11-04 | W11-03, W14-03 | tool_integration |
| W11-06 | W11-05 | W11-04, W11-05, W07-03 | live_integration |
| W11-07 | W11-06 | W11-01, W09-03, W08-05 | core_contract |
| W11-08 | W11-07 | W11-07, W10-09 | core_contract |
| W12-01 | W11-08 | W11-08, W00-04 | core_contract |
| W13-01 | W12-03 | W06-09, W04-03 | core_contract |
| W14-01 | W13-04 | W06-09 | core_contract |
| W15-01 | W14-04 | W06-09, W04-04, W08-01 | core_contract |
| W15-04 | W15-03 | W15-03, W03-01 | live_integration |
| W16-01 | W15-04 | W10-11, W11-03, W08-01 | core_contract |
| W16-02 | W16-01 | W16-01, W15-04 | live_integration |
| W16-03 | W16-02 | W16-01, W15-03, W08-05 | core_contract |
| W16-04 | W16-03 | W16-03, W01-03, W02-04, W07-02, W07-03, W13-04, W15-04, W14-03 | live_integration |
| W16-05 | W16-04 | W16-03, W14-03, W13-04 | core_contract |
| W16-07 | W16-06, W29-06, W30-04 | W16-06, W29-06, W30-04, W16-04 | live_integration |
| W29-01 | W16-05 | W16-05, W06-09 | core_contract |
| W29-02 | W29-01 | W29-01, W01-01 | core_contract |
| W29-03 | W29-02 | W29-02, W07-02, W01-02, W13-04 | live_integration |
| W29-04 | W29-03 | W29-02, W14-03 | core_contract |
| W29-06 | W29-05, W10-08 | W29-04, W10-08 | core_contract |
| W30-01 | W29-04, W16-05 | W29-04, W16-05, W06-09 | core_contract |
| W30-03 | W30-02 | W30-02, W07-03, W13-04 | live_integration |
| W17-01 | W16-07, W16-08 | W29-04, W08-05, W15-03, W16-03 | core_contract |
| W17-02 | W17-01 | W17-01, W13-01 | core_contract |
| W17-03 | W17-02 | W17-02, W15-03 | core_contract |
| W17-04 | W17-03 | W17-03, W16-07, W29-05, W30-03 | live_integration |
| W18-01 | W17-04 | W17-03, W29-04, W14-03 | core_contract |
| W19-04 | W19-03 | W19-03, W16-08, W16-04, W17-04 | live_integration |
| W31-01 | W19-04 | W19-01, W15-03, W13-03 | core_contract |
| W31-05 | W31-04 | W31-04, W16-08 | core_contract |
| W20-01 | W31-06 | W17-01, W19-01, W31-01, W29-04 | core_contract |
| W22-04 | W22-03 | W22-03, W17-04, W19-04, W31-07 | live_integration |
| W23-02 | W23-01, W18-02, W22-04 | W23-01, W18-02, W20-04 | core_contract |
| W27-01 | W26-05 | W26-05, W22-04 | live_integration |
| W27-04 | W27-03 | W26-05, W24-05, W06-09 | core_contract |
| W32-01 | W27-04 | W24-05, W15-03 | core_contract |
| W32-02 | W32-01 | W32-01, W22-04, W31-07, W27-03, W27-04 | live_integration |
| W28-01 | W32-03 | W32-03, W03-03, W07-04, W12-03, W16-07, W27-03, W31-07 | final_gate |

## 4. 실제 환경 검증의 보존

- core 카드의 자동 검사는 실제 backend/DB/파일/화면에서 수행하고, 외부 관찰만 명시 test fixture로 제공한다.
- actual engine/모델의 준비·실행·품질은 카드의 live_acceptance_tasks에서 입증한다. fixture 성공을 native evidence로 기록하지 않는다.
- production adapter 없음은 명시 차단/불명이며 fake 성공 adapter를 기본 경로에 연결하지 않는다.
- 원래 UI21/DATA22/실행10 조건은 그대로다. 특히 healing 실제 조건은 W31-07을 추가로 연결한다.
- 부모 W는 필요한 parent_gate_tasks와 원래 상위 조건까지 충족해야 완료다. 필수 integration의 blocked 상태는 전체 MVP 완료를 막는다.

## 5. 문서 검사 항목

전체 ID/카드/상태·직접 선행·순환 없음·부모 gate·링크/예시/진행률을 대조한다.
추가로 VM/USB/model/APK 도구가 모두 없다고 가정한 DAG 진행 시뮬레이션에서 bootstrap/DB/queue/관리 UI/리포트/보관의 독립 core 경로가 열리는지 검사한다.
이 시뮬레이션은 **계획상 접근 가능성**이며 실제163개 구현/시험 PASS가 아니다.
기존 src/tests/patches/원본 SOURCE와 두 인계는 개정 전후 hash가 같아야 한다.
