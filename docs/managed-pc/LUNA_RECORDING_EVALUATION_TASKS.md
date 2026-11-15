# Luna 실제 녹화·관찰 가능한 추론 평가

2026-11-15, master c120dcc. 사용자 Luna 선택과 실제 녹화/추론 체크리스트 요청에 따라 직접 구현한다. GET models200에서 gpt-6-luna 노출을 확인했고 mini는 더 이상 노출되지 않았다. env 파일1개 항목의 원문 키는 출력/문서/argv0이다. 기존 metadata-load.md와 test_rx_47.py dirty는 손대거나 커밋하지 않는다.

설계: 기존 OpenAI Responses port에 명시 reasoning_effort=low(지원 none/low 포함), 호출 cap<=12/기본3, 실제 reasoning/cache 토큰 metadata를 더한다. 별도 opt-in 평가 도구는 단일 Back 정답을 주입하지 않고 자연어 목표로 PNG→짧은 관찰/다음 action/완료 근거 JSON을 최대10회 요청한다. 기존 Mobile-Agent 호환 parser/typed ADB/원본 native v2와 단계별 전후 PNG/log를 재사용한다. 실제 upstream 전체 Mobile-Agent planner/정상 서버 승인/QA 수용 완료로 표현하지 않는다.

기본 과제: G마켓에서 로그인/구매/권한 허용 없이 상품 검색창을 열고 ASCII mouse 검색 결과를 확인한다. 앱 초기 권한 안내의 단순 확인은 허용하되 Android 권한 dialog나 외부 package에서는 좌표 tap/type를 허용하지 않고 Back/명시 blocked만 허용한다. 사용자 데이터/앱 초기화/설치 변경0. 출력 schema/typedallowlist/geometry/literal gate, before fsync→planned→native1/no-retry→after screenshot 순서다. 모델 finish는 성과 claim이지 QA PASS가 아니며 실제 스크린샷 대조로 판정한다. 저장 후 사람 검토는 미실행으로 남긴다.

- [x] 1 reusable 추론 평가 체크리스트와 ID/근거/판정 규칙. 정답 동작을 미리 주지 않음, 목표이해/화면연결/다단계/상태갱신/헛클릭/종료판단/안전·비용/저장·재생 분리, 미실행을 PASS로 세지 않는다.
- [x] 2 port effort/usage/cap와 평가 response parser/외부package action gate/중복동작·시간/ACK·저장 source pin의 작은 집중 TDD. 실패 원문/키 출력0, 오류/429 자동 재시도0. 단일Back도구와 기존포트 기본값 회귀를 확인하고 전체 검사 반복0.
- [x] 3 dedicated AVD actual Luna low 평가 최대10generation×출력1024, 시간240초. 성공/실패/차단 근거 PNG/log/토큰/모델/effort/latency를 남긴다. 앱 안내 허용 범위를 넘어가면 중단하며 자동 추가비용/모델fallback/개인계정 사용0. 저장한 새 다단계 trace 재생은 별도 승인/정식 연결 후속으로 남긴다.
- [x] 4 체크리스트 실제 판정·인계/NEXT/소유계약/로컬master커밋. fresh final review1회·필수 수정1회, 전체 제품 수용으로 완료율 올리지 않는다. 이 평가 결과와 소프트웨어 검사는 분리한다.

Ruling: 선택 모델은 사용자 지정 Luna이며 다른 모델과의 유료 비교는 하지 않는다. 비용: 실패 때 상위모델의 상대우위는 알 수 없다. Ruling: hidden chain-of-thought는 요구/저장하지 않고 짧은 의사결정 근거와 실제 상태변화로 평가한다. 비용: 내부 추론 경로 자체는 평가하지 않는다. Ruling: 모델 자체 성공 선언은 자동 assertion/인간 승인으로 승격하지 않는다. 비용: 최종 검토가 추가로 필요하다.

실제 결과·체크리스트/리뷰·미룬 Minor/재현 범위: [인계 AI-LIVE-02](../validation/tasks/AI-LIVE-02.md). cutoff는 새 send 경계이고 이미 시작한 I/O·증거/정리는 개별 timeout 내 drain한다. 정상 서버 OpenAI 공급자/새 다단계 재생/사람 승인은 계속 미완료다.
