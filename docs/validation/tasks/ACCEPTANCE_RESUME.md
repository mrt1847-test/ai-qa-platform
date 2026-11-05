# 실환경 수용 재개 조건 보고

2026-11-05 기능 공백 재조사 후 이 보고의 로컬 후보 소진 판단은 [후속 근거](../reviews/2026-11-05-feature-entry-gaps.md)로 갱신됐다. 아래는 당시의 실환경 재개 조건 기록이다. 현재 구현 후보는 [NEXT_ACTION](../../../NEXT_ACTION.md)의 RX-63~71을 따른다.

- 상태: reported (구현 완료 아님 · live PASS 아님)
- 기준일: 2026-11-05 (Asia/Seoul)
- 적용 범위: [ACCEPTANCE_TASKS](../../managed-pc/ACCEPTANCE_TASKS.md) RX-21~27·RX-29 · [IMPLEMENTATION_TASKS](../../managed-pc/IMPLEMENTATION_TASKS.json) `release_acceptance`
- 색인 조회: `feature_implementation` **16/16 complete** (잔여 0). AD-02~04는 [구현 경계](../../managed-pc/RUNTIME_BOUNDARIES.md#카드-선택과-기존-이력)상 자동 선택 제외. PC 전환 색인 open 0. CF-01 자동 선택 제외.
- 로컬 확인: `IMPLEMENTATION_TASKS.json`에서 feature 잔여 `[]`, acceptance 8건(blocked 2 · not_started 6). fixture PASS를 live 완료로 올리지 않음.

## 게이트 요약

| ID | 상태 | 직접 선행(코드) | 막히는 환경 | 재개에 필요한 것 |
|---|---|---|---|---|
| RX-21 | blocked | RX-08·20·28·37·41·59 complete | independent_server, tls_domain, oidc_tenant, second_client, deployment_authorized | 독립 관리 호스트+DNS/TLS, 운영 IdP, 서비스 계정, 두 번째 접속 PC, 배포 권한자 health/runbook 승인. 상세 [RX-21.md](RX-21.md) |
| RX-22 | blocked | RX-15·30·35·60 complete | verified_web_vm, dedicated_web_origin, native_test_authorized | 지원 VM·전용 origin·실제 deny matrix 시험 허용. 상세 [RX-22.md](RX-22.md) |
| RX-23 | not_started | 코드 선행 대부분 complete; **RX-21 미완** | dedicated_android, actual_model_key, native_test_authorized, independent_server | RX-21 + 전용 AVD + **운영 모델 키** |
| RX-24 | not_started | RX-61 등 complete; **RX-21·RX-22 미완** | verified_web_vm, dedicated_web_origin, actual_model_key, native_test_authorized | RX-21·22 + 격리 브라우저 + 운영 키 |
| RX-25 | not_started | PC-03·RX-53 complete; **RX-21·23·24 미완** | independent_server, second_client, execution_pc_power_test_authorized | 승인된 실행 PC 전원 단절 + 다른 접속 PC |
| RX-26 | not_started | RX-38 complete; **RX-21·23 미완** | independent_server, dedicated_android, fault_injection_authorized | 통신 단절 주입 권한 |
| RX-27 | not_started | RX-62 complete; **RX-21·23 미완** | independent_server, two_registered_workers, shared_test_physical_scope, native_test_authorized | 등록 두 워커·공유 physical scope |
| RX-29 | not_started | **RX-23·24 미완** | actual_model_key, cost_sample_authorized | 양 플랫폼 수용 후 비용 표본 승인 |

## 의존 순서 (환경이 열릴 때)

1. **RX-21** (독립 서버)와 **RX-22** (Web VM 격리) — 서로 독립 재개 가능.
2. **RX-23**(Android)·**RX-24**(Web) — 각각 RX-21(+RX-22 for Web) 이후.
3. **RX-25~27** — RX-21·23(+24 for 25) 이후 장애·경합.
4. **RX-29** — RX-23·24 이후 계측.

## 이미 끝난 로컬 근거 (live로 승격 금지)

- 서버/OIDC fixture: RX-37·41·59
- Web guest·녹화/재생 계약: RX-42·60·61
- Android 배선·모델 검사 fixture: RX-44~46 등
- 복수 워커 lease fixture: RX-62

## 이번 실행에서 하지 않은 것

- 독립 호스트 배포, 운영 키 사용, 실 VM deny matrix, 전원/통신 단절, 두 워커 실경합, 비용 표본 구매/실행.
- AD-02~04·CF-01 자동 착수.

## 재평가 트리거

새 근거가 생길 때만 Current를 RX-21 또는 RX-22로 바꾼다: 독립 호스트/DNS/TLS/IdP/배포 승인, 또는 지원 VM·전용 origin·native 시험 허가. 그 전에는 이 보고를 유지한다.
