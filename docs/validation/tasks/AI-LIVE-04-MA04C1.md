# AI-LIVE-04-MA04C1 · 원본 runtime handler

2026-11-16 Asia/Seoul. BASEd99eb64 master. 전체 RX87·87/99·49/53 수 유지. actual original main+ASGI 서버와 모의 OpenAI/ADB/app launch, 실제 과금/기기0.

새 worker/mobile_agent_handler.py의 OriginalAndroidRecordingHandler는 기존 AndroidRecordingHandler의 context/gate/binder만 재사용하며 기존 계획 루프를 호출하지 않는다. exact pin/owner/case Android/serial·현재 remote fence·live capture·target preparer가 필요하다. runtime root/mobile-agent/project UUID/attempt UUID directory를 준비 전에 생성해 재시작 시 앱 준비도 반복하지 않는다.

선택 앱 준비는 최종 journal fsync 뒤 before_dispatch gate에서1회 charge한다. source에 넣는 녹화 native에는 남은 action/time budget만 배정한다. session의 before_native만 before_dispatch, before_model은 before_model, 나머지는 before_lookup으로 매핑한다. parent allowed는 local cancel/time/control.failed를 읽으며 IPC polling마다 HTTP를 보내거나 action을 중복 charge하지 않는다. 기존 runtime keepalive/checkpoint binder는 subclass를 인식한다.

AppPreparationFailed는 알려진 ACK 수와 서버 저장 IDs를 전달해 앱 준비 저장 직후 취소에도 사실을 보존한다. journal이 읽히지 않으면 unknown/quarantine을 보수적으로 유지한다. model port는 before artifact UUID를 검증해 immutable turn에 보관하고 session 별도 before_artifact_ids를 제공한다. HandlerResult는 준비+before+after/log/source IDs와 cursor·실제 ACK 수·source mapping을 finish에 전달한다.

중요한 producer 수정: wait/terminal은 전후 PNG/log/action row를 보존하되 physical event prefix를 늘리지 않는다. 이전 logical event pairs가 final_seq=2*native_count strict seal과 충돌해 fallback draft만 만들던 문제를 정상 finish 통합 검사로 확인했다. 서버 seal gate를 완화하거나 final prefix를 줄여 숨기지 않고 원본 event producer를 수정했다. wait/terminal은 source-v2 native 수와 분리된다.

초기 RED9(module missing)→8pass/1finish failure→native event producer 수정 후66pass132s. 준비 ACK 뒤 취소 RED1, unreadable journal RED1을 수정했다. 마지막 pre-review handler11+model14=25passed43.43s. 최종 리뷰/회귀 결과는 아래에 추가한다.

Ruling: 기록 버전은 creation_kind=recorded라는 임의 타입이 아니라 source_manifest_id/replay_package_id로 판별한다. 새 통합 검사는 저장 manifest/package/버전을 확인하되 자동 사람 승인을 만들지 않는다.

Ruling: 내부 handler 완성과 운영 접수 전환은 분리한다. 다음 MA04c2에서 operational factory가 이 handler를 선택하고 실제 supported source/protocol+현재 boot를 inventory에 보고하며 서버가 원본 engine pin을 접수한다. 기존 fixture/Web 흐름은 별도로 보존하며 일반 접수 전환은 아직 하지 않았다.

최종 fresh review Important7을 RED11로 확인하고 단일 fix pass를 적용했다. unknown cleanup은 일반 proof로 대체하지 않고 기기를 격리한다. 이전 owner의 preparer ACK는 scope/context가 다르면 반환하지 않는다. fallback failure evidence와 model-before 등록 후 fence 거절에도 확인된 IDs를 남긴다. child teardown의 kill/wait/close 예외는 known count/cursor/IDs와 cleanup_failed를 가진 정지 결과로 바꾸고 worker finish/cleanup까지 전달한다. 기존 attempt directory 충돌은 보수적으로 ambiguous이며, 첫 remote lookup 전부터 clock을 시작하고 instruction의 타입/빈값/16KB 한도도 준비 전에 검사한다. 새 통합22passed50.36s. 재리뷰0.

Final Ruling: 승인 상태 검사 의견은 Minor에서 Important로 올렸다. 자동 승인은 핵심 계약 위반이므로 approval_events=0을 DB로 확인한다. 기존 동작은 올바르며 coverage만 추가했다. deferred minor0.

Final Ruling: missing post-launch capture의 기존 ambiguous 분류는 보존했다. 확인된 failure evidence IDs는 저장하고 native를 재전송하지 않는다. 비용: 캡처 불가 시 launch를 수행했어도 보수적으로 격리하며 native ACK 수 개선은 별도 단위에서 다룬다. live/model/전체 RX87과 운영 등록은 C2/MA05로 분리한다.

최종 관련 회귀108passed182.10s: handler/session/process/model/target preparation/keepalive runtime/기존 RX73 cleanup/RX38 finish recovery. 전체 suite는 재실행하지 않았고 기존9개 baseline 실패 해결을 주장하지 않는다. 유료 모델/실제 기기0.
