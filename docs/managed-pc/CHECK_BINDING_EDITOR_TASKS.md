# RX87 B2.3b2 · 녹화 검증 연결 편집 UI와 정확한 후보 검토

2026-11-15 master f7cb466. 선행 B2.3b1 storage/API 완료 인계. 원본·기존 승인/FAIL/초기 샘플 UI 계층은 보존한다. API keys/device/실 모델 없이 임시 DB와 UI로 구현한다. 사용자 dirty metadata-load.md/test_rx_47.py 제외.

설계: 녹화 상세 페이지에서 source logical step마다 native 동작 이후 시점을 선택하고 고급 details에서 선택 package resource ID를 입력한다. 최종 검증은 마지막 동작 이후라는 뜻을 명시한다. 입력 미지정은 자동 PASS가 아니며, 현 단계는 연결 저장만 가능하고 runtime 적용은 후속임을 알린다. 기존 aiqaForms/CSRF/request·페이지 메모리 dirty·ACK 유실 retry를 재사용한다. 증거는 새 탭으로 열어 편집을 보존한다.

- [x] 1 저장 receipt에 새 manifest hash를 명시해 응답 이후 사용자 추가 편집을 보존하며 다음 CAS를 고정한다. 서버 rendering에 유효 context/미지원 사유·실제 materialized version을 연결하고 해당 version의 승인 여부만 표시한다. 원래 case current approval을 새 candidate 승인으로 표시하지 않는다.
- [x] 2 source ID/텍스트를 안전하게 렌더하는 작은 폼/JS. source order client validation/선택 resource syntax, explicit 새후보 저장/버전 링크/저장응답불명 같은key확인, dirty editing 중 polling reload0. 409에서 입력 유지/서버값 비교/명시 최신 pin 선택; 다른 input version/native identities면 자동 재적용0.
- [x] 3 ?version=UUID 검토 링크를 project/case/version exact 조회에 연결하고 board/readiness/decision/protection 모두 같은 version. unknown/foreign version404, latest fallback0. 기존 default latest 흐름은 유지한다. 승인·시범을 자동 생성하지 않는다.
- [x] 4 UI·API/JS 부정/동작 검사와 가능한 실제 브라우저 키보드/3폭 확인, focused review journey 회귀, fresh review1/필수 TDD수정1pass·계약/인계/큐/master commit. 전체 검사 무변경 반복0. runtime check 소비/b3/c는 다음이다. 1024·1440에서 선택·저장 버튼이 보였고, 저장 후 검토 링크의 version에서 승인 버튼은 비활성이었다. Tab은 페이지 처음으로 이동했다.

Ruling: native evidence는 새 탭으로 조회 — polling이나 선택 변화로 입력을 잃지 않기 위해서 — 비용: 두 탭을 오가야 한다. Ruling: source-compatible 충돌만 명시 pin 갱신으로 재적용 — 다른 원본의 좌표/expected로 잘못 저장하지 않기 위해서 — 비용: 구조가 바뀌면 사용자가 새 폼에서 다시 선택한다. Ruling: 후보 검토 URL의 version을 실제 decision/protection까지 전파 — 최신 version으로 조용히 바뀌는 승인을 막기 위해서 — 비용: legacy helper에 optional version argument가 추가된다.
