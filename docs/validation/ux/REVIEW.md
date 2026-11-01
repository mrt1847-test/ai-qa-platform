# 최종 UI 변경 검토와 수정

2026-11-01 · 기준232ea88 · 별도 reviewer가 tracked diff와 untracked src/tests를 읽었다. native·실제 모델·OS 비밀 저장소·시각 수용은 reviewer의 판정 범위에서 제외했고 구현자 검증과 구별했다.

| 중요도 | 재현한 문제 | 수정·근거 |
|---|---|---|
| Important | Android 환경에서 시간만 수정해도 reset/account_ref/여러 허용 패키지가 사라짐 | snapshot 보존과 명시 필드. `environment_editor.test.cjs` RED→GREEN |
| Important | 저장 중 고친 최종 기대가 화면에만 남고 다음 payload는 예전 값이며 clean으로 오인됨 | ACK와 현재 기대를 비교하고 ID를 안정화. `recording_setup.test.cjs` RED→GREEN |
| Important | 버전 없는 빈 case의 첫 기대 입력에서 undefined final_expected 예외 | definition 기본 필드 정규화. 같은 controller 시험 RED→GREEN |
| Important | 다른 탭의 Web→Android 변경과 충돌할 때 비교창 local은 Android지만 실제 제출은 Web | 비교와 제출에 같은 named read 사용. `case_settings.test.cjs` RED→GREEN, 두 payload JSON 동일 확인 |
| Minor | 다음 페이지에서 limit·archived 조건을 잃음 | URL scope 유지. `test_ux_project_search.py` 실제 HTML 다음 링크 RED→GREEN |

처음3건은 reviewer가 수정 후 Node17개 통과를 확인했다. 마지막 충돌 비교 지적은 구현자가 전체 controller 회귀로 해소했고 추가 독립 재검토를 했다고 세지 않는다. 비용 조회·기기 preview·다른 dirty form의 자동 reload 방지 후속에서는 reviewer가 새 Important/Critical을 찾지 않았다.

구현자가 추가로 확인한 계약 보완:

- 설정 확장 필드/비용 한도가 서버 serializer에서 유실되던 문제를 실제 API 왕복 RED→GREEN으로 수정했다.
- 접수 후 busy/offline이 되어도 기존 요청 확인은 receipt를 반환한다. 새 접수는 현재 준비 상태를 다시 검사한다.
- 시범 preview hash와 job snapshot에 data/environment/resource를 고정한다. 현재 single admission은1 ITEM이며 여러 항목을 조용히 잘라 실행하지 않는다.
- 재녹화 초안의 parent와 base 컬럼 및 REC의 기준을 따로 보존한다. UI의 실제 제출 body를 controller 시험으로 확인했다.
- 전체보기는 실제 화면 영역 확대와 명시 닫기를 제공한다. 브라우저의 Promise/void 변형을 회귀 시험으로 다룬다. 이전 JS 캐시가 남던 검토 런타임은 UI 정적 파일 버전으로 갱신한다.

최종 수치는 [결과](README.md)·[진행 기록](PROGRESS.md)을 따른다. 실제 Hyper-V/장치/모델·독립 사용자·스크린리더를 검증했다고 주장하지 않는다.
