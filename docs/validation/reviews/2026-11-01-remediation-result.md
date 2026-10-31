# 계약 검토 수정 결과 — 2026-11-01

원 검토 R01~R20과 V01을 수정했다. 기존 구현과 미커밋 변경을 보존했으며, 신규 제품 단계 W15 이후를 완료 처리한 것은 아니다. 현재 구현의 관리 UI·도메인·실행 제어·증거 저장 계약을 보완한 작업이다.

## 수정 추적

| 지적 | 수정한 동작 | 주된 검증 |
|---|---|---|
| R01 | 버전 전체 정의/설정/절차/source·package body hash를 공용 helper로 식별. 변수·selector·비밀 별칭의 `name` 같은 키도 보존. 녹화 절차의 명시적 비밀 원문은 저장 전 거부, artifact availability는 hash에서 제외 | test_review_domain |
| R02 | 스텝 편집이 Android 대상·설정·녹화 절차와 parent를 보존. 새 버전은 package-null | test_review_domain, 실제 브라우저 |
| R03 | 화면이 전체 snapshot을 복원하고 변경하지 않은 다중 단계/check/final/path/secret ref/설정/절차를 보존 | test_review_ui, 실제 브라우저 |
| R04 | 제안의 고정 base ID/hash와 현재 head를 함께 검사. 오래된 제안 거부. 제안 수락의 refs/좌표도 공용 parser로 보존 | test_review_domain |
| R05 | 실제 create_app에 catalog 연결. 앱 factory/health는 DB를 열지 않고 실제 catalog 조회가 DB를 연다 | bootstrap 시험, test_review_ui, 실제 브라우저 |
| R06 | 관리 UI·case/TC/settings/taxonomy/secret/model binding mutation의 Origin·CSRF·서버 actor 검사 통일. CSRF GET은 토큰을 회전하지 않음 | W04/W10/test_review_ui, 실제 요청 헤더 |
| R07 | 실제 PNG 형식/CRC/geometry/압축 데이터 검증. 픽셀 정제 보장이 없는 민감 캡처는 저장·전송 전 거부 | test_review_actions, W13 |
| R08 | attempt/action별 durable 상태 전이와 프로세스 lock. unknown/dispatch_started 재호출은 명령 0. journal에도 attempt action/time 한도 보존 | test_review_actions, W13 |
| R09 | lookup 후 및 journal flush 후 실제 제어·generation·lease 여유·watchdog·한도 재검사. phase 객체 재생성 시 같은 attempt 예산 공유 | test_review_actions, W09 |
| R10 | 복구 manifest별 불변 파일·해시·경로·prior lineage. 전체 입력 검증 후 쓰기. 파일 I/O를 DB writer transaction 밖으로 분리. 실패 시 새 미참조 파일만 정리 | test_review_evidence, W14 |
| R11 | 실제 REC/ITEM→job→attempt→action/check 소속 검증 후 ready+typed ref 원자 저장. 격리 파일 ready 승격, ready ID/메타데이터 변경도 거부 | test_review_evidence, W14 |
| R12 | 기존 hash 업로드도 metadata/owner를 먼저 검사. MIME별 identity 분리. 실제 파일 상태 확인 | test_review_evidence |
| R13 | CRUD의 같은 key/body 원 receipt·다른 body 409, 7일 expiry, 동시 요청 단일 결과, DB/receipt 원자성. Worker 파일 업로드도 key/body intent 및 원 receipt 보존 | test_review_ui, worker HTTP 회귀 |
| R14 | TC 복제/보관/참조 연결·해제/가져오기 preview·거부·수락, 단계 제안 수락·거부를 실제 API에 연결 | test_review_ui, W10, 실제 브라우저 |
| R15 | UI/API의 timeout 1~600 검증 공유. 음수·0·상한 초과 거부 | test_review_ui |
| R16 | 같은 attempt/seq의 다른 PNG/log payload는 충돌. 동일 body만 기존 receipt 반환 | test_review_evidence, W14 |
| R17 | ACK 파일 정리 뒤에도 prefix/hash metadata를 남김. 재시작 후 다음 ACK 가능. journal은 lock+atomic replace | test_review_evidence, W14 |
| R18 | deferred exact version/package/link 및 ready/source manifest ID·hash 관계를 전방 migration으로 강제 | test_review_domain, W06 |
| R19 | manifest→produced version/동일 case/source 관계를 deferred FK claim으로 강제 | test_review_domain, W06 |
| R20 | 영구 사실 UPDATE/DELETE 보호. 모든 Store의 recursive triggers로 INSERT OR REPLACE 우회도 차단 | test_review_domain, W06 |
| V01 | 중복 helper 명칭·가짜 approval 포인터·서로 다른 package source 등 시험 fixture를 올바른 관계로 수정. 별도 router 설치에 의존하던 검증도 정정 | 전체 회귀 |

## 추가로 보완한 경계

- Clone도 정의/단계/check projection을 같은 transaction에서 생성한다.
- Deferred COMMIT 실패 시 Store가 열린 transaction을 rollback한다.
- 동시 파일 업로드는 독립 partial 파일을 사용하고 동일 object ID에 다른 bytes를 덮어쓰지 않는다. staging을 저장해 rename 이후 DB 실패의 재시도가 같은 object를 완성한다.
- Local owner의 actor identity를 재접속에도 유지한다. 최초 프로젝트 1개의 동일 Origin 로컬 setup 이후 프로젝트 생성은 local-owner session+CSRF가 필요하다.
- 민감 입력을 포함할 수 있는 receipt에 원문 SHA256을 저장하지 않는다. 내부 HMAC key는 Windows 사용자 DPAPI로 보호한 envelope만 저장하고, 모델 API key의 저장 위치는 기존 OS 비밀 저장소를 유지한다. 구현 API는 [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)와 [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata)를 따랐다.
- Browser CRUD의 outer transaction이 실패하면 새로 만든 OS secret write를 보상한다. 시험은 이 외부 저장 경계를 대역 처리했고 실제 사용자 key는 사용하지 않았다.

## 검증 근거

최종 전체 회귀는 **141 passed, 실패0, 1 deselected / 57.63초**다. 제외한 것은 기존 blocked인 W01-02 VM live 시험이다. [JUnit 결과](remediation-tests.xml), [요약](remediation-summary.json), [브라우저 결과](browser-result.json)에 보존했다. 실제 관리 UI 변경 요청16개가 통과했고 console error는0이었다. Python `compileall`과 `pip check`도 통과했으며 신규 의존성을 설치하지 않았다.

실행 명령:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --deselect tests/integration/test_w01.py::test_w01_02 --tb=short --junitxml=docs/validation/reviews/remediation-tests.xml
.\.venv\Scripts\python.exe -m compileall -q src migrations
.\.venv\Scripts\python.exe -m pip check
node docs/validation/reviews/browser-journey.cjs
```

브라우저 검증은 실제 create_app·임시 SQLite·설치된 Chrome으로 수행한다. 프로젝트 생성→session→개요→케이스 생성→정의 재저장→Android 설정/절차 보존→스텝 편집→설정 저장→TC 복제/보관/연결/해제/preview/거부/수락을 확인한다. 보호 대상 mutation에 Origin/CSRF/key가 있었고 console error가 없었다. [최종 화면](browser-final.png)은 이 기능 확인의 증거이며 전체 시각 디자인/사용성 수용을 뜻하지 않는다. 브라우저 harness는 현재 Codex 번들 Playwright와 설치된 Chrome을 사용하는 로컬 검증 도구다.

샌드박스에서는 Windows socketpair 초기화와 파일 rename에 제약이 있어 해당 검증을 승인된 일반 로컬 실행으로 수행했다. DB·파일은 모두 새 임시 경로를 사용했다. 사용자 런타임 DB 초기화/마이그레이션, 모델 호출, USB/VM 조작, 설치, 배포, Git commit/push는 수행하지 않았다.

## 다음 작업자가 지킬 한계

1. **민감 PNG 마스킹 구현 완료로 해석하지 않는다.** 현재는 정제 보장이 없으면 차단하는 보호다. 실제 authoring 연결 시 신뢰할 픽셀 정제 제공자와 coverage 검증을 연결하기 전에는 민감 캡처를 활성화하지 않는다. `secrets=()`로 비밀 목록을 비워 우회하지 않는다.
2. 현재 runtime upload의 검증된 owner는 REC/ITEM이다. 다른 management owner를 임의 UUID로 받아 성공시키지 않는다. Resource/build/export 등 후속 소비자는 각 소유 스펙의 typed ref/권한 계약을 구현해야 한다.
3. 기존 typed ownership이 없는 artifact metadata는 지우거나 유효하다고 주장하지 않는다. 원본을 보존하고 조회를 unverified로 거부한다. 잘못된 기존 package/materialization 관계는 migration을 실패시키며 자동으로 provenance를 고쳐 쓰지 않는다.
4. 실제 마이그레이션은 신규 `0022/0023/0024`다. 이번에는 임시 DB에서만 새 설치·전방 제약을 검증했다. 사용자 DB에 적용한 기록이 아니다. DPAPI 보호 receipt key의 다른 Windows 사용자/PC 복구 처리는 W27의 OS 비밀 복구와 함께 검증해야 한다.
5. W01-02 VM과 후속 native/model·trial/approval/replay/healing/GC/복구 통합 게이트는 이 결과로 완료되지 않는다. 현재까지는 core 기능 검증이며 실제 배포 전 검증과 별도다.

Current는 W15-01을 유지한다. 기존 53개 완료 수를 문서 수정이나 보완 횟수로 늘리지 않는다. 외부 차단은 해당 native 가지에만 적용하고 독립 core 작업은 계속할 수 있다.
