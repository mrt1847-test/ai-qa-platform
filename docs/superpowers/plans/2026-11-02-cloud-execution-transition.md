# Cloud Execution Transition Implementation Plan

> **이전 배치안:** [사용자 확정 배치](../specs/2026-11-02-managed-pc-execution-design.md)가 우선이다. 현재 PC를 등록 실행 자원으로 사용하며 중앙 관리/증거는 독립 유지한다. 아래 cloud 전용 MVP·CF-01 우선순위는 더 이상 활성 지시가 아니다. 상용 provider 조사는 선택 후속이다.

> **For agentic workers:** CF-01은 읽기 전용 조사·설계 작업이다. 코드 구현 단계는 산출된 세부 계획에 따라 executing-plans 또는 subagent-driven-development를 적용한다.

**Goal:** 사용자는 PC별 agent 설치 없이 관리 사이트에 접속하고, 서비스가 클라우드 Web·Android 세션을 제어한다.

**Architecture:** 중앙 관리 API/인증/DB/artifact와 서비스 worker/provider adapter를 분리한다. 기존 record→persist→review→approve→replay 및 AI 비용 정책을 재사용한다. 로컬 emulator는 개발 자산이다.

**Tech Stack:** 현재 Python/FastAPI/core 계약 재사용. cloud provider/protocol, 운영 DB/artifact/secret/auth backend는 조사·선정 전 미확정이다. 지금 설치하거나 배포하지 않는다.

**Spec:** [최신 cloud 배치 규범](../specs/2026-11-02-cloud-execution-scope.md), 영역별 불변 계약은 DESIGN/UI_SPEC/DATA_DESIGN/CONTRACTS. 과거 로컬 배치가 충돌하면 최신 cloud 규범이 우선이다.

## Global Constraints

- 사용자 PC worker/ADB/VM은 필수 사용 조건이 아니다. 서비스 측 격리·권한·계측 증명은 유지한다.
- Web·Android 모두 실제 cloud 자원으로 수용한다. 로컬 proof/테스트 fixture를 cloud 성공으로 바꾸지 않는다.
- 공급자 capability·Mobile-Agent/CUAWright 연동 지점은 실제 공식 자료/고정 source로 대조한다. Appium/Playwright라는 이름만으로 호환성을 확정하지 않는다.
- 모델과 provider 자격은 서버 측 별도 secret reference다. 프런트/생성 code에 raw endpoint/token을 전달하지 않는다.
- 저장·승인·재녹화 불변, 일반 actor0/필요 verifier/기본OFF healing, 원본 QA 보존을 유지한다.
- 이번 단계는 구매·과금 세션·계정 가입·설치·배포를 하지 않는다. 필요한 접근 정보는 실제 실행 카드의 준비 조건으로 남긴다.

## Review Focus

서로 다른 PC에서 접속한 사용자의 자원/권한 혼입, provider session 생성 응답 유실의 중복 과금, 임시 evidence URL 만료, 종료 실패/late cost, 사내 URL 접근 불가, raw driver/모델 자격 노출, local proof를 cloud로 잘못 완료 처리하는 경우를 대조한다.

<a id="cf-01"></a>
## CF-01 — 클라우드 공급자 능력·엔진 연결점과 후속 세부 작업 확정

- 상태 not_started. 직접 선행 W01-01 complete. 검증 등급 source_audit/design. 환경은 로컬 문서/공개 코드·공식 문서 조회뿐이며 VM/Android 실행/모델 key/cloud 계정이 없어도 시작할 수 있다.
- 이 작업의 산출물만 작성한다. endpoint만 교체하는 제품 patch나 임시 fake cloud adapter를 만들지 않는다.

### 읽기와 산출물

현재 spec, `RESEARCH.md`의 두 엔진 SHA/출력·쓰기 경계, 기존 worker/job/resource/artifact/secret 계약만 읽는다. 전체 과거 audit를 연쇄로 읽지 않는다.

생성할 파일:

1. `docs/cloud/PROVIDER_CAPABILITIES.md`: 후보와 근거 표. managed browser/Android farm과 서비스 운영 emulator 선택지를 구분하고, 우선 후보는 플랫폼당 최대2개만 깊게 확인한다.
2. `docs/cloud/ADOPTION_DECISION.md`: cloud target/account/session/protocol 선택·근거·비용/접근 unknown·고정 source 연결점·현 코드 재사용/적응/개발 전용 분류. 공급자 미선정은 미선정으로 쓴다.
3. `docs/cloud/IMPLEMENTATION_TASKS.json`과 필요한 영역별 카드: 후속 코드를 작은 검증 단위로 나눈 실제 파일·선행·interface·부정 시험·환경·완료 조건·인계 경로. 원본 W 이력과 별도 관리하되 CLOUD_TASK_INDEX 및 NEXT_ACTION에 새 색인 경로/조회 규칙을 함께 등록하여 Current 하나를 넘긴다.
4. `docs/validation/tasks/CF-01.md`: 검토한 URL/문서 날짜·source SHA/파일/함수·확인/미확인·선정 판단과 후속 준비 조건.

### 실행 체크리스트

- [ ] 1. 사용자 PC 설치 없는 cloud 목표와 현재 local-only 코드의 차이를 나열한다. 중앙 인증/DB·artifact·secret/backend와 session cleanup을 빠뜨리지 않는다.
- [ ] 2. 공식 문서에서 자원 목록/세션 생성·조회·종료, 제어 프로토콜, PNG/screenshot·좌표/IME·앱 설치, TTL/동시성·region/private-network·과금/계정 조건을 확인한다. 자료가 없으면 unknown으로 표시한다.
- [ ] 3. 고정 CUAWright source의 browser/context/Playwright·model helper·PNG/로그 writer를 provider 신뢰 driver와 어떻게 연결할지 함수 단위로 대조한다.
- [ ] 4. 고정 Mobile-Agent source의 ADB/관찰/행동 호출을 farm ADB 또는 지원 API에 연결 가능한지 대조한다. raw shell·미지원 입력·capture/geometry가 핵심 흐름을 막으면 후보 미채택/조건부로 기록한다.
- [ ] 5. resource/session identity·claim/lease·불명 dispatch·release/과금·증거 만료와 저장·server credential/auth 책임을 비교한다. 일반 replay AI0과 provider 요금은 다른 항목이다.
- [ ] 6. 기존 W/AD/UI 산출물을 재사용/수정/개발 전용/새 cloud 수용으로 매핑한다. 완료 이력을 지우거나 기존269개를 cloud 수용으로 세지 않는다.
- [ ] 7. 공급자가 정해진 범위만 실행 가능한 작은 후속 카드로 만든다. 미정인 protocol/자격/네트워크를 숨기고 큰 구현 한 장으로 묶지 않는다. DB 초기화·대량 재작성·원격 공개는 임의 진행하지 않는다.
- [ ] 8. 기존 W·AD/UX·CLOUD_TASK_INDEX와 새 cloud 후속 색인의 ID/직접 선행/순환·링크·Current 준비 상태를 코드로 검증한다. 인계/스펙/큐를 맞추고 다음 준비 작업으로 Current를 옮긴다.

### 완료 기준

필수 제어·capture·action 증거·credential·수명 계약마다 근거 또는 명시된 unknown이 있고, 각 후보가 두 엔진의 실제 hook에 대응한다. 다음 작업자가 읽을 최소 입력과 실제 검증 단위가 있으며 cloud 자격이 없는 동안에도 가능한 계약/UI 작업과 실제 세션이 필요한 항목을 구분한다. 읽기 전용 조사 완료가 실제 연결 성공을 뜻하지 않는다.

## 이후 구현 영역 — CF-01에서 세분화 후만 실행

provider/session DTO·실패 정규화 → 서비스 worker/신뢰 driver → Web remote 세션 → Android farm adapter → action 전후 정제 증거/저장·AI authoring/저장 replay → 자원 선택 UI → 중앙 인증/운영 저장·배포 구성 → 종료/장애/비용 → 두 PC 접속과 양 플랫폼 E2E 순의 실제 의존을 확정한다. 이 나열 자체는 실행 가능한 완료 카드가 아니다.

계정/실기기/세션이 막히면 해당 실행 검증만 대기하고, 독립 UX-01 같은 공유 core 후보를 수행한다. 고객 PC에 로컬 agent를 설치하는 경로로 자동 축소하지 않는다.
