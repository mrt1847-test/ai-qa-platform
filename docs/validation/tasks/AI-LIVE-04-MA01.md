# AI-LIVE-04-MA01 · 정상 앱의 명시 OpenAI provider 선택

2026-11-15 Asia/Seoul, 기준master6ab54c0. 정상 create_app/settings/factory가 명시 openai 모드를 선택하고 서버 secret resolver/gateway를 거쳐 OpenAI Responses 프로토콜로 전송하는 배선을 구현했다. 실제 유료 API/기기 호출0이며 HTTP는 MockTransport다. upstream worker/정상 녹화 수용 완료가 아니다. AI-LIVE-03 실제 증거를 재시험하지 않았고 RX 완료 수를 올리지 않는다.

## 동작과 파일

config.py ModelProviderSettings/load_settings: AIQA_MODEL_PROVIDER_MODE=openai를 명시한 경우만 새 서버 포트를 고른다. 기본fixture/기존operational 동작을 유지한다. origin=https://api.openai.com, path=/v1/responses, HTTPX public CA 검증/trust_env=False, timeout 유한0초초과60초이하. 임의 origin/path/TLS 해제/CA override는 거절한다. 키를 env 파일이나 factory에서 읽지 않으며 기존 서버 비밀 참조로 받은 값만 각 호출에 전달한다.

models/openai_server.py: 기존 bounded OpenAIProviderHttp를 요청마다 max_calls1로 새로 생성한다. API 프로세스 전체에12회 한도가 누적되지 않는다. 실패 시 자동 retry/fallback0. 요청 단위 실제 send count를 thread-safe 역할 counter로 누적하며 키/요청 내용/거절된 임의 역할 문자열을 state에 보존하지 않는다. 독립13회/서로 다른 자격 증명 동시 호출은 검증했다.

models/openai_http.py: 기존 CLI 기본60초를 보존하면서 실제 설정 timeout을 HTTP client에 전달한다. 서버가 허용한 maintenance 역할도 보존한다. 기존 observation/hash/phase/usage/response latching을 재사용한다.

provider_http.py의 ProviderHttpError는 provider_dispatched=None(기존/불명)·False(전송 전)·True(전송 시도)를 구분할 수 있다. server port는 실제 child call_count로 지정하고 broker.py gateway는 명시False의 로컬 오류를 차감하지 않는다. 실제503/timeout/불명·기존 provider의 None은 보수적으로 차감한다. 잘못된 출력 한도8을 거절한 뒤 정상 요청을 보낼 수 있고 실제 실패로 예산1을 썼다면 다음 요청은 거절한다.

## 검사와 리뷰

TDD초기4실패/9통과: openai 모드 미지원으로 정상 factory/13독립호출/독립 오류/전송 전 취소가 실패했다. 구현 후42통과. 정상 앱 factory→서버 secret→gateway 중복키/예산 경계와 기존 RX45를 포함한47통과2.93s. Fresh review1회 Critical0/Important3/Minor3. 실제 gateway에서 전송 전 차감·maintenance 거절 RED2/2통과를 재현한 뒤 수정, 관련50passed4.78s. 재리뷰0. 추가 권한·이미지/원본 호환 회귀 결과는 아래 재개 검증 절에 기록한다. 기존 전체9개 실패는 별도 기준선이며 전체 green으로 보고하지 않는다.

중요1/2는 코드 수정했다. 중요3의 system-root 문구는 구현 의도와 달라 HTTPX 기본 public CA 검증으로 바로잡았다. TLS 검증을 끄거나 Windows 신뢰 저장소를 새로 설치하지 않았다. 실제 callback의 최종 권한 경계와 token 정산은 MA02이며 현재 정상 recording endpoint는 openai kind를 fail-closed로 거절한다. 이 점을 녹화 기능 연결 완료라고 확대하지 않는다.

## 결정·보류·다음

Ruling: complete_path None은 constructor의 기본 표식이고 fixture/operational은 기존 /v1/complete, openai는 /v1/responses로 정규화한다. 명시 env의 잘못된 경로는 거절한다. 비용: direct None은 이제 기본값을 뜻한다.

Ruling: 시스템 root라고 한 초기 설명을 HTTPX public CA/trust_env=False로 수정한다. 비용: 사내 private CA/root override는 이 모드에서 지원하지 않는다; 기존 operational은 유지한다.

Ruling: 녹화 endpoint grant/실제 usage 영속화/최종 HTTP fence/upstream IPC는 MA02~05에 남긴다. 현재 정상 녹화는 provider_unavailable로 차단되므로 이 commit만으로 upstream 웹 녹화가 가능하다고 쓰지 않는다. 비용: 사용자 여정은 다음 연결 단위가 필요하다.

미룬 Minor: 환경변수의 origin 뒤 여러 slash는 loader가 제거해 direct constructor와 진단이 다를 수 있으나 실제 outbound는 고정origin이다. 다른 actual_model/유효 observation을 새 server wrapper에서 직접 검사하는 추가 handoff coverage는 보류했다(하위 포트 유효 image 검사는 보존). zero counter entry 문제는 전송 전 오류의 실제 차감만 기록하는 수정에 함께 해결했다.

다음 MA02a: 정상 recording grant에 openai provider/HTTPS endpoint를 정확히 묶고, 실제 HTTP send 직전에 현재 권한을 재검사한다. MA02b: input/output/reasoning/cache와 unknown의 정확한 저장·재시도 receipt를 구현한다. 가격/월3000건 계측은 필수 기능 뒤다.

재개 검증: RX98 정상 녹화 authoring·RX99 PNG 관찰·원본 Mobile-Agent/session 호환93passed89.89s. 새로운 유료 호출/기기 호출0. 원본94개 관련 검사와 이번50/93개는 소프트웨어 회귀 수이며 실제 앱 TC 수가 아니다.
