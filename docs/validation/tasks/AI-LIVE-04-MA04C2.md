# AI-LIVE-04-MA04C2 · 운영 원본 handler 등록과 접수

2026-11-17 Asia/Seoul. BASE040867d master. 전체 RX87·87/99·49/53는 유지한다. 실제 모델/기기 호출0, actual upstream main/정상 API와 mock OpenAI/ADB/app launch다.

운영 Android factory는 OriginalAndroidRecordingHandler를 반환하고 기존 자체 plan_provider를 연결하지 않는다. startup과 각 handler의 준비 전 pinned public source를 검증한다. 실제 recording route가 이 handler이며 adapter가 준비된 경우만 inventory.permissions에 exact authoring_engine과 authoring_engine_boot_id를 보고한다. worker runtime이 이 정보를 HTTPS inventory에 넣고 미지원 route나 Web·source 오류에서는 오해 가능한 engine metadata를 제거한다. 기존 inventory JSON 확장이며 DB schema와 credential 흐름은 바꾸지 않는다.

서버 engine_for_recording은 선택 project/physical resource의 ready inventory, worker 현재 presence boot, exact source/protocol ref와 같은 immutable binding revision의 provider/model/endpoint를 대조한다. Android 원본 녹화는 OpenAI gpt-6-luna 공식 endpoint가 필요하다. engine은 browser 입력에서 받지 않고 frozen limits/policy hash에 넣는다. REC와 rerecord 모두 선택 resource를 소비하고 동일 request 재호출은 이전 pin을 보존한다. 명시 fixture adapter+fixture binding과 Web은 별도 unmarked 경로를 유지한다. 실제 원본 worker에 fixture model을 연결해 암묵적 성공을 만들지 않는다.

녹화 준비 preview도 같은 engine admission helper로 차단 사유를 반환한다. resource/authoring 자체가 막혔으면 중복 engine 사유를 줄인다. 처음13pass17.69s, preview/준비 전 source drift RED2 보완 뒤 admission18+기존 RX97 pin17=35pass37.64s. 새 실제 runtime cycle은 fixture의 미리 ACK된 작업을 쓰지 않고 real worker ACK→keepalive→원본 main→finish/cleanup까지 실행해 manifest/package와 approval_events=0을 확인했다. 실제 사람 승인/기기/유료 호출이나 배포 완료를 뜻하지 않는다.

Ruling: 새 capability는 기존 permissions JSON에 현재 boot와 함께 보고한다. 비용: 구버전 operational worker는 이 정보를 보고하지 않으므로 실제 원본 녹화 접수가 거절되고 새 worker/지원 보고가 필요하다. 기존 queued marker 없는 작업을 새 handler가 자체 계획 루프로 대체하지 않는다.

Ruling: explicit fixture와 Web은 기존 경로를 보존한다. 비용: fixture 성공은 실제 Mobile-Agent/OpenAI 수용이 아니며 사용자 판단과 비용 측정에 혼용하면 안 된다. 서버 key는 기존 secret resolver에만 있고 worker/child에 원문을 보내지 않는다.

최종 review/fix/회귀 결과는 아래에 추가한다. 다음 MA05 저장본 검토·사후 사람 승인·승인본 AI0 실행과 남은 RX87 logical check 소비/평가·제한 healing/UI다. 월3000건 비용은 최종 수용 뒤 별도다.

최종 리뷰 보완: Critical1(다른 PC가 선택 PC의 작업을 가져가는 경로)·Important8을 수용했다. marker가 있거나 새 Android authoring pin인 녹화는 lease 할당 전에 선택 physical owner와 현재 authenticated report를 대조한다. 동일 emulator-5554라는 문자열은 PC 신원이 아니다. 보고는 recording credential·project·worker·boot·session에 서버가 서명 대신 trusted metadata stamp를 붙이며, probe-only나 client가 작성한 authoring_report를 신뢰하지 않는다. credential 만료와 같은 boot 재접속 새 session도 거절한다. engine 없는 보고를 fixture로 추정하지 않고 실제 FixtureAndroidRecordingHandler의 affirmative fixture report가 필요하다. source unavailable은 recording만 비활성화하며 나머지 worker route는 생성한다.

실제 API 경계: WorkerRuntime heartbeat는 서버의 boot/session을 받고 inventory에 현재 incarnation을 전달한다. 서버는 report authority를 덮어쓰며 current project alias와 active recording credential까지 검사한다. 일반 REC/rerecord/repair-adoption/preview가 실제 gateway와 가격 모드를 metadata로 전달한다. fixture gateway 또는 strict unknown quote는 새 원본 녹화를 차단하며 예전 accepted idempotency pin은 보존한다. immutable 저장 입력의 민감 참조·준비 포함 최소2 native·server goal/literal 한도를 같은 pure 함수로 미리 검사한다. key 값은 읽지 않는다.

Settings UI는 공식 OpenAI endpoint를 openai provider로 저장하고 같은 기존 endpoint의 provider를 보존한다. canonical endpoint 판정은 모델 send 경계와 공유해 trailing slash를 허용한다. model/provider/price 차단은 Settings, device/capability는 Environments, input은 케이스 링크로 안내한다. Minor href 의견은 필수 readiness 보완과 함께 처리했다. Target SecretRef negative가 드러낸 기존 secret_revisions 오조회는 실제 available secret_refs metadata 조회로 수정했다.

검증: marker/serial/claim을 조작하지 않은 새 public-API fixture로 secret/binding/case→두 UUID worker enrollment/인증 heartbeat/inventory→browser start→true claim→keepalive→원본 main→finish/cleanup을 확인했다. 다른 PC의 같은 emulator serial claim 거절, source/probe/session/credential/project alias·actual gateway/strict price·input 제약·UI provider·미승인 저장을 검사했다. 내부 original fixture도 실제 Android input과 authenticated capability/사전 OpenAI gateway를 사용하며 강제 engine pin을 제거했다. 컴포넌트 fixture는 명시 모의 report를 생성한다. 집중106passed161.87s. 실제 기기TC106건 또는 유료 모델 수용이 아니다.

Ruling: capability stamp는 기존 global inventory JSON을 사용하되 project·recording token·worker incarnation을 모두 대조한다. 비용: 동일 worker ID를 여러 프로젝트 alias에 공유하면 선택 프로젝트의 현재 authenticated report가 필요하며 다른 프로젝트의 report를 재사용하지 않는다. 서버 schema는 추가하지 않았다.

Ruling: source 누락 시 worker 전체 startup을 막지 않는다. 비용: device 자체 ready와 authoring available은 구분되며 원본 녹화는 support report/preview에서 차단된다. 권한/키/가격·target coverage gate는 지우지 않는다.

Ruling: 실제 paid/device/독립 host·wheel-only distribution 수용은 이 테스트의 근거가 아니다. editable source checkout의 source 누락은 위 경로로 처리한다. 기존 전체 회귀 결과와 저장본 승인/AI0 수용은 별도 기록한다. 재리뷰0, deferred minor0.

전체/후속 회귀: 첫 전체 실행15failed1393passed1skipped1031.50s로 기존9외6개를 확인했다. 후속 영향 경로53passed44.99s로 README의 예전 상태/명령 literal 기대, 명시 fixture report 누락(RX71/77/RX47), builder의 missing-case 사유를 보완했다. 새 original 핸들러도 case_context_invalid를 보존한다. observation import 부작용 검사는 canonical 모듈을 reload하지 않고 임시 모듈명으로 실제 source를 로드해 다른 guard exception identity를 바꾸지 않는다. 순서 회귀32passed5.46s는 새 native-frame 실패와 기존 RX12/34/48 세 간섭 실패가 해소됨을 확인한다. 생산 sanitizer/geometry guard는 완화하지 않았다. 전체 suite는 다시 실행하지 않았으므로 전체 green을 주장하지 않는다. 남은 기존6개는 baseline 문서를 따른다. metadata-load.md 자동 보고서는 보존/커밋 제외한다.

확인한 다음 기능 공백: failure original native는 local journal/quarantine은 보존하지만 서버 녹화가 open/running, ma-before action이 observed로 남고 remote failure log가 없다. 이 부분을 정상 성공 경로 완료로 확대하지 않는다. 다음 [MA05a](../../managed-pc/MOBILE_AGENT_FAILURE_EVIDENCE_TASKS.md)에서 저장 상태/typed failure log/unknown history 차단을 구현한다. 사람 승인/최종 QA 수용은 아직 미완료다.
