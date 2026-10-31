# 세분화 검토·보완 기록 v0.8

> 구현 후 2026-11-01 검토 R01~R20/V01은 [별도 수정 결과](../validation/reviews/2026-11-01-remediation-result.md)에 수용 근거를 남겼다. 아래 초기 계획 검토와 구분한다.

기준일: 2026-10-31. 검토 대상은 기존 v0.6 DESIGN/DATA/UI/T 계획/W 진행표/실행 spec이다.
[작업 색인](README.md) · [공통 계약](CONTRACTS.md) · [UI 추적](UI_COVERAGE.md) · [요구 추적](COVERAGE.md).

## 1. 검토 결론과 경계

32개 W는 기능 묶음이었고, 다른 모델에게 한 번씩 맡길 상세 지시로는 컸다.
이번에는 **33개 W 아래163개 상세 작업, 15개 영역 문서, 공통 계약/인계/추적표**로 바꾼다.
문서에 이미 있던 조작도 실제 저장 소유·API·화면·시험 담당이 없으면 보완 대상으로 보았다.
아래 상태는 **문서 반영 상태**다. DB/VM/기기/모델/제품 코드가 구현됐거나 시험 통과했다는 뜻이 아니다.

## 2. 발견 사항·보완·담당

| ID | 발견한 누락/모호함 | 보완 결정 | 작업/규범 | 문서 상태 |
|---|---|---|---|---|
| F01 | W 하나가 여러 화면/기능을 포함 | W는 상위 상태, 한 요청은 leaf1개. 163개로 분해 | README/HANDOFF, 전체 카드 | 반영 |
| F02 | 화면 번호 연결만 있어 조작별 누락을 판별하기 어려움 | 16화면+공통94개 조작·상태 묶음에 직접 담당/시험/근거 연결 | UI_COVERAGE | 반영 |
| F03 | W16 전체를 끝낸 후 W29를 하면 compile 통합과 순환/누락 위험 | W16-05 source/fallback → W29/W30 → W16-07 finish 통합 | leaf DAG, C07 | 반영 |
| F04 | 원래 W10의 통합 탭에 실행 설정 편집 담당이 불명확 | case별 check method/binding·healing capability·환경/한도 편집 작업 추가 | W10-11, C02/C06/C09 | 반영 |
| F05 | diff 제안/수락 API는 있으나 영속 소유/중복수락 계약 부족 | case_edit_proposals/decisions·base/hash·명시 수락 원자성·중복1 | W06-09, C12 | 반영 |
| F06 | browser 메모가 worker seq와 충돌할 수 있음 | recording_notes 독립 actor/commitseq/requestkey·append, 제어/expected 변경0 | W06-01/W16-04, C12 | 반영 |
| F07 | 선택 기기의 미리보기 capture를 담을 typed owner 없음 | resource_observations와 artifact_refs.resource_observation_id 추가 | W06-08/W11-01, C03/C12 | 반영 |
| F08 | app_inspect는 session없음인데 installed app은 live ADB 필요 | APK metadata=app_inspect, live관찰=read-only resource_probe/physical lease | W11-04, C04 | 반영 |
| F09 | package0 초안의 나중 컴파일 route·권한 누락 가능 | package-rebuilds route/source refs·관리 owner null·새 manifest/version만 | W16-07/W29-04, C04/C07/C11 | 반영 |
| F10 | 편집한 정의/절차가 예전 package를 그대로 가질 위험 | 의미 편집은 package=null 새 draft·전체 REC. rebuild는 같은 source만 | W05-03/W10-07/W10-11, C02 | 반영 |
| F11 | API payload가 source/package/approval를 자의적으로 지정할 여지 | 공개 CaseEditInput과 내부 materializer 입력 분리, provenance 주입422 | W05-02/W10-06, C02/C12 | 반영 |
| F12 | default25/max100·오류·CAS·멱등성·로컬인증이 여러 문서로 흩어짐 | DTO/status/7일 key/60초 일회 nonce·CSRF/Origin/worker분리를 한 계약에 고정 | W04/W08/W10, C01 | 반영 |
| F13 | claim과 runner ACK가 각각 attempt를 만들 수 있음 | claim에서1회생성, ACK는 확인만. 중복nonce/응답으로 runner추가0 | W08-02/03, C04 | 반영 |
| F14 | 단말 별칭/project별 등록으로 같은USB 이중배정 가능 | physical key(worker,native serial)에서 lease1 | W07-01/W08-02, C04 | 반영 |
| F15 | 일반 action retry1과 uncertain dispatch 금지의 경계가 불명확 | 미dispatch 증명된 전달 전만 retry. durable dispatch_started 후는 재전송0 | W09-02/W13-03/W31-02, C04/C05 | 반영 |
| F16 | terminal 취소 재요청과 취소 멱등 receipt가 충돌 | 새 finalizing/terminal 취소409, 기존 동일key는 원래 receipt | W09-01/W22-01, C04 | 반영 |
| F17 | spool최대7일을 미ACK에도 적용하면 기록 손실 | 7일 자동청소는 ACK/hash확인된 것만·미ACK압박은새행동중지/부분보존 | W14-01/W26-01, C05 | 반영 |
| F18 | UI projectcursor와 worker local_seq를 혼용할 위험 | 별도 타입·route·contiguous ACK와commitseq분리 | W08-04/W12-02, C01/C11 | 반영 |
| F19 | preview를 승인/환경 예약으로 오해할 위험 | enqueue/claim 재검사·exactapproval/버전/정책 snapshot·제외 명시 | W20-01/02/W21-04, C09 | 반영 |
| F20 | 구조화/연결검사의 role 계측 소유가 모호 | 구조화authoring·연결검사maintenance·모든 retry계측·QA=null | W15/W16-02, C04/C06 | 반영 |
| F21 | manual pin 해제로 approval protection까지 풀 수 있음 | manual API는manual만·approval/review/build/backup은각수명API | W26-02, C12 | 반영 |
| F22 | backup job은 있으나 purpose enum에 없음 | backup을관리purpose·owner null/QA null/기기·모델제어없음으로추가 | W06-02/W26-04, C04 | 반영 |
| F23 | 복원 DB의 queued/running·기존lease가 자동작동할 위험 | 별도경로검사/명시활성화·옛실행재개0·lease/token폐기·quarantine/key재설정 | W26-05, C10 | 반영 |
| F24 | 비용비교를위해AI필수검사를빼면품질조건이달라짐 | 같은oracle유지가능cohort만비교·전체/구성별표본수·거짓PASS별도 | W32-02, C06/C09 | 반영 |
| F25 | 3000TC를단일RUN이나새batch기능으로오해 | RUN100유지·최소30RUN/release_label·추가data/env/retry별도 | W21-04/W32-03, C09 | 반영 |
| F26 | 한 contracts.py가커지고모델별중복DTO가생길위험 | 책임별contracts package·최초소유card/receipt·소비자는동일schema사용 | C00, 모든card | 반영 |
| F27 | case/activity UI가완료여도후속기능은mock상태일수있음 | 앞작업은shell/조회경계명시·실제후속담당지정·W28에서임시핵심UI차단 | W10-08/W28-01, UI_COVERAGE | 반영 |
| F28 | 파괴적purge/영상/수동제어를구현범위로확대할여지 | archive는유지·historypurge UI는MVP밖. 나머지기존P1경계유지 | C00/C10, root후속목록 | 반영 |
| F29 | SQLite 전체백업과project경로/worker역할의충돌 | PC전체/local_owner전용·API가DBsnapshot·worker는HTTPbytes복사·일반artifact노출금지·전체진행작업정리후복원 | W26-04/05, C01/C10/C11 | 반영 |
| F30 | 결과7종/집계함수가리포트단계에처음등장해trial/수행이앞서사용 | W23-01순수kernel을W06-06직후로이동·W09-04가명시의존·리포트UI는W22뒤 | W23-01/W09-04/W23-02, leafDAG | 반영 |
| F31 | job/attemptFK가사용할resource/worker schema의최초소유가흐림 | worker기본은W04-03·physicalkey/alias는W06-10·lease/job/attempt는W06-02·inventory는W07 | W04-03/W06-10/W06-02/W07-01 | 반영 |
| F32 | nullable FK도부모테이블이아직없으면앞선저장단계가실패할수있음 | 모든FK대상schema를B단계에서확정·후속단계는service구현·FK목표존재/nullable insert검사·누락migration경로명시 | W05/W06, C12 | 반영 |
| F33 | 최소 패키지/app/page/검사 환경 없이 외부 탐색부터 시작 | W00-01–04를 앞에 추가하고 기존 src/tests 재사용·lock/CLI/import/HTTP smoke 검증 | W00, C13 | 반영 |
| F34 | VM 차단이 실제 의존 없는 DB/queue/관리 UI도 막음 | 직접 선행48개 교정·환경 요구/검증 등급·독립 준비 후보 선택 | SCHEDULING, C14 | 반영 |
| F35 | core 검증과 native 수용을 한 task에 묶어 전체 진척 정지 | core fixture는 별도 표기·실제 치유 W31-07 및 원래 live/final gate 유지·parent gate 지정 | W31-07, C14/COVERAGE | 반영 |
| F36 | 큐의 오래된0완료 표시로 실제 source 완료/VM 차단이 사라질 위험 | 실제 TASK_INDEX·두 인계·코드 hash를 기준으로1완료/1차단 보존 | NEXT_ACTION/SCHEDULING | 반영 |

## 3. 문서 검증 방식

1. 원본 R35개를 추출해 P0 32개는 leaf 담당 존재, P1 3개는 명시 후속인지 대조한다.
2. UI16화면과 공통 상태를94개 묶음으로 나눠 각 묶음에 정확히 한 직접 담당을 지정한다. 통합 검수는 W28에서 별도 수행한다.
3. UI21/DATA22/실행10 시나리오를 원문 번호/내용으로 추적하고 leaf ID가 실제 존재하는지 검사한다.
4. TASK_INDEX와 각 카드의 ID/선행/상태/계약/기대/시험명·파일·링크를 대조한다. 없는 선행/순환/중복은 오류다.
5. 모든 카드에 파일·정확한 함수/route·검증 전제·관찰 projection·명령·완료 근거 경로가 있는지 확인한다.
6. root진행률·문서영역수·leaf수·UI묶음수와 미착수 상태를 맞춘다. Markdown링크/anchor·JSON/Python예시·diff공백을 검사한다.
7. 남은 모호함을 아래 실제gate와 구별한다. 문서의 기대 결과를 실제 관찰값으로 보고하지 않는다.

## 4. 구현 전에 확정/검증할 실제 gate

| 아직 확인할 사항 | 소유 | 실패/부재 시 처리 |
|---|---|---|
| 실제 Windows에서 사용할 VM제품/버전·가상화/관리권한·Linuxdriver권한/네트워크 분리 | W01-02/W03-02/W07-02 | P0차단·ADR수정, native비격리우회금지 |
| 공개SHA출력/patch·컴파일subset·rawaction/helper차단·capture경계 | W01/W29 | source 위치/실험 근거로 재설계, 지원을 주장하지 않음 |
| USB기종/AndroidOS·ADB권한·IME/한글·FLAG_SECURE·앱meta도구 | W02/W11 | 지원범위/환경차단, 자동unlock/보안화면우회금지 |
| 허용한합성/staging대상·앱/package·QA계정·외부화면전송정책 | W01–03/W16 | 합성만사용·대상입력대기, 업무화면임의전송금지 |
| 실제provider/model/image/action프로토콜·usage/tariff/월예산 | W03/W15/W32 | 호환/strictbudget차단 또는 명시estimate·미계측표시 |
| 실제schema/transaction/FK·GC/승인/복원경합 | W04–06/W19/W26/W27 | 실패한leaf재개·제품통과표시금지 |
| 정상/결함/장애/치유의정확성·falsePASS·성공률·성능/비용 | W27/W28/W32 | 실제측정후판정, 제안수치를실측처럼쓰지않음 |

60초 nonce/typedproposal저장/관리job backup/미리보기 소유 등은 이번 세분화에서 정한 구현 상세다.
사용자가 정한 녹화/재생/검증/healing/사후승인 방향을 바꾸지 않는다. 보완 계약은 root DESIGN/DATA/UI에도 연결한다.

## 5. 변경 보관과 진행

개정 전 여섯 문서는 [v0.6 보관본](../history/v0.6/WORK_PROGRESS.md)에 보존한다.
현재 진행률은0/33 W·1/163상세다. W01-01 완료와 W01-02 차단을 보존했다. 문서 작성·정합성 검사는 제품 완료 수에 넣지 않는다.
실제 구현에서 새로운 불일치를 발견하면 여기에 근거/영향ID를 추가하고 관련카드/규범/추적표를 함께 수정한다.

## 6. v0.8 기반·차단 진행 보완

[변경 선행/기존 근거 보존](SCHEDULING.md)에48개 직접 선행 교정과 검증 등급/실제 수용을 기록했다. W00부터 진행하고 VM이 없는 가지는 대기에 두며 실제 독립 core로 전환한다. 실제 native/품질/비용·MVP gate는 그대로 필요하다. [개정 전 v0.7](../history/v0.7-before-bootstrap/WORK_PROGRESS.md)을 보관했고 기존 source/probe/test/인계는 수정하지 않았다.
