# 실제 OpenAI 녹화·저장·AI 없는 재생 기술 시험

2026-11-15, master. 사용자 제공 로컬 env 키는 Git 제외 .review-work/ai-recording.env에만 둔다. 원문 출력/복제/로그0. 최초 키401 이후 수정 키는 GET /v1/models 200, gpt-5-mini 사용 가능. 이 작업은 기존 native-trace 변경 위에서 실행하며 사용자 metadata-load.md는 보존한다.

- [x] Responses API 전용 OpenAIProviderHttp: fixed TLS origin, image+geometry+instructions, store=false, no redirect/retry, call/output caps, typed completed text/usage만 반환. env 파일은 명시 읽기/중복 거절/셸 실행0. 작은 HTTP mock 집중 검사만 수행한다.
- [x] 전용 기존 AVD에서 실 AI 응답으로 비민감·짧은 동작을 결정하고 기존 Mobile-Agent parser/typed ADB driver로 실행한다. 전후 PNG/응답·native trace/토큰 메타데이터를 로컬 기술 시험 디렉터리에 저장한다. 로그인/구매/권한 부여/데이터 초기화0. 첫 시험 generation 최대3, 출력 최대2048/call; 401/429/timeout에는 자동 재시도0. AVD가 이미 켜져 있으면 새 실행으로 전원 간섭0.
- [x] 저장 trace를 재로딩/동일 geometry 검사 후 AI0으로 재생하고 실제 명령·호출 수를 기록한다. 로컬 기술 시험은 정식 API 접수/사람 승인/검증 PASS를 대신하지 않는다. 실제 모델 실패·응답 불명도 원문 키 없이 남긴다. 새 모듈/도구 집중 검사+실제 증거/인계, 기존 전체 검사 불필요 반복0. 기존 native-trace final review/commit은 별도 재개한다.

공식 근거: https://developers.openai.com/api/reference/resources/responses/methods/create 및 https://developers.openai.com/api/docs/guides/images-vision . 현재 키가 허용하는 모델 gpt-5-mini만 사용한다. 첫 실제 시험은 설정/앱 화면의 뒤로가기 등 가역 동작이며 상품/계정/외부 콘텐츠의 지시는 따르지 않는다. 정상 제품 runtime/factory/웹 OpenAI 등록은 이 smoke만으로 완료 처리하지 않는다.

실제 결과·제약·키 없는 증거: [AI-LIVE-01](../validation/tasks/AI-LIVE-01.md). actual1call/2409tokens/recordback1/replayback1/model0. source digest/단일 Back/native ACK와 부분 message 거절은 리뷰 후 검사로 보강했으며 유료 호출은 반복하지 않았다.
