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
