# Next Actions

Updated: **2026-11-14 (Asia/Seoul)** — [중앙 관리·실행 PC 설계](docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md)가 현재 배치다. 초기 실행 자원은 현재 PC이며 추가 PC/선택 cloud adapter로 확장한다. 관리 UI/API·DB·증거는 실행 PC와 독립 가동한다. 접속 PC는 웹만 사용하고 등록 실행 PC에는 worker/driver를 준비한다.

실행 PC offline에도 서버에 commit/ACK된 녹화 조회·검토·승인은 가능하다. 재녹화·trial·정식/묶음·재실행·기기 진단은 불가하며 재연결 후 사용자가 명시 실행한다. 필수 증거/기존 OFF trial/승인 불변성은 유지한다. [정상 진입점 보완](docs/managed-pc/ENTRY_COMPLETION_TASKS.md) RX-63~71의 기존 증거는 보존한다. QA 결과·워커 정리·실제 driver의 남은 연결은 [RX-72~78](docs/managed-pc/RESULTS_AND_NATIVE_TASKS.md)에서 먼저 구현한다.

기존 W 완료126/163·상위6/33, AD-01·UX-01~03 완료(4/7), RX-01~20·RX-28·RX-30~86·RX-91~99 완료는 보존한다. 현재 PC HTTPS/AVD 녹화·모의 HTTPS operational·목표 고정·Android 다스텝·타임라인·재생 패키지·claim 고정 시범/회귀·시범 승인·묶음 회귀·Check/제한 healing·자연어 구조화·Android 설치 앱 조회·명시 설치/초기화·모델 연결 검사·운영 브라우저 OIDC 로그인·Web guest 실행 연결·복수 워커 물리 자원 임대·Web 녹화/승인 패키지 재생 공통 계약·앱 조회/설치 워커 등록·구조화 모델 binding·TrustedWebDriver 로컬 실행 포트·브라우저 접수→승인본 회귀·실행 finish→ITEM QA·워커 cleanup 임대 반환·APK 영속 저장·ADB 설치 driver·실 브라우저 CDP 포트·QA·자원 복귀 여정·W11/W12 launcher 회귀까지 확인했다. 이 수는 새 분리 배치의 완료율이 아니다. 문서 수정으로 제품 완료를 추가하지 않는다. 실행 순서는 이 파일만 관리한다. 기능 구현과 실환경 수용을 별도 트랙으로 추적한다.

## Current

**RX-87 — Android worker의 고정 한도·정책·제한 healing 연결.** 다음 RX-88.

[RX-99](docs/validation/tasks/RX-99.md)의 정제 PNG/geometry 실제 입력 연결을 마쳤다. [세부 작업](docs/managed-pc/ANDROID_RUNTIME_TASKS.md)의 A(녹화 한도)→B(재생 정책)→C(서버 check/episode 권한)→D(허용 native 치유) 순서로 구현한다. A의 녹화 고정 한도·실제 전송 경계는 구현/회귀 검증했다. B0.1/B0.2의 fresh server fence와 runtime 연결도 검증했다. 현재 B0.3의 장기 heartbeat/renew·제어 세션 종료/연결 유실을 구현하고, 이후 B/C/D를 이어간다. 부분 구현으로 RX87을 완료하지 않는다. 실제 운영 키 없이 정상 API pin·모의 ADB/HTTP로 구현하고, 실제 모델/기기 수용은 별도다.

## Next

| 순서 | 카드 | 구현 목표 | 직접 선행 |
|---|---|---|---|
| 1 | [RX-88](docs/managed-pc/UI_EXECUTION_TASKS.md#rx-88) | Web 고정 정책·episode·허용 치유·한도 소비 | RX-98/RX-99 및 기존 선행 |
| 2 | [RX-89](docs/managed-pc/UI_EXECUTION_TASKS.md#rx-89) | 정식 준비 ON/OFF와 이유 | RX-87/88 등 카드 |
| 3 | [RX-90](docs/managed-pc/UI_EXECUTION_TASKS.md#rx-90) | 공통4단계·최종 버전/한도/호출 확인 | RX-89 |
| 별도 | 실환경 수용 | 독립 서버·OIDC·AVD/브라우저·비용 계측 | 외부 대기 표 |

운영 키·독립 서버·VM이 없어도 위 구현은 로컬 fixture로 진행한다. trial/기본 healing은 OFF다. 실제 모델 수용을 구현 완료로 대신하지 않는다. RX-29 비용 계측은 양 플랫폼 최종 수용 뒤에 진행한다.

전체 회귀의 기준 커밋부터 존재하는 9개 실패는 [검사 기준선](docs/validation/tasks/REGRESSION_BASELINE_2026-11-09.md)에 정확한 node와 재현을 기록했다. 실패를 숨기거나 안전 gate를 완화하지 않는다. 독립 구현은 진행한다.

## 외부 대기와 재사용

아래 조건은 실환경 수용을 여는 조건이다. 같은 기능의 로컬 구현과 독립 카드는 계속 진행한다.

| 대상 | 상태·재개 조건 | 막히는 범위 |
|---|---|---|
| 독립 관리 서버 | RX-41·RX-59 fixture 완료. 독립 호스트·DNS/TLS·IdP·배포 권한 확인 시 [RX-21](docs/validation/tasks/RX-21.md) | 실제 배포와 이를 사용하는 통합 |
| Android·모델 키 | [AD-01](docs/validation/tasks/AD-01.md)·[RX-44](docs/validation/tasks/RX-44.md)·[RX-45](docs/validation/tasks/RX-45.md)·[RX-46](docs/validation/tasks/RX-46.md) 완료. **운영 모델 키**·독립 호스트 확인 시 RX-23 | 운영 키를 쓰는 Android 녹화·재생 최종 수용 |
| Web VM | 지원 VM·테스트 대상 준비 후 [RX-22](docs/validation/tasks/RX-22.md)/[RX-24](docs/managed-pc/ACCEPTANCE_TASKS.md#rx-24). RX-42·RX-60·RX-61 fixture 완료 | Web 실환경 및 양쪽 전원 종료 수용 |
| 장애·경합 검증 | 다른 접속 PC, 승인된 전원/통신 단절, 추가 워커와 공유 테스트 자원 준비 시 RX-25~27. RX-62 fixture 완료 | 실제 전원 종료·불명 행동·두 워커 수용 |
| AD-02~04 | 개발 이력으로 보존. 적용 범위는 [구현 경계](docs/managed-pc/RUNTIME_BOUNDARIES.md#카드-선택과-기존-이력)에 매핑 | 자동 선택 제외 |
| CF-01 | `future_optional_provider`, 상용 provider 선택 조사로 이동 | 현재 PC 기반 MVP의 필수 선행 아님 |
| 민감 증거 | 정제 coverage/권한/서버 ACK 없으면 실제 전송·승인 근거 준비 미완료 | 해당 실제 경로만. fixture로 제품 성공을 만들지 않음 |

## 차단되었을 때 다음 작업 선택

1. 현재 범위에서 해결할 결함은 해결한다. 외부 조건이면 ID·원인·재개 조건·영향·인계를 기록하고 소유 색인에 blocked를 남긴다.
2. Next에서 **미완료·blocked 아님·직접 선행 전부 complete+인계 보유·알려진 unavailable 환경 없음**인 구현 후보로 Current를 바꾼다. 완료로 가장하거나 진짜 선행/보안/QA gate를 지우지 않는다.
3. 후보가 없으면 TASK_INDEX(기존 W)·DEV_FOLLOW_UP_INDEX(AD/UX)·PC_EXECUTION_INDEX(전환)·[IMPLEMENTATION_TASKS](docs/managed-pc/IMPLEMENTATION_TASKS.json)(RX)를 ID로 합쳐 요약만 조회한다. RX 색인의 feature_implementation을 먼저 선택한다. release_acceptance가 blocked여도 구현 후보를 유지한다. 기존 W/AD는 [구현 경계](docs/managed-pc/RUNTIME_BOUNDARIES.md)의 매핑을 따르며 CLOUD_TASK_INDEX의 future_optional_provider는 자동 선택하지 않는다.
4. 후보도 없으면 [정상 경로 보완 카드](docs/managed-pc/ENTRY_COMPLETION_TASKS.md)의 완료 인계가 일반 브라우저/API/worker 진입점까지 확인했는지 대조한다. 제품 요청에서 fixture 기본값·미등록 handler·무동작 성공·증거 없는 완료가 보이면 구현 결함으로 카드에 남긴다. 확인한 기능 공백이 없을 때 재개 조건을 보고한다. 새 근거/환경 변화가 있을 때만 차단을 재평가한다. 고객 접속 PC 설치나 상용 provider 가입을 우회 필수 조건으로 만들지 않는다.

## 매 실행의 최소 입력과 종료

1. 이 파일→Current 카드→지정 CONTRACTS 절→직접 선행 인계의 interface/검증/제약→관련 코드/저장소 지침만 읽는다.
2. Current 하나를 수행·검증한다. source audit·임시 DB/fixture·실제 PC/배포 수용을 구분하고 UI 변경은 실제 브라우저/키보드·오류·샘플 UI 일관성을 확인한다.
3. `docs/validation/tasks/<ID>.md`에 파일/interface·명령/결과·등급/fixture·제약/재개 조건을 남긴다. [인계 형식](docs/execution/HANDOFF.md#완료-인계-파일)을 따른다.
4. 카드 체크·소유 색인·[WORK_PROGRESS](WORK_PROGRESS.md)·관련 spec/추적표를 동기화한다. 완료면 다음 준비 후보, 외부 차단이면 독립 후보로 이동한다. 외부 차단 아닌 미완료는 Current를 유지한다.
5. ID/상태/카드/계약/선행/인계/Updated/Next를 함께 갱신한다. 한 실행 후 멈추며 연속 실행 요청이 있을 때만 다음 카드를 이어간다.
6. 사용자 DB 초기화·이력 삭제·범위 밖 인프라/권한/예약·구매·배포 금지. 실제 quota/rate limit은 기록하고 자동 구매/재설정하지 않는다.

## Cursor에 전달할 한 문장

```text
master에서 NEXT_ACTION.md의 Current 기능 하나를 실제 진입점에 구현하고 로컬 검증·인계·큐를 갱신해줘. 운영 키·독립 서버·VM 대기는 실환경 카드에 남기고, 구현에는 로컬 fixture를 써. 차단되면 색인의 다른 feature_implementation 후보를 먼저 조회해. 실환경 완료는 별도 증거로만 기록해.
```
