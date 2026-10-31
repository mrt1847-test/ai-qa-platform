# UI 조작·상태 누락 점검표 v0.8

[UI 원본 규범](../../UI_SPEC.md) · [작업 색인](README.md) · [요구/시나리오](COVERAGE.md).
**기본15화면 + 선택TC1화면**, 공통6묶음 + 화면88묶음 = **94개 의무 묶음**이다.
묶음 안에 나열한 버튼/필드/상태를 전부 구현·검증해야 해당 행이 완료다. 화면 이름만 존재한다고 통과하지 않는다.

## 공통 적용 규칙

core UI는 실제 API/DB/브라우저와 test-only 외부 입력으로 검사할 수 있다. fixture를 production에 넣지 않는다. native 동작/QA 수용은 [COVERAGE](COVERAGE.md)의 live 담당/C14를 추가로 요구하며 직접 UI 담당만 완료했다고 실제 기기/모델이 검증된 것은 아니다.


UI-01–16 모두 loading/empty/422/403/409/stale·입력 보존/미저장·키보드/focus·1024/1440·query/selected 복원을 적용한다.
해당하지 않는 조작은 이유를 기록한다. 빈 화면/연결 오류를 데이터0건으로 위장하지 않는다.
미승인·미완성·키/예산 없음은 원인에 맞게 비활성/차단하고 조용히 제외하거나 PASS로 만들지 않는다.
기기 preview는 최근 정제 capture+시각이며 busy/권한/만료와 실제 제어를 구별한다.
TC 화면은 선택적으로 이용하지만 구현 대상에서 빠지는 P1 항목은 아니다.

| 화면 | 최초/기능 담당 | 공통 회귀 확인 |
|---|---|---|
| UI-01 | [W10-02](04a-case-management-ui.md#w10-02) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-02 | [W10-03](04a-case-management-ui.md#w10-03) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-03 | [W10-04](04a-case-management-ui.md#w10-04), [W10-05](04a-case-management-ui.md#w10-05), [W21-04](08b-execution-and-suites.md#w21-04) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-04 | [W10-06](04a-case-management-ui.md#w10-06), [W10-07](04a-case-management-ui.md#w10-07), [W10-08](04a-case-management-ui.md#w10-08), [W10-11](04a-case-management-ui.md#w10-11), [W16-02](05b-recording-workflow.md#w16-02), [W16-06](05b-recording-workflow.md#w16-06), [W16-08](05b-recording-workflow.md#w16-08), [W29-06](06-replay-packages.md#w29-06), [W31-06](08a-self-healing.md#w31-06) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-05 | [W11-01](04b-environments-and-launcher.md#w11-01), [W16-01](05b-recording-workflow.md#w16-01), [W16-02](05b-recording-workflow.md#w16-02), [W16-03](05b-recording-workflow.md#w16-03), [W16-04](05b-recording-workflow.md#w16-04), [W16-05](05b-recording-workflow.md#w16-05) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-06 | [W16-06](05b-recording-workflow.md#w16-06), [W16-07](05b-recording-workflow.md#w16-07), [W16-08](05b-recording-workflow.md#w16-08) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-07 | [W29-06](06-replay-packages.md#w29-06), [W17-01](07-trial-and-review.md#w17-01), [W18-01](07-trial-and-review.md#w18-01), [W18-02](07-trial-and-review.md#w18-02), [W18-03](07-trial-and-review.md#w18-03), [W18-04](07-trial-and-review.md#w18-04), [W18-05](07-trial-and-review.md#w18-05), [W19-02](07-trial-and-review.md#w19-02), [W19-03](07-trial-and-review.md#w19-03), [W26-03](10-retention-and-release-gates.md#w26-03) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-08 | [W21-01](08b-execution-and-suites.md#w21-01), [W21-02](08b-execution-and-suites.md#w21-02), [W21-03](08b-execution-and-suites.md#w21-03) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-09 | [W17-01](07-trial-and-review.md#w17-01), [W31-06](08a-self-healing.md#w31-06), [W20-01](08b-execution-and-suites.md#w20-01), [W20-03](08b-execution-and-suites.md#w20-03), [W21-04](08b-execution-and-suites.md#w21-04) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-10 | [W17-04](07-trial-and-review.md#w17-04), [W31-06](08a-self-healing.md#w31-06), [W20-04](08b-execution-and-suites.md#w20-04), [W21-05](08b-execution-and-suites.md#w21-05), [W22-01](08b-execution-and-suites.md#w22-01), [W22-02](08b-execution-and-suites.md#w22-02), [W22-03](08b-execution-and-suites.md#w22-03) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-11 | [W18-02](07-trial-and-review.md#w18-02), [W31-05](08a-self-healing.md#w31-05), [W31-06](08a-self-healing.md#w31-06), [W22-03](08b-execution-and-suites.md#w22-03), [W23-02](09-results-and-analytics.md#w23-02), [W23-03](09-results-and-analytics.md#w23-03) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-12 | [W22-03](08b-execution-and-suites.md#w22-03), [W23-04](09-results-and-analytics.md#w23-04), [W23-05](09-results-and-analytics.md#w23-05), [W24-03](09-results-and-analytics.md#w24-03), [W25-02](09-results-and-analytics.md#w25-02), [W25-03](09-results-and-analytics.md#w25-03), [W32-03](10-retention-and-release-gates.md#w32-03) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-13 | [W24-04](09-results-and-analytics.md#w24-04), [W32-03](10-retention-and-release-gates.md#w32-03) | [W28-03](10-retention-and-release-gates.md#w28-03) |
| UI-14 | [W11-01](04b-environments-and-launcher.md#w11-01), [W11-02](04b-environments-and-launcher.md#w11-02), [W11-03](04b-environments-and-launcher.md#w11-03), [W11-04](04b-environments-and-launcher.md#w11-04), [W11-05](04b-environments-and-launcher.md#w11-05), [W11-06](04b-environments-and-launcher.md#w11-06), [W11-07](04b-environments-and-launcher.md#w11-07) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-15 | [W10-09](04a-case-management-ui.md#w10-09), [W11-08](04b-environments-and-launcher.md#w11-08), [W15-04](05a-action-evidence-and-models.md#w15-04), [W26-03](10-retention-and-release-gates.md#w26-03), [W26-04](10-retention-and-release-gates.md#w26-04), [W26-05](10-retention-and-release-gates.md#w26-05) | [W28-02](10-retention-and-release-gates.md#w28-02) |
| UI-16 | [W10-10](04a-case-management-ui.md#w10-10) | [W28-02](10-retention-and-release-gates.md#w28-02) |

## 개별 조작·상태의 구현과 검사

하위 시험 함수/파일은 향후 만들 산출물이다. 실제 근거는 담당 카드의 `docs/validation/tasks/{ID}.md`와 W28 회귀 기록에 연결한다.
아래 상태는 모두 미구현·미실행이며 이번 문서 점검을 제품 PASS로 표시하지 않는다.

| ID | 누락 없이 포함할 조작·상태 | 직접 담당 | 시험 함수 | 실제 상태 |
|---|---|---|---|---|
| UI-COMMON.01 | 프로젝트 전환·breadcrumb·메뉴·검색 진입·이 PC 연결 | [W10-01](04a-case-management-ui.md#w10-01) | `test_w10_01` | complete |
| UI-COMMON.02 | loading/empty/422/403/409/stale·증거 오류·미저장 이동·중복 제출 차단 | [W10-01](04a-case-management-ui.md#w10-01) | `test_w10_01` | complete |
| UI-COMMON.03 | URL 필터/페이지/선택·scroll/열 복원·키보드/focus·1024/1440px | [W10-01](04a-case-management-ui.md#w10-01) | `test_w10_01` | complete |
| UI-COMMON.04 | 로컬 시작·이미 실행·port 충돌·worker/VM 미준비·탭 종료 | [W12-01](04b-environments-and-launcher.md#w12-01) | `test_w12_01` | 미구현·미실행 |
| UI-COMMON.05 | 2초 polling·마지막 수신·재접속·REC/ITEM/action 복원 | [W12-02](04b-environments-and-launcher.md#w12-02) | `test_w12_02` | 미구현·미실행 |
| UI-COMMON.06 | 안전 종료·절전/복귀 lost·정리/quarantine·새 실행 안내 | [W12-03](04b-environments-and-launcher.md#w12-03) | `test_w12_03` | 미구현·미실행 |
| UI-01.01 | 프로젝트 이름/key/설명/대상·생성·중복 오류·검색/활성·보관 필터·열기 | [W10-02](04a-case-management-ui.md#w10-02) | `test_w10_02` | complete |
| UI-01.02 | 케이스/검토/수행 counts·진행 작업 보관 차단·보관/복구·이력 | [W10-02](04a-case-management-ui.md#w10-02) | `test_w10_02` | complete |
| UI-02.01 | 미완성 REC/검토대기/미분류 실패·최근/대기 RUN·환경 차단·빠른 작업 | [W10-03](04a-case-management-ui.md#w10-03) | `test_w10_03` | complete |
| UI-03.01 | 표시 열·폴더/태그/우선순위/담당자·승인/초안/미완성/보관 필터 | [W10-04](04a-case-management-ui.md#w10-04) | `test_w10_04` | complete |
| UI-03.02 | ID/이름/검증 검색·sort·page·열 설정·선택·뒤로 복원 | [W10-04](04a-case-management-ui.md#w10-04) | `test_w10_04` | complete |
| UI-03.03 | 새 녹화/상세/검토·단일/선택 실행·묶음 추가·복제/보관·항목별 오류 | [W10-05](04a-case-management-ui.md#w10-05) | `test_w10_05` | complete |
| UI-03.04 | 선택의 data 확장·미승인/불가 항목의 명시 제외·N0/100 상한 | [W21-04](08b-execution-and-suites.md#w21-04) | `test_w21_04` | 미구현·미실행 |
| UI-04.01 | 자연어/목적/조건/변수/secret ref/기대·필수 경로·draft 저장·409 | [W10-06](04a-case-management-ui.md#w10-06) | `test_w10_06` | complete |
| UI-04.02 | 단계/검증 추가·복제·삭제·정렬·변수화·제안 diff 거부/수락 | [W10-07](04a-case-management-ui.md#w10-07) | `test_w10_07` | complete |
| UI-04.03 | 검증/단계·code/설정/실행이력/검토·버전 통합 탭·읽기 전용 snapshot | [W10-08](04a-case-management-ui.md#w10-08) | `test_w10_08` | complete |
| UI-04.04 | 최신 draft와 기본 approved 병기·선택 버전·정의/절차/설정 diff | [W10-08](04a-case-management-ui.md#w10-08) | `test_w10_08` | complete |
| UI-04.05 | AI 구조화 job·대기/실패·제안 diff·원문 유지·명시 수락 | [W16-02](05b-recording-workflow.md#w16-02) | `test_w16_02` | 미구현·미실행 |
| UI-04.06 | 녹화 이력·source/produced receipt·부분 기록 열기 | [W16-06](05b-recording-workflow.md#w16-06) | `test_w16_06` | 미구현·미실행 |
| UI-04.07 | 재녹화 base/사유/목표 유지·변경 diff·장치/data/reset·기존 default | [W16-08](05b-recording-workflow.md#w16-08) | `test_w16_08` | 미구현·미실행 |
| UI-04.08 | 원본/승인 code 또는 plan·runtime/compiler/lock/package hash·mapping | [W29-06](06-replay-packages.md#w29-06) | `test_w29_06` | 미구현·미실행 |
| UI-04.09 | 승인 healing capability/scope/상한·기본OFF와 run ON/OFF의 구분 | [W31-06](08a-self-healing.md#w31-06) | `test_w31_06` | 미구현·미실행 |
| UI-04.10 | 케이스별 환경/앱URL/data·reset/cleanup/limits·check method/binding·정책 편집 | [W10-11](04a-case-management-ui.md#w10-11) | `test_w10_11` | complete |
| UI-05.01 | Android/Web 기기 선택·권한 있는 최근 화면·시각·busy/없음/만료 | [W11-01](04b-environments-and-launcher.md#w11-01) | `test_w11_01` | 미구현·미실행 |
| UI-05.02 | 기기→필요 정보→자연어→AI 녹화·뒤로/앞으로·TC 단계 없음 | [W16-01](05b-recording-workflow.md#w16-01) | `test_w16_01` | 미구현·미실행 |
| UI-05.03 | Web URL/Android 앱·빌드·계정ref/data·초기화/한도·불완전 draft | [W16-01](05b-recording-workflow.md#w16-01) | `test_w16_01` | 미구현·미실행 |
| UI-05.04 | 자연어 구조화 제안·모호함/실패·diff 거부/수락 | [W16-02](05b-recording-workflow.md#w16-02) | `test_w16_02` | 미구현·미실행 |
| UI-05.05 | 시작 preflight·불가 사유·busy 대기/돌아가기·중복 시작 차단 | [W16-03](05b-recording-workflow.md#w16-03) | `test_w16_03` | 미구현·미실행 |
| UI-05.06 | 현재 화면·action 전후PNG/log·ACK/대기/오류 counts·메모·마지막 수신 | [W16-04](05b-recording-workflow.md#w16-04) | `test_w16_04` | 미구현·미실행 |
| UI-05.07 | 녹화 완료/중단·flush/정리/저장 구분·실패/부분도 저장·사후 화면 이동 | [W16-05](05b-recording-workflow.md#w16-05) | `test_w16_05` | 미구현·미실행 |
| UI-06.01 | REC 목록/input/output/base·대상/시각/action 수·저장/종료/완결/증거/검토 분리 | [W16-06](05b-recording-workflow.md#w16-06) | `test_w16_06` | 미구현·미실행 |
| UI-06.02 | 미완성/반려 기록·전후 증거/수집 범위/종료 사유·receipt 열기 | [W16-06](05b-recording-workflow.md#w16-06) | `test_w16_06` | 미구현·미실행 |
| UI-06.03 | 복구/재컴파일 요청·진행/실패·새 manifest/version·기존 version 보존 | [W16-07](05b-recording-workflow.md#w16-07) | `test_w16_07` | 미구현·미실행 |
| UI-06.04 | 미완성 후보에서 새 전체 재녹화·이전 프로세스 재개 없음 | [W16-08](05b-recording-workflow.md#w16-08) | `test_w16_08` | 미구현·미실행 |
| UI-07.01 | package/lock/mapping ready·컴파일/격리/계측 차단 사유 | [W29-06](06-replay-packages.md#w29-06) | `test_w29_06` | 미구현·미실행 |
| UI-07.02 | 미승인 시범·OFF actor0·명시 verifier·새 현재 근거 | [W17-01](07-trial-and-review.md#w17-01) | `test_w17_01` | 미구현·미실행 |
| UI-07.03 | 완료/저장 후 검토 요청·exact source/trial/evidence snapshot | [W18-01](07-trial-and-review.md#w18-01) | `test_w18_01` | 미구현·미실행 |
| UI-07.04 | step/action 전후PNG·확대/이동/100%·시각/좌표/로그·출처 구분 | [W18-02](07-trial-and-review.md#w18-02) | `test_w18_02` | 미구현·미실행 |
| UI-07.05 | reviewed/needs_change/evidence_missing·의견·미검토 이동/counts | [W18-03](07-trial-and-review.md#w18-03) | `test_w18_03` | 미구현·미실행 |
| UI-07.06 | 입력/설정/시범/기록/버전 탭·base/candidate diff·불가 사유·새 draft/REC | [W18-04](07-trial-and-review.md#w18-04) | `test_w18_04` | 미구현·미실행 |
| UI-07.07 | review 보관 기한/보호·연장·만료 근거의 승인 차단 | [W18-05](07-trial-and-review.md#w18-05) | `test_w18_05` | 미구현·미실행 |
| UI-07.08 | 승인 및 기본본 사용·반려 사유·409 재비교·기록/기존 기본본 유지 | [W19-02](07-trial-and-review.md#w19-02) | `test_w19_02` | 미구현·미실행 |
| UI-07.09 | 철회 영향/사유·queued 차단/running 취소·no fallback | [W19-03](07-trial-and-review.md#w19-03) | `test_w19_03` | 미구현·미실행 |
| UI-07.10 | 필수 근거의 보호/만료/누락 조회·pin 이유·재검증 안내 | [W26-03](10-retention-and-release-gates.md#w26-03) | `test_w26_03` | 미구현·미실행 |
| UI-08.01 | 묶음 목록·검색/생성·metadata·복제/보관·구성/수행 이력 | [W21-01](08b-execution-and-suites.md#w21-01) | `test_w21_01` | 미구현·미실행 |
| UI-08.02 | AUT 검색·entry 추가/제거/정렬·exact version/data/env/reset·continue/stop | [W21-02](08b-execution-and-suites.md#w21-02) | `test_w21_02` | 미구현·미실행 |
| UI-08.03 | 새 승인 알림·diff/영향·명시 선택 교체·새 suite revision | [W21-03](08b-execution-and-suites.md#w21-03) | `test_w21_03` | 미구현·미실행 |
| UI-09.01 | 시범 목적/미승인 허용·OFF 고정·공통 마법사 진입 | [W17-01](07-trial-and-review.md#w17-01) | `test_w17_01` | 미구현·미실행 |
| UI-09.02 | replay/actor0·verifier 필요 조건·healing OFF/ON/한도·진행 중 불변 | [W31-06](08a-self-healing.md#w31-06) | `test_w31_06` | 미구현·미실행 |
| UI-09.03 | exact 승인/과거본·기기/앱/변수/모델 차단·busy·명시 제외 | [W20-01](08b-execution-and-suites.md#w20-01) | `test_w20_01` | 미구현·미실행 |
| UI-09.04 | 4단계·이름/purpose/source/사유·data/env/build/reset·릴리스·최종 counts/시작 | [W20-03](08b-execution-and-suites.md#w20-03) | `test_w20_03` | 미구현·미실행 |
| UI-09.05 | single/selection/suite/rerun 확장·확정 N/제외·상한·동일 기준 | [W21-04](08b-execution-and-suites.md#w21-04) | `test_w21_04` | 미구현·미실행 |
| UI-10.01 | trial/현재 QA·actor0/OFF·진행·정식 승인과 구분 | [W17-04](07-trial-and-review.md#w17-04) | `test_w17_04` | 미구현·미실행 |
| UI-10.02 | replaying/verifying/healing phase·role calls·eligibility/치유 진행·terminal 새 수행 | [W31-06](08a-self-healing.md#w31-06) | `test_w31_06` | 미구현·미실행 |
| UI-10.03 | 대기/진행/완료/전체 목록·purpose/source/요청자/env/build/결과/기간 필터·page | [W20-04](08b-execution-and-suites.md#w20-04) | `test_w20_04` | 미구현·미실행 |
| UI-10.04 | ITEM 목록·현재화면/이벤트/연결·종료수/PASS수·경과/자원·복원 | [W20-04](08b-execution-and-suites.md#w20-04) | `test_w20_04` | 미구현·미실행 |
| UI-10.05 | 순차·continue/stop·NOT_RUN 이유·부모 확정·전체 결과 | [W21-05](08b-execution-and-suites.md#w21-05) | `test_w21_05` | 미구현·미실행 |
| UI-10.06 | 전체/ITEM 취소·요청/정지/정리·완료/FAIL 보존 | [W22-01](08b-execution-and-suites.md#w22-01) | `test_w22_01` | 미구현·미실행 |
| UI-10.07 | 미시작 skip·사유·running 거부·SKIPPED 집계 | [W22-02](08b-execution-and-suites.md#w22-02) | `test_w22_02` | 미구현·미실행 |
| UI-10.08 | 같은 구성/선택 ITEM 새 재실행·원본/사유·확인 마법사 | [W22-03](08b-execution-and-suites.md#w22-03) | `test_w22_03` | 미구현·미실행 |
| UI-11.01 | 공통 증거 viewer·첫 실패/이전다음·로그/시도·만료/누락 | [W18-02](07-trial-and-review.md#w18-02) | `test_w18_02` | 미구현·미실행 |
| UI-11.02 | 불변 수정 제안 저장/보기·diff·새 전체 REC 채택 | [W31-05](08a-self-healing.md#w31-05) | `test_w31_05` | 미구현·미실행 |
| UI-11.03 | 원래 오류→제안→정책→override→dispatch→QA·치유 금지 사유·badge | [W31-06](08a-self-healing.md#w31-06) | `test_w31_06` | 미구현·미실행 |
| UI-11.04 | 원본/사유가 있는 새 재실행·새 버전/재녹화 이동 | [W22-03](08b-execution-and-suites.md#w22-03) | `test_w22_03` | 미구현·미실행 |
| UI-11.05 | exact version/hash/attempt/data/env/build/engine/model·기대/관찰·첫/마지막 | [W23-02](09-results-and-analytics.md#w23-02) | `test_w23_02` | 미구현·미실행 |
| UI-11.06 | 분석 상태/분류·담당자/메모/issue URL·이의 의견 이력·QA 불변 | [W23-03](09-results-and-analytics.md#w23-03) | `test_w23_03` | 미구현·미실행 |
| UI-12.01 | 선택 결과 새 재실행·원본 FAIL과 새 결과 병기 | [W22-03](08b-execution-and-suites.md#w22-03) | `test_w22_03` | 미구현·미실행 |
| UI-12.02 | 리포트 목록/필터·단일/묶음·범위/purpose/설정·진행 중간 보고 | [W23-04](09-results-and-analytics.md#w23-04) | `test_w23_04` | 미구현·미실행 |
| UI-12.03 | terminal7+진행·세 비율·미검증·제외·실패근거·분석/issue·원본 | [W23-04](09-results-and-analytics.md#w23-04) | `test_w23_04` | 미구현·미실행 |
| UI-12.04 | PASS 안 unassisted/치유·episode 결과·role usage/비용·null/partial | [W23-05](09-results-and-analytics.md#w23-05) | `test_w23_05` | 미구현·미실행 |
| UI-12.05 | 누적 기간/KST·case/version/data/env/build/model/release 필터·all/latest·추세/표본/as_of | [W24-03](09-results-and-analytics.md#w24-03) | `test_w24_03` | 미구현·미실행 |
| UI-12.06 | CSV 생성·수식 안전화·한글/줄바꿈·정제·원본/기준 | [W25-02](09-results-and-analytics.md#w25-02) | `test_w25_02` | 미구현·미실행 |
| UI-12.07 | 인쇄 HTML·진행/완료/오류/만료·다운로드·print layout | [W25-03](09-results-and-analytics.md#w25-03) | `test_w25_03` | 미구현·미실행 |
| UI-12.08 | 월3000 workload·최소30 RUN/release·authoring/회귀/치유/재녹화 별도 추정 | [W32-03](10-retention-and-release-gates.md#w32-03) | `test_w32_03` | 미구현·미실행 |
| UI-13.01 | 기준/비교 RUN·case/data/target align·변화/지속실패/추가/제외 | [W24-04](09-results-and-analytics.md#w24-04) | `test_w24_04` | 미구현·미실행 |
| UI-13.02 | 조건/verification/strict diff·나란한 step/PNG/expected/시간/비용·혼합 배너 | [W24-04](09-results-and-analytics.md#w24-04) | `test_w24_04` | 미구현·미실행 |
| UI-13.03 | 동일 release 다중 RUN·월간 조건/계측 범위 비교 | [W32-03](10-retention-and-release-gates.md#w32-03) | `test_w32_03` | 미구현·미실행 |
| UI-14.01 | 이 PC worker/Web/Android·연결/점유/OS/해상도/시각·preview·이 기기로 녹화 | [W11-01](04b-environments-and-launcher.md#w11-01) | `test_w11_01` | 미구현·미실행 |
| UI-14.02 | 환경 profile·URL/package allowlist·viewport/locale/reset·revision | [W11-02](04b-environments-and-launcher.md#w11-02) | `test_w11_02` | 미구현·미실행 |
| UI-14.03 | data 이름/schema/행/secret ref·case 연결·오류·불변 revision | [W11-03](04b-environments-and-launcher.md#w11-03) | `test_w11_03` | 미구현·미실행 |
| UI-14.04 | 설치 앱 기본 선택·package/version/API/ABI·hash unknown | [W11-04](04b-environments-and-launcher.md#w11-04) | `test_w11_04` | 미구현·미실행 |
| UI-14.05 | 단일APK 업로드·hash/metadata/서명·도구 미준비/미지원/크기 오류 | [W11-05](04b-environments-and-launcher.md#w11-05) | `test_w11_05` | 미구현·미실행 |
| UI-14.06 | 명시 설치/초기화/logout 영향·기기/build 확인·진행/실패/사후 관찰 | [W11-06](04b-environments-and-launcher.md#w11-06) | `test_w11_06` | 미구현·미실행 |
| UI-14.07 | VM/driver/broker/격리·USB/IME 진단·quarantine·proof 복구·unsupported 없음 | [W11-07](04b-environments-and-launcher.md#w11-07) | `test_w11_07` | 미구현·미실행 |
| UI-15.01 | 프로젝트/분류·기본 한도/실패/보관 설정·충돌 | [W10-09](04a-case-management-ui.md#w10-09) | `test_w10_09` | complete |
| UI-15.02 | 역할별 endpoint/model/key ref·일회 입력·원문 미반환·비용 안내 | [W10-09](04a-case-management-ui.md#w10-09) | `test_w10_09` | complete |
| UI-15.03 | 변경 audit·actor/time/reason·필터/cursor·다른 project 차단 | [W11-08](04b-environments-and-launcher.md#w11-08) | `test_w11_08` | 미구현·미실행 |
| UI-15.04 | worker 범위/enrollment/revoke·연결 상태·공간/보호 요약 | [W11-08](04b-environments-and-launcher.md#w11-08) | `test_w11_08` | 미구현·미실행 |
| UI-15.05 | 명시 모델 연결 검사 job·호환/actual model/비용·키 없는 replay | [W15-04](05a-action-evidence-and-models.md#w15-04) | `test_w15_04` | 미구현·미실행 |
| UI-15.06 | DB/파일/보호/삭제예정·한도·retention plan/pin/release·공간 조치 | [W26-03](10-retention-and-release-gates.md#w26-03) | `test_w26_03` | 미구현·미실행 |
| UI-15.07 | 일관 백업 요청·진행/결과/incomplete·receipt·secret 제외 | [W26-04](10-retention-and-release-gates.md#w26-04) | `test_w26_04` | 미구현·미실행 |
| UI-15.08 | 별도 경로 복원 검사·명시 활성화·key 재설정·과거 job 재개 금지 | [W26-05](10-retention-and-release-gates.md#w26-05) | `test_w26_05` | 미구현·미실행 |
| UI-16.01 | 선택 TC 목록/검색/분류·원문/단계/기대·revision·복제/보관 | [W10-10](04a-case-management-ui.md#w10-10) | `test_w10_10` | complete |
| UI-16.02 | 참조 연결/해제·새 TC 버전 정보·명시 import diff/수락·case 독립 | [W10-10](04a-case-management-ui.md#w10-10) | `test_w10_10` | complete |

## 종료 대조

- 담당자 있는 행 = 계획상 배정이며 실제 구현/통과가 아니다.
- component·tab·button마다 route/request/성공/오류/저장/이동을 확인한다. API만 통과하고 UI 연결이 없으면 실패다.
- UI03→05→04/06→07→09→10→11/12→13, UI14/15 준비, UI16 선택 참조를 실제 browser로 확인한다.
- 일부 기능이 뒤 작업에 있다면 앞 화면은 사유를 표시하고 담당 ID를 남긴다. W28에서 그런 임시 상태가 MVP 핵심에 남으면 출시 차단이다.
- 최종 근거: `docs/validation/ui-management-recording.md`, `ui-review-execution.md`, `mvp-results.md`. 이번에는 생성/실행하지 않았다.
