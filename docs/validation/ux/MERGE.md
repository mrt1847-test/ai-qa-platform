# UI 작업본과 최신 master 통합

2026-11-01 · 사용자 요청: “해당 작업본 머지 해줘”.

UI 작업 `3f9247f`와 최신 master `fa856ad`를 통합한다. UI 시작 당시 실제 파일 스냅샷은 `232ea88`이다. Git상의 이전 공통 조상 `5ff4e52`만 사용하면 양쪽에서 따로 커밋한 기존 구현이 add/add 충돌로 나타나므로, 실제 스냅샷을 명시한 3-way tree로 중복 이력과 실제 변경을 구분했다. 최종 통합 커밋은 두 브랜치 이력을 모두 보존한다.

## 보존과 충돌 해결

- master의 새 마이그레이션, healing·suite·보고·보관·백업 구현과 TASK_INDEX는 그대로 보존했다. NEXT_ACTION/WORK_PROGRESS의 완료126/163·준비된 Current 없음 상태를 유지했다.
- 실행 접수는 master의 다중 ITEM 원자적 저장과 모든 ITEM/job receipt 반환을 유지한다. UI의 dataset/entry hash, 저장 한도·환경·기기·데이터·버전 고정값과 durable receipt 우선 확인을 결합했다. 새 요청은 ready/대상 일치와 승인·패키지·미리보기 고정값을 재검사한다. 응답을 잃은 기존 요청은 기기 상태가 바뀌어도 저장 receipt를 돌려준다.
- 단일 시범 화면은 실제 저장본 선택·검사·접수 UI를 유지하고, 최신 목적·다중 전개·치유 제한 안내를 결합했다. 시범 healing은 비활성 OFF이며 정식 수행의 승인/명시 허용과 구분한다.
- 설정의 실제 모델 연결 편집/키 보호 UI와 최신 저장소 보관 안내를 함께 유지했다. 증거 화면의 확대·이동·전체보기와 “없는 캡처를 모델 그림으로 대체하지 않음” 안내를 보존했다.
- W20 fixture에 실제 ready inventory를 추가하고, 화면 시험은 존재하는 케이스를 만든 뒤 조회하도록 수정했다. W21의 두 `_count`가 서로 덮어쓰던 테스트 결함은 SQL 조회 도우미 이름을 분리했다. W23 기존 수용 문구인 미사용/불명 구분을 리포트에 복원했다.
- 전체 시험에서 같은 시각의 시범 UUID 순서에 따라 준비 상태가 healing ON 항목을 고르던 결함을 발견했다. UUID 순서를 고정한 시험으로 실패를 재현한 뒤, 같은 버전의 치유 OFF 시범을 우선하고 검토 snapshot이 있으면 그 정확한 시범을 유지하도록 수정했다. 이전 버전이 pin된 경우 stale 차단은 유지한다. 접수된 결정적 재생의 actor=0도 명시한다. 관련 검토·승인·접수12개 회귀가 통과했다.

## 통합 검증

최종 전체 Python 시험은 **241 passed, 1 deselected (170.95초)**, Node 제어 회귀는 **21 passed**다. 실제 Hyper-V가 필요한 `test_w01_02`만 기존대로 제외했다. 첫 실행의 저장소 내부 basetemp는 경로 독립성 시험 3개를 위반했으므로, 최종 전체 실행은 저장소 밖의 고유 임시 디렉터리를 사용했다. 제품의 경로 검사를 완화하지 않았다.

검증 명령: `python -m pytest -q -k 'not test_w01_02' --basetemp <저장소 밖 고유 임시 경로>`, 기존8개 `tests/web/*.test.cjs`의 `node --test`, `node --check src/aiqa/web/static/execution_setup.js`, `git diff --cached --check master`. UX 문서 링크 누락0개. 전체 시험 로그는 로컬 `.review-work/merge-verified-pytest.log`, Node는 `.review-work/merge-final-node.log`다. 최신 master에 원래 있던 두 테스트 파일의 EOF 빈 줄은 이번 UI 통합 범위 밖이라 보존했다.

독립 UI 작업의199개 Python/21개 Node 기록과 통합 후의 결과를 혼동하지 않는다. 실제 기기·모델·독립 사용자 수용은 이번 병합으로 완료하지 않으며 원격 push/설치/배포도 포함하지 않는다.
