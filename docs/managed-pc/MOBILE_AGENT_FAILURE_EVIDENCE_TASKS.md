# MA05a · 원본 실패 녹화의 저장 상태와 증거 Implementation Plan

> REQUIRED SUB-SKILL superpowers:executing-plans inline/TDD. Spec C05/C06 immutable saved evidence, MOBILE_AGENT_SERVER_WIRING_TASKS MA05. BASE is C2 completed commit.

Goal: 원본 녹화가 실패해도 서버에 ACK된 사실과 종료 상태를 사람이 offline에서 확인한다. observed를 모델 제안이나 before 업로드로 추정하지 않고 unknown을 재실행/승인하지 않는다.

Confirmed gap: genuine API inventory→browser REC→claim→original main→fake ADB timeout→finish/cleanup을 실행했을 때 recording=(open,running,local,incomplete), ma-action=(observed,outcome_known1), 서버 roles=[before]였다. local journal unknown과 quarantine은 있으나 remote failure log가 없다. 증거: git-ignored .review-work/mobile-agent-engine-admission/next-failure-probe.log.

- [ ] RED 새 통합: 원본 before 업로드/모델 제안만으로 action observed/known0을 만들지 않는다. unknown native는 same-call error log를 저장하고 action unknown, no source/no promotion/no retry, 서버 녹화 ended/incomplete이다. native ACK 뒤 after capture 실패는 알려진 ACK 수/원본 prefix와 실패 log를 보존한다. 취소/미전송은 uncertain으로 꾸미지 않는다. 로그 upload ACK 유실은 동일 metadata만 복구한다.
- [ ] worker/mobile_agent_recording.py가 bounded sanitized failure metadata를 생성한다. native 재전송/model 재호출0. after diagnostic capture는 현재 권한이 있을 때만. 오류 문자열/키/원본 stdout을 그대로 보내지 않고 허용 error code와 typed action/hash만 저장한다. existing observed step-v1 history codec에 unknown proof를 섞지 않는다. 필요 시 명시 failure schema를 별도로 정의한다.
- [ ] store/evidence.py의 marked ma-call before는 planned로 만들고 같은 owner/call의 검증된 completed/failed log만 안전한 disposition으로 전환한다. generic legacy/prepare 기존 규칙은 유지한다. unknown이 server history나 compile-ready source로 승격되면 안 된다. 이벤트 prefix는 확인된 physical ACK쌍만 포함하며 unknown/대기/종료를 억지 추가하지 않는다.
- [ ] queue REC failure/cancel finish는 source 승인/컴파일 없이 stopped/saved/incomplete 상태를 기록한다. 기존 승인본/다른 후보를 바꾸지 않는다. ready/ACK facts가 남고 PC offline에서 case/recording/timeline/log를 볼 수 있어야 한다. success source seal은 기존 exact prefix/hash gate를 유지한다.
- [ ] actual original+ASGI/mock provider/ADB 집중 회귀, one fresh review/single TDD fix pass, 인계/계약/큐/master commit. 실제 기기/유료 호출/사람 승인0. 이후 MA05b 저장본 검토·사람 승인·AI0 여정과 B2.3 binding/evaluator/C/D/UI를 진행한다.

Ruling: 실패 녹화는 성공 replay source가 아니다. 로그와 저장 종료 상태는 보존하되 incomplete/unknown을 PASS나 승인으로 바꾸지 않는다. metadata 복구는 녹화 재개가 아니다. 새 manifest/version 필요 여부는 기존 실패 저장 계약과 실제 UI 사용 흐름을 대조해 최소 변경으로 결정하고 인계에 기록한다.

## 실행 단위 분리 (2026-11-17)

MA05a1: 인증된 worker failure/cancel/lost finish에서 해당 REC만 stopped / error 또는 interrupted / stored / incomplete로 끝낸다. 서버 ACK 증거의 PC offline 조회와 성공 seal 회귀를 확인한다. incomplete에는 manifest/version/package/승인을 만들지 않는다. finish receipt 재전송은 같은 결과다.

MA05a2: 별도 failure codec·planned/acknowledged/unknown lifecycle·동일 packet metadata 복구·unknown 로그를 구현한다. a1 완료를 a2 완료나 RX87 완료로 해석하지 않는다.

MA05a1 완료: [인계](../validation/tasks/AI-LIVE-04-MA05A1.md), 관련64pass82.43s. MA05a2는 미완료이며 아래 원 gap은 행동 상태/로그 측면에서 여전히 재현된다.

## MA05a2 보완과 후속 경계

MA05a2는 모델이 반환한 turn의 native/control 실패를 대상으로 한다. diagnostic failure-v1만 서버에 저장하며 normal step-v1 history와 분리한다. before는 planned/known0, same-call ACK proof로만 observed/acknowledged/unknown 또는 known not-sent로 바꾼다. observed 전후 이벤트는 exact pair/hash/action/순서/연속 prefix이며 after PNG는 같은 call geometry다. same-call role bytes는 불변이다. normal packet ACK가 미확인인 동안 finish payload를 만들지 않고 metadata-only 재확인으로 정확한 cursor를 얻은 뒤 error/incomplete로 종료한다. 새 claim/기기/모델 호출0. 재시작 no-resume 유지.

MA05a3 (다음): before는 ACK됐지만 모델 요청이 거절되거나 정상 turn 수신 전에 실패한 경우 별도 bounded 진단 로그를 남긴다. 실제 native 호출0·planned 사실을 유지하고 모델 제안/실행 ACK를 만들어내지 않는다. same worker/project/attempt/call/before hash에 묶고 cached receipt·로그 복구를 확인한다. raw provider 오류/키/추론은 저장하지 않는다.

MA05a4 (별도): worker finish가 전혀 오지 않은 서버 watchdog/lost·lease 만료 경로의 REC 종료 상태를 조사한다. 기존 terminal job fact와 ACK prefix만으로 interrupted/incomplete 저장하고 승인/source를 생성하지 않는다. a1의 인증 worker finish 수용을 실제 PC 전원 종료 수용으로 과장하지 않는다.

## MA05a3 실행 체크리스트 · 등록된 관찰 뒤 authoring 실패

직접 선행: MA05a2 인계와 저장 packet/상태 검사. 전체 이력 문서를 다시 읽지 않는다. 파일은 worker/mobile_agent_models.py·mobile_agent_recording.py, recording/mobile_agent_evidence.py, 새 통합 테스트만 먼저 본다.

- [x] RED: observation 등록 후 before_model 거절이면 provider0/native0, HTTPS503이면 provider mock1/native0, 정상 모델 응답을 worker가 받지 못하거나 거절하면 재요청0이다. 세 경우 REC stopped/stored/incomplete, before+bounded 진단 log를 PC offline에서 읽는다. 실제 비용/usage는 서버 model receipt에만 따른다.
- [x] model port는 현재 등록된 관찰의 frozen call/action/before artifact ID/hash만 별도로 노출한다. 정상 evidence release에서 해제하고 다른 call/attempt와 섞지 않는다. 모델 turn을 만들기 전 오류를 원본 turn이 실행된 것처럼 만들지 않는다.
- [x] 별도 `mobile-agent-authoring-failure-v1`의 exact fields(call/action/before hash, stage=authoring, outcome=no_accepted_action, native_calls0/native=None, bounded reason)만 저장한다. raw 예외/provider body/키/추론0. action은 planned/known0을 유지하며 캐시된 모델 응답으로 실행을 재개하지 않는다.
- [x] server는 exact original pin과 현재 project/worker/attempt/call의 등록된 model observation·before ACK를 검사한다. 다른 call/hash/owner/type/임의 schema/추가 field 거절, same-call role immutable 규칙 유지. normal step-v1/history release로 인정하지 않는다.
- [x] 같은 durable metadata seq와 pending recovery를 재사용한다. 로그 ACK 유실은 같은 body/time/key만 재확인하며 capture/model/native0이다. 정상 원본 녹화·모델 history·ma05a1/a2·finish/cleanup 집중 회귀 후 한 fresh review/한 fix pass, 인계·큐·master commit.

범위 제외: before image upload 자체가 불명인 경우의 새 payload 추정, 정상 관찰 등록 전 caller가 주장한 call metadata, 미확인 모델 결과를 성공으로 분류, 운영 키 실호출. 이 경계는 보존된 서버 이미지/미ACK spool로 추후 조사하며 source/승인 gate를 완화하지 않는다.

MA05a2 native/control 범위 완료: [인계](../validation/tasks/AI-LIVE-04-MA05A2.md), 관련157pass263.30s 후 visible ACK rename 보완의 영향73pass193.48s. 모델 turn 이전 오류는 위 MA05a3이며 전체 MA05/RX87은 미완료다.

## MA05a4 실행 체크리스트 · worker finish 없는 서버 종료

직접 선행: a1의 `finish_incomplete_recording`(source/승인 생성0)과 a2/a3의 ACK prefix 불변. 소유 코드 queue.reconcile_stored(현재 lost job/quarantine만 갱신)와 cancel_job(queued→cancelled)이다. 외부 PC·유료 키를 선행으로 요구하지 않는다.

- [ ] RED: 실제 브라우저 녹화 접수 후 queued 취소하면 worker/모델/native0, REC interrupted/stopped/stored/incomplete다. 등록 worker가 ACK before를 저장한 뒤 서버 fake-clock lease/session/runner 손실을 reconcile하면 같은 상태이고 PNG는 PC offline에 읽힌다.
- [ ] 서버가 job을 terminal로 바꾸는 같은 transaction에서 해당 project/job의 recording만 incomplete 종료한다. 다른 REC/승인/terminal 상태·기존 manifest/version/package는 바꾸지 않는다. queued 보존·live generation continue·quarantine/no-resume 규칙을 유지한다.
- [ ] 반복 reconcile/취소 receipt 재확인은 불변이다. terminal worker late finish는 오류 사실/서버 ACK metadata만 확인하며 새 source를 만들지 않는다. normal success와 trial/regression QA는 바뀌지 않는다.
- [ ] 실제 API/DB/fake-clock 집중 회귀, 한 fresh review/한 fix pass, 인계/큐/master commit. 실제 PC 종료 수용으로 표시하지 않는다.

MA05b 후속 UI: 실패본에 materialized version이 없을 때 기존 recording.html의 무조건 case/review 링크가 다른 최신/승인 후보를 가리키지 않도록 한다. 해당 실패의 타임라인·로그를 계속 읽고, 승인 대상 없음/재녹화 경로를 분명히 표시한다. 완전 저장본은 실제 후보 version으로 사후 검토·승인한 뒤 같은 package의 AI0 trial/regression 여정을 확인한다.

MA05a3 완료: [인계](../validation/tasks/AI-LIVE-04-MA05A3.md). 관련201pass/old expectation1fail 뒤 영향40pass, 추가 offline1pass. 다음 MA05a4이며 전체 MA05/RX87은 미완료다.
