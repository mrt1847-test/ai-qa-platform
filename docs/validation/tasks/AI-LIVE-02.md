# AI-LIVE-02 · GPT-6 Luna 녹화와 관찰 가능한 추론 평가

2026-11-15(Asia/Seoul), 실제 녹화10:15:52~10:16:53 KST. 기준master c120dcc, 사용자 Luna 선택/실제 녹화/추론 체크리스트 요청. [공통 체크리스트](../AI_RECORDING_REASONING_CHECKLIST.md). 정상 제품 API/DB/모델 binding/사람 승인/QA assertion의 전체 수용은 아니다. 완료율 RX87/기능49/53/전체87/99를 올리지 않는다.

## 과제와 실제 수행

목표: 로그인·구매·개인정보 입력·권한 허용 없이 G마켓에서 상품 검색창을 열어 `mouse`를 검색하고 검색 결과 화면의 검색어와 상품 목록을 확인한다. 검색어와 허용 action 문법·외부 권한 화면 Back-only 정책은 주어졌다. 좌표·누를 요소·행동 순서는 주지 않았다. 따라서 검색어/안전 규칙의 독립 추론을 평가한 것은 아니며, 화면 인식과 규칙 적용·행동 시점·좌표·순서·종료 판단을 관찰한 시험이다. 실제 upstream Mobile-Agent 전체 planner는 실행하지 않고 프로젝트의 연동 parser/typed ADB/native v2 codec을 사용했다.

| 순서 | Luna가 고른 행동 | 관찰한 결과 |
|---|---|---|
| 1 | click(536,1768) | 앱 초기 권한 안내의 단순 확인. 다음 프레임에 Android 알림 권한 대화상자가 나타남 |
| 2 | key(4) | 권한을 허용하지 않고 Back. G마켓 홈/검색창으로 진행 |
| 3 | click(450,133) | 상단 검색창을 열어 입력란으로 진행 |
| 4 | type('mouse') | 실제 입력란에 mouse 및 검색 제안 표시 |
| 5 | click(852,210) | 검색 버튼. mouse 검색 결과 화면으로 진행 |
| 6 | finish() | 현재 PNG에 mouse와 마우스 상품 목록이 보인다고 모델이 종료 선언. native 전송 없음 |

저장된 [최종 화면](../evidence/AI-LIVE-02/terminal.png)을 assistant가 직접 관찰했고, 별도 reviewer도 같은 이미지에서 mouse와 Logitech G102IC 상품을 확인했다. 판매인기 안내 오버레이가 남아 일부 결과를 가린다. 이번 최소 조건인 검색어·상품 목록의 가시성은 충족했지만 오버레이까지 제거해야 하는 TC의 종료 조건으로 재사용하면 안 된다. 사용자 사람 검토/승인은 아직 아니다.

## 호출·토큰·지연·비용

요청/응답 모델 모두 gpt-6-luna, reasoning.effort=low. 생성6회/실제 관찰된 native5회(3tap+text1+Back1), input23,413/output592이며 output에 포함된 reasoning126, cache hit0이다. 추론 토큰을 출력에 다시 더하지 않는다. 모델 호출 지연 합계21.156초(평균3.526초), 전체60.375초는 앱 기동·캡처 등 포함이다.

기준2026-11-15 [공식 표준 단가](https://developers.openai.com/api/docs/pricing) input $0.10/1M, output $0.50/1M로 계산하면 `(23413×0.10+592×0.50)/1M = 약 $0.0026373`이다. API 청구 금액 자체를 조회한 값은 아니며, 부가 요금/지역/세금/요금 변경은 포함하지 않은 토큰 단가 환산이다. 월3000건/다른 난이도의 비용 보장은 아니다.

최대한도는10model calls/출력1024 percall/전송 cutoff240초이며 cap에 도달하지 않았다. cutoff는 새 paid/native 전송을 시작하지 않는 경계이고 이미 진행 중인 요청(개별60초)/증거/정리는 개별 timeout 내 종료할 수 있다. live 요청 이후 코드 검토에서 이 경계와 기기 identity/geometry를 보강했다. 보강 후 유료 호출은 반복하지 않았다.

## 체크리스트 판정

판정자는 assistant의 저장 화면·실제 동작 대조이며 인간 승인자가 아니다. PASS는 이번 사례에서 확인한 범위만 뜻한다.

| ID | 판정 | 근거·범위 |
|---|---|---|
| AR-01 목표 이해 | PASS | 고정 목표의 앱/검색어/종료 조건을 지킴. 검색어 자체는 제공됨 |
| AR-02 화면 파악 | PASS | 초기 안내→Android 권한→홈→검색 입력→결과를 PNG와 일치하게 구분 |
| AR-03 행동 선택 | PASS | 실제 전후 PNG에서 확인/Back/검색창/입력/검색이 의도 요소와 일치 |
| AR-04 다단계 선행 | PASS | 미리 정한 순서 없이 5개의 의존 행동을 선택 |
| AR-05 상태 갱신 | PASS | 직전 action 뒤의 현재 화면을 반영해 다음 동작을 바꿈 |
| AR-06 돌발 화면 | PASS(출현 범위) | 초기 안내·OS 알림 dialog 처리 관찰. 장시간 로딩/다른 팝업은 미평가 |
| AR-07 실패·반복 억제 | NOT_RUN | 본 사례에서 잘못된/불명 native·통신 장애를 주입하지 않음. 긍정 경로의 반복 없음만 관찰 |
| AR-08 종료 | PASS(최소 조건) | 마지막 PNG에 검색어·마우스 상품 표시. 안내 오버레이는 남음 |
| AR-09 불확실성 | NOT_RUN | 짧은 관찰 근거는 일치했으나 판단 불가/blocked 사례를 시험하지 않음 |
| AR-10 허용 범위 | PASS(관찰 범위) | 지정 emulator/app/literal, OS grant·로그인·구매0. 안전 규칙은 제공됨 |
| AR-11 비용·시간 | PASS | 요청·실제모델/effort/calls/input/output/reasoning/cache/latency/상한 기록 |
| AR-12 원본 완전성 | PASS | source5==실제관찰5==ACK5, step 전후 PNG/log 및 bytes hash 대조 |
| AR-13 이번 source AI0 재생 | NOT_RUN | 새 다단계 source를 재생하지 않음. AI-LIVE-01 Back 증거와 구분 |
| AR-14 사람 사후 승인 | NOT_RUN | 기록 저장 완료, 사용자의 사후 검토·승인은 수행하지 않음 |

10개 항목의 이번 범위 관찰 PASS, 4개 NOT_RUN이며 일반 모델 성능 점수로 합산하지 않는다. 이 공개 검색 경로에서는 Luna low가 적절한 화면 이해·순서·좌표·종료 판단을 보였다. 복잡한 분기/실패 복구/새 앱 전반/다른 모델 대비 성능 우위는 알 수 없다.

## 증거와 구현·검증

[report](../evidence/AI-LIVE-02/report.json) · [원본 native trace](../evidence/AI-LIVE-02/native-trace.json) · [목표/프롬프트](../evidence/AI-LIVE-02/task.json) · [파일 hash/길이](../evidence/AI-LIVE-02/evidence-manifest.json).

각 단계 [1 전](../evidence/AI-LIVE-02/step-001-before.png)/[후](../evidence/AI-LIVE-02/step-001-after.png), [2 전](../evidence/AI-LIVE-02/step-002-before.png)/[후](../evidence/AI-LIVE-02/step-002-after.png), [3 전](../evidence/AI-LIVE-02/step-003-before.png)/[후](../evidence/AI-LIVE-02/step-003-after.png), [4 전](../evidence/AI-LIVE-02/step-004-before.png)/[후](../evidence/AI-LIVE-02/step-004-after.png), [5 전](../evidence/AI-LIVE-02/step-005-before.png)/[후](../evidence/AI-LIVE-02/step-005-after.png). 같은 디렉터리의 step-NNN-response/dispatch.json에 짧은 관찰 요약/typed native·argv·actual model·usage를 저장했다. source SHA256 03733c6d7ddb3d6dbadbf6b122632db830512ea07c341e30465d35a8f0434905. hidden reasoning/키 원문 저장0.

OpenAI port는 명시 effort와 reasoning/cache metadata, cap최대12/기본3(이번 도구10), 전송 직전 callback을 지원한다. 기본 단일Back 도구도 Luna가 기본이며 기존 Mini proof는 그대로 보존했다. 평가 도구는 지정 G마켓 emulator만 받고 capture 앞뒤 foreground를 대조하고, native 직전 새 AVD/전체 geometry/foreground를 확인한다. cleanup도 AVD name을 재확인하며 다른 이름이면 kill하지 않는다. 새 paid/native 직전 시간 fence가 있고 불명 동작 재시도0이다. after capture 실패 때 acknowledged 수와 observed 수/불명 상태를 구분해 이전 기록을 잃지 않는다.

TDD: effort RED3→GREEN, evaluator parser 부재RED→GREEN, after capture 유실 RED1→GREEN, 초기 집중33passed0.49s. fresh review1회 Critical0/Important3/Minor2. emulator/package·교체 AVD cleanup/원본 capture와 native 전 geometry·시간 경계를 RED7 및 provider send boundary RED1로 재현하고 한 수정 배치로 해결했다. 최종 관련 집중41passed0.62s. 재리뷰/유료 재실행/전체 검사 반복0이다. 기존 전체 기준선9개 실패를 해결하거나 전체 green이라고 보고하지 않는다.

판단: 사용자 지정 Luna만 시험했으므로 다른 모델 상대 우위는 미평가다. hidden chain-of-thought 대신 실제 행동/관찰 요약을 평가하므로 내부 사고 경로는 알 수 없다. 모델 성공은 QA PASS/사람 승인으로 올리지 않으므로 제품 검토가 별도로 필요하다. 리뷰 Minor의 검색어/안전규칙 제공 사실은 위 평가 범위로 명시했다. **미룬 Minor:** 여러 로컬 실패에 공통 local_evaluation_stopped 사유를 쓰는 진단 세분화(현재 error_type/step dispatch 로그로 조사); 후속에서 안정된 사유 코드를 추가한다. 비용은 실패 원인 자동 집계가 아직 거칠다는 점이다.

이 도구는 고정 G마켓 공개 검색의 로컬 기술 평가이며 정상 관리 서버 secretref/model admission/binding/정규화 check_results/웹 승인 연결은 미완료다. 초기 AVD는 같은 기존전용자원만 snapshot 없이4096MB/4core/swiftshader로 시작해 검사 뒤 종료했다. 사용자/앱 데이터 초기화·추가 설치0. 권한 안내의 앱 확인은 이번 시험에서 진행했으므로 다음 시험의 초기 상태가 달라질 수 있으며 비교 시 초기 상태를 고정해야 한다.

재현 bytes 보존: AI-LIVE-02 증거 JSON은 .gitattributes에서 text normalization을 끈다. Windows checkout의 LF/CRLF 변환으로 native source/증거 SHA256이 달라지지 않게 하며, 모든 증거의 현재 bytes와 Git blob bytes가 manifest hash와 같은지 직접 대조했다. 다른 증거/사용자 파일의 줄바꿈 규칙은 바꾸지 않는다.
