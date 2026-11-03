# Next Actions

Updated: **2026-11-03 (Asia/Seoul)** — [중앙 관리·실행 PC 설계](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md)가 현재 배치다. 초기 실행 자원은 현재 PC이며 추가 PC/선택 cloud adapter로 확장한다. 관리 UI/API·DB·증거는 실행 PC와 독립 가동한다. 접속 PC는 웹만 사용하고 등록 실행 PC에는 worker/driver를 준비한다.

실행 PC offline에도 서버에 commit/ACK된 녹화 조회·검토·승인은 가능하다. 재녹화·trial·정식/묶음·재실행·기기 진단은 불가하며 재연결 후 사용자가 명시 실행한다. 필수 증거/기존 OFF trial/승인 불변성은 유지한다. 실제 독립 서버 배포·원격 소비 loop·전원 단절 수용은 아직 미완료다.

기존 W 완료126/163·상위6/33, AD-01 완료는 보존한다. 이 수는 새 분리 배치의 완료율이 아니다. 문서 수정으로 제품 완료를 추가하지 않는다. 실행 순서는 이 파일만 관리한다.

## Current

**RX-01 — 워커 세대와 서버 부팅 분리.** 상태 `not_started`. 독립 대안 RX-02, RX-16, UX-01.

- [RX-01 카드](docs/managed-pc/WORKER_TASKS.md#rx-01)와 직접 선행 [PC-04](docs/validation/tasks/PC-04.md)·[PC-02](docs/validation/tasks/PC-02.md)의 인계를 읽는다.
- worker boot/session을 claim에 저장하고 서버 단독 재기동과 worker 단독 재기동을 각각 검증한다. [RX 색인](docs/managed-pc/IMPLEMENTATION_TASKS.json)과 `docs/validation/tasks/RX-01.md`를 갱신한다.

## Next

| 순서 | ID | 목표 | 직접 선행·환경 |
|---|---|---|---|
| 1 | [RX-02](docs/managed-pc/WORKER_TASKS.md#rx-02) | 실행 PC 등록 코드·인증 범위·폐기 | PC-04/PC-02 · local_python |
| 2 | [RX-03](docs/managed-pc/WORKER_TASKS.md#rx-03) | claim 영수증과 불변 실행 스냅샷 | RX-01/RX-02 · local_python |
| 3 | [RX-04](docs/managed-pc/WORKER_TASKS.md#rx-04) | outbound HTTPS 클라이언트 | RX-02/RX-03 · local_python |
| 4 | [RX-16](docs/managed-pc/SERVER_TASKS.md#rx-16) | 독립 관리 서버 프로필과 HTTPS 경계 | PC-04 · local_python |
| 5 | [UX-01](docs/execution/11-development-follow-ups.md#ux-01) | 묶음·수행·리포트 탐색 복원 | W20-04/W21-01/W23-04 · local_python |

표는 가까운 후보만 유지한다. 이후 워커·엔진·서버·실환경 후보는 [RX 색인](docs/managed-pc/IMPLEMENTATION_TASKS.json)에서 조회한다. UX-02/03의 선행과 범위는 [개발 보완 카드](docs/execution/11-development-follow-ups.md#ux-02)에 있다.

## 외부 대기와 재사용

| 대상 | 상태·재개 조건 | 막히는 범위 |
|---|---|---|
| 독립 관리 서버 | 독립 호스트·DNS/TLS·IdP·배포 권한 확인 시 RX-21 | 실제 배포와 이를 사용하는 통합. core/UI는 진행 |
| Android·모델 키 | [AD-01](docs/validation/tasks/AD-01.md) 전용 emulator 관찰을 재사용. 실제 AVD·키·시험 범위 확인 시 RX-23 | 실제 Android 녹화·재생 수용 |
| Web VM | 지원 VM과 테스트 대상 준비 후 RX-22/24. W01-02/W29-05 기존 이력 보존 | Web 실환경 및 양쪽 전원 종료 수용. Android와 core는 진행 |
| 장애·경합 검증 | 다른 접속 PC, 승인된 전원/통신 단절, 추가 워커와 공유 테스트 자원 준비 시 RX-25~27 | 실제 전원 종료·불명 행동·두 워커 수용 |
| AD-02~04 | 개발 이력으로 보존. 적용 범위는 [구현 경계](docs/managed-pc/RUNTIME_BOUNDARIES.md#카드-선택과-기존-이력)에 매핑 | 자동 선택 제외 |
| CF-01 | `future_optional_provider`, 상용 provider 선택 조사로 이동 | 현재 PC 기반 MVP의 필수 선행 아님 |
| 민감 증거 | 정제 coverage/권한/서버 ACK 없으면 실제 전송·승인 근거 준비 미완료 | 해당 실제 경로만. fixture로 제품 성공을 만들지 않음 |

## 차단되었을 때 다음 작업 선택

1. 현재 범위에서 해결할 결함은 해결한다. 외부 조건이면 ID·원인·재개 조건·영향·인계를 기록하고 소유 색인에 blocked를 남긴다.
2. Next에서 **미완료·blocked 아님·직접 선행 전부 complete+인계 보유·알려진 unavailable 환경 없음**인 독립 후보로 Current를 바꾼다. 완료로 가장하거나 진짜 선행/보안/QA gate를 지우지 않는다.
3. 후보가 없으면 TASK_INDEX(기존 W)·DEV_FOLLOW_UP_INDEX(AD/UX)·PC_EXECUTION_INDEX(전환)·[IMPLEMENTATION_TASKS](docs/managed-pc/IMPLEMENTATION_TASKS.json)(RX)를 ID로 합쳐 요약만 조회한다. managed_execution_mvp/product_shared를 우선한다. 기존 W/AD는 [구현 경계](docs/managed-pc/RUNTIME_BOUNDARIES.md)의 매핑을 따르며 CLOUD_TASK_INDEX의 future_optional_provider는 자동 선택하지 않는다.
4. 후보도 없을 때만 재개 조건을 보고한다. 새 근거/환경 변화가 있을 때만 차단을 재평가한다. 고객 접속 PC 설치나 상용 provider 가입을 우회 필수 조건으로 만들지 않는다.

## 매 실행의 최소 입력과 종료

1. 이 파일→Current 카드→지정 CONTRACTS 절→직접 선행 인계의 interface/검증/제약→관련 코드/저장소 지침만 읽는다.
2. Current 하나를 수행·검증한다. source audit·임시 DB/fixture·실제 PC/배포 수용을 구분하고 UI 변경은 실제 브라우저/키보드·오류·샘플 UI 일관성을 확인한다.
3. `docs/validation/tasks/<ID>.md`에 파일/interface·명령/결과·등급/fixture·제약/재개 조건을 남긴다. [인계 형식](docs/execution/HANDOFF.md#완료-인계-파일)을 따른다.
4. 카드 체크·소유 색인·[WORK_PROGRESS](WORK_PROGRESS.md)·관련 spec/추적표를 동기화한다. 완료면 다음 준비 후보, 외부 차단이면 독립 후보로 이동한다. 외부 차단 아닌 미완료는 Current를 유지한다.
5. ID/상태/카드/계약/선행/인계/Updated/Next를 함께 갱신한다. 한 실행 후 멈추며 연속 실행 요청이 있을 때만 다음 카드를 이어간다.
6. 사용자 DB 초기화·이력 삭제·범위 밖 인프라/권한/예약·구매·배포 금지. 실제 quota/rate limit은 기록하고 자동 구매/재설정하지 않는다.

## Cursor에 전달할 한 문장

```text
NEXT_ACTION.md의 Current 하나를 수행·검증하고 인계와 큐를 갱신해줘. 중앙 관리/저장과 등록 실행 PC를 분리하고, offline 저장본 승인과 live 작업 차단을 구분해줘. 상용 디바이스팜은 필수 선행이 아니야. 외부 차단이면 근거를 남겨 독립 후보로 전환하고 기존 완료 이력은 보존해줘.
```
