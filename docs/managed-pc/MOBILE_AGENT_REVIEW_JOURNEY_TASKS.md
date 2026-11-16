# MA05b · 원본 저장본 검토·사후 승인·AI0 실행

Required: superpowers:executing-plans inline/TDD. Spec C05/C06와 기존 sample UI/검토·승인 계약을 유지한다. 직접 선행 MA05a1~4 인계, 범위별 소유 코드만 읽는다. 실제 키/기기를 선행으로 요구하지 않는다.

## MA05b1 · 저장된 녹화에 정확히 묶인 검토 UI

Confirmed gap: recording.html은 materialized_version_id가 없어도 case/review 링크를 보낸다. 실패 REC에는 새 source/version이 없으므로 링크가 다른 최신/기존 승인 후보를 열 수 있다. 현재 페이지에는 내부 package/compiler 설명과 raw completion code도 노출된다. 새 화면을 만들지 않고 기존 sample 기반 레이아웃/타임라인/키보드 흐름을 유지한다.

- [ ] RED: 정상 API+원본 main의 native/model 실패 뒤 저장본 페이지를 열면 다른 candidate/base 승인을 여는 링크가 없어야 한다. 해당 timeline/PNG/log와 케이스에서 명시 재녹화할 경로는 남는다. PC offline에서도 검토 내용 조회는 가능하다.
- [ ] 후보 version이 실제로 materialized된 경우만 그 exact version으로 검토 링크를 보낸다. 승인 가능 여부는 기존 package/complete/evidence/trial gate를 따른다. 실패본에 후보를 임의 생성하거나 오래된 version을 fallback으로 넣지 않는다.
- [ ] 상태/다음 행동을 사용자 용어로 표시하고 compiler/package 구현 설명은 사용자 흐름에서 제거한다. raw machine completion code는 data attribute/JSON 계약으로 유지해 polling/선택 행동이 깨지지 않게 한다.
- [ ] 정상 완료/미승인/실패/중단/진행 중과 offline을 확인한다. 기존 구성에서 세 폭 화면과 키보드 링크 이동을 검증한다. 기능/API·UI 영향 회귀, 한 fresh review/한 fix pass, 인계/큐/master commit.

## MA05b2 · 정상 source→검토→사후 승인→동일 package AI0

먼저 현재 source/check binding/evaluator/trial 준비 조건을 실제 코드로 대조한다. 원본 main이 만든 서버 manifest/package를 사용하고 fixture가 만든 별도 표시 코드/force approval로 갈아끼우지 않는다. 저장 후 browser review/실제 승인 API actor 이벤트와 같은 package ITEM/trial/regression의 deterministic native·actor AI0·healing OFF를 확인한다. 검증 AI는 승인된 지점/예산만 허용한다. 논리 check 소비가 미구현이면 B2.3b/C/D의 구체 구현 단위를 먼저 편성하며 외부 환경 대기로 숨기거나 assertion/승인 gate를 완화하지 않는다.

전체 MA05/RX87 완료는 별도 수용이다. 실제 paid/device/월3000건 비용은 최종 기능 뒤 독립 수용으로 남긴다.
