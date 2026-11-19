# Android Assertion과 재생 로딩 수정

사용자가 2026-11-19 두 문제의 즉시 수정을 요청했다. 기존 질문 생략 지시와 직전 확인 결과를 기준으로 실행하며, 새 승인 UI나 영상 저장 기능은 추가하지 않는다.

## 선택한 방향

기존 recorded_replay, check binding, 모델 broker와 evidence ACK를 확장한다. 원본 Mobile-Agent main을 재생 때 다시 호출하면 비용·동작 불변성이 깨지고, 고정 sleep만 늘리면 로딩을 판별하지 못하므로 사용하지 않는다.

- 녹화 Assertion은 원본 목표에 전달한다. 재생 Assertion은 고정 case version의 별도 check로 평가하고 결과·근거를 저장한다. authoring 성공을 QA PASS로 쓰지 않는다.
- 명시 resource와 경계가 있는 text/state는 공통 hierarchy reader로 실제 비교한다. 자연어 화면 검증은 명시 verification binding으로 현재 증거 이미지에 대해 AI 판단을 요청한다. 미설정·관찰 불가·모호함·취소는 unknown이며 위반을 재시도로 지우지 않는다.
- 모든 required check 결과가 충족되고 동작·증거가 완결된 경우만 PASS다. 위반은 FAIL, 빠진 평가는 INCONCLUSIVE다. normalized check_results와 ITEM 결과를 연결한다.
- 새 녹화 native source에 실제 동작 전 화면의 대상 조건과 녹화 중 wait를 함께 저장한다. 재생은 현재 대상 조건을 제한 시간 동안 read-only로 확인한 뒤 한 번만 입력을 보낸다. 후 화면 안정화와 검증 시점 관찰도 총 deadline·취소를 따른다.
- 화면 안정화만으로 기대 결과 충족을 추정하지 않는다. 일반 대기와 최종 Assertion을 분리한다. old source는 기존 좌표 의미를 보존하며 근거 없는 새 조건을 만들어 넣지 않는다.

## 제약과 검증

모델 키는 서버에 유지하고 check별 명시 정책/현재 lease/선택 package/ACK 증거를 확인한다. 같은 요청 재확인에 입력·모델을 재실행하지 않는다. 기존 source/승인/FAIL을 수정하지 않는다. 로딩 지연·timeout·취소, 잘못된 경계·대상·교차 프로젝트, PASS/FAIL/unknown·결과 영속화를 fixture로 먼저 재현한다. 기존 실제 영상은 과거 실행 근거로 유지하며 수정 후 실행인 것처럼 바꾸지 않는다.
