# 클라우드 기본 배치 정정 검토

2026-11-02 · 기준 구현 `684daef`. 이번 변경은 설계·큐·작업 색인 문서만 수정한다. CF-01 조사나 cloud 제품 구현 완료가 아니다.

## 정정한 계약

- 사용자는 관리 사이트에 접속하고 서비스 worker가 cloud browser/device-farm Android를 제어한다. 고객 PC worker/ADB/VM을 요구하지 않는다.
- 기존 local emulator·AD-01은 개발 근거로 보존한다. AD-02~04는 development_only, UX-01~03은 product_shared다. 기존 W/AD/UX 상태는 변경하지 않았다.
- DESIGN/UI_SPEC/DATA_DESIGN/실행 spec/CONTRACTS와 계획·진행표에 최신 배치 우선권을 반영했다. 자원 선택·증거 보관·다른 PC 재접속·서버 인증/저장·session 정리/비용을 포함한다.
- NEXT_ACTION Current는 읽기 전용 CF-01이다. 공급자 능력/실제 두 엔진 hook을 공식 자료·고정 source로 대조하고 후속 구현 카드를 확정한다. 자격이 막히면 독립 UX 후보로 진행하며 로컬 PC 설치 경로로 돌아가지 않는다.

## 문서 검증

로컬 Python으로 세 JSON 색인을 결합해 중복 ID·누락 선행·순환·기존 상태 변화·Current 준비 조건·문서 링크를 검사했다.

- PASS: 171 unique IDs(기존 W163 + AD/UX7 + CF1), 선행 참조 존재, DAG 순환0.
- PASS: HEAD 기준 기존 W 및 AD/UX의 모든 상태 동일. W 완료126/163, AD-01 완료 보존.
- PASS: CF-01·독립 UX-01의 직접 선행 complete 및 인계 파일 존재.
- PASS: 변경 Markdown의 로컬 링크 대상 파일 존재, CF-01 명시 anchor와 Current 일치, 변경 JSON 파싱 성공.
- PASS: 변경 파일은 Markdown/JSON뿐이며 `git diff --check` 통과.

현재 공급자 미선정이다. 공식 공급자 능력 조사·실제 세션·모델 호출·과금·중앙 배포를 이번 검증으로 주장하지 않는다. 제품 코드 변경이 없어 제품 pytest는 재실행하지 않았다. 기존269개 시험 결과는 AD-01의 로컬 baseline 이력으로만 유지한다.

[최신 규범](../../superpowers/specs/2026-11-02-cloud-execution-scope.md) · [CF-01 카드](../../superpowers/plans/2026-11-02-cloud-execution-transition.md#cf-01) · [실행 큐](../../../NEXT_ACTION.md)
