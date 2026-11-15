# AI-LIVE-01 · 실제 OpenAI 단일 동작 녹화와 AI 없는 재생

2026-11-15(Asia/Seoul). 기술 시험 실행09:46:05~09:46:25 KST. 정상 제품 접수/DB/승인/QA assertion/다단계 자율 탐색의 수용이 아니다. RX87/RX23 상태·완료 수는 올리지 않는다.

## 실제 결과

- 사용자 로컬 파일 .review-work/ai-recording.env를 명시 읽었다. Git 제외이며 키 원문 출력/문서 복제0. 첫 수정 값은 모델 단일 조회404였고, 목록200에서 gpt-5-mini만 확인하여 키 무효로 오판하지 않았다. 생성 호출에 사용한 실제 모델 응답명 gpt-5-mini-2025-08-07.
- 기존 전용 Medium_Phone_API_36/emulator-5580만 snapshot 없이4096MB/4cores/swiftshader로 기동했다. boot SystemUI ANR에서 관찰한 Close app만 수동1회 눌렀다. 일반 사용자 기기/다른 AVD/설치 앱 데이터/권한/계정/구매 변경0이다. AVD config 변경0. 시험 후 이번 실행이 시작한 AVD만 종료한다.
- G마켓 com.ebay.kr.gmarket/.eBayKoreaGmarketActivity 기동/foreground 확인 뒤 실제 현재 PNG와 geometry/명시적인 한 번 뒤로가기 과제를 OpenAI Responses API에 보냈다. AI가 자유 탐색해 새 시나리오를 계획한 시험은 아니다. 현재 화면이 위험하면 finish()로 거절하도록 했다.
- 실제 OpenAI generation1회, input2387/output22/total2409 tokens. 반환 key(4)를 기존 Mobile-Agent 연동 action parser/typed ADB driver로 실행했다. native event v2를 로컬 파일에 먼저 저장했다. prompt/mock 응답을 대신 넣지 않았다. 실제 upstream Mobile-Agent 전체 planner 실행은 아니다.
- 저장 JSON을 다시 읽고 physical geometry를 대조한 뒤 같은 keyevent4를 재생했다. 기록/replay의 ADB argv가 같고 재생 AI0이다. 두 after PNG 모두 앱 권한 안내 위에 한 번 더 뒤로가면 종료된다는 toast가 관찰됐다. 확인/허용 버튼은 누르지 않았다.
- API 금액은 계측하지 않았고 토큰만 실측했다. 20달러 잔액/월3000건 비용 추정은 하지 않는다. 사후 사람 승인과 복수 step/check 결과 저장, 정상 서버 pin/binding 연결, Web 실제 모델 수용은 미완료다.

## 산출물과 재현

[report](../evidence/AI-LIVE-01/report.json), [모델 응답](../evidence/AI-LIVE-01/model-response.json), [재로딩한 native trace](../evidence/AI-LIVE-01/native-trace.json). [녹화 전](../evidence/AI-LIVE-01/record-before.png) / [녹화 후](../evidence/AI-LIVE-01/record-after.png), [재생 전](../evidence/AI-LIVE-01/replay-before.png) / [재생 후](../evidence/AI-LIVE-01/replay-after.png).

실행 도구 tools/android_openai_smoke.py의 --adb/--serial/--avd/--package/--key-file/--output 인자는 명시 값이다. --output은 새 디렉터리만 허용하여 불명 전송의 자동 resume을 하지 않는다. 키는 --key-file 경로로 전달하고 argv에 원문을 넣지 않는다. OpenAIProviderHttp는 생성 최대3(이번 실행1), output16..2048(실제요청1024), TLS 고정 origin/redirect0/retry0, 401/429/timeout/불명 응답 후 인스턴스를 중단한다. 이 작은 포트를 정상 관리 서버 factory에 연결한 것은 아니다.

집중 검사: tests/unit/test_openai_http.py 11passed0.34s. native-trace의 이전 전체9failed1014passed1skipped495.35s는 앞 코드 배치의 결과이며 새 OpenAI 모듈 전체 검사로 표현하지 않는다. 이번에는 관련 집중 검사와 실제 기기/모델 관찰만 수행한다. 증거는 raw credential을 포함하지 않는다.

공식 구현 근거: [Responses](https://developers.openai.com/api/reference/resources/responses/methods/create), [image input](https://developers.openai.com/api/docs/guides/images-vision). 다음은 이 직접 호출을 정상 서버의 비밀 참조/model binding/usage admission과 연결하고 다단계 일반 시나리오를 수용하는 것이다.

리뷰 보완: OpenAI response의 top-level completed만이 아니라 assistant message의 명시 incomplete도 거절한다. smoke는 저장 시 계산한 원본 bytes hash와 정확히 하나의 Back을 재생 전에 확인하고 양쪽 native1/acknowledged를 필수로 한다. RED12(앞 native 배치 포함)→집중102passed57.24s. 실제 AI 호출은 보완 전 위1회이며 유료 재검사는 하지 않았다. 이 변경은 별도 정상 모델 연결 완료를 뜻하지 않는다.

추가 영향 검증: 고정 case metadata·recording pin·모델 admission·observation 관련 회귀99passed81.80s. 이번 변경 뒤 전체 재실행은 하지 않았으므로 전체 결과는 앞 baseline과 구분한다.
