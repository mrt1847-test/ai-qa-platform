# 샘플 기반 UI 개선 결과

2026-11-01 · 작업 분기 `codex/ui-ux-improvements` · 기반 snapshot `232ea88`.

초기 [QA Studio 샘플](../../../prototype/README.md)을 기준으로 실제 FastAPI/Jinja 화면을 개선했다. 기존 엔진/DB/승인 계약을 재사용했으며 프런트 프레임워크·의존성을 설치하지 않았다. 독립 UI 작업 `3f9247f` 당시에는 W 완료89/163·Current W31-02를 보존했다. 이후 사용자 요청에 따른 통합에서는 최신 master `fa856ad`의 완료126/163과 준비된 Current 없음 상태를 보존한다. 아래 수치는 독립 UI 작업의 검증 기록이며 통합 후 검증은 [병합 기록](MERGE.md)을 따른다.

## 확인된 결과

- pytest 전체: **199 passed, 1 deselected** (`test_w01_02`: 실제 Hyper-V 선행 미준비). 최종 추가 변경은 지정 smoke 및 Node 시험으로 재확인했다.
- JavaScript 제어 회귀: **21 passed**. 새/수정 JavaScript 구문 검사와 마지막 UI/API smoke **27 passed**도 확인했다.
- 1440×1000 / 1024×900에서 개요·환경·데이터·검증·시범·목록·검토를 실제 브라우저로 확인했다. 각 화면의 body scrollWidth는 viewport 이하였다. 표/원본 크기 캡처의 전용 스크롤은 유지한다.
- 1024에서 Web 초안 v1 저장→목적 수정→저장 후 설정 이동(v2), Android 초안 재조회, package 없음/기기 offline 시범 차단, 키 보기/취소, 검토 의견 저장·반려를 조작했다. 기록 없이 임의 PASS를 채우지 않았다.
- 합성3000 case, 페이지25, warm20회 p95 .0023862초, 조회4개/페이지, 전체 페이지 순회 누락/중복0. 시험 환경 Windows build26200/Python3.11.9/AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD. 혼합 상태 전체 부하·native 처리량과 구별한다.

## 단위별 인계

`[x]`는 현재 MVP의 UI/core 변경과 위 근거를 뜻한다. 상태 열의 외부·미지원 경계까지 완료했다는 뜻이 아니다. 원 계획의 세부 수용 체크리스트는 보존하며 현재 결과는 각 ID 문서에서 대조한다.

| UI/core 반영 | 단위 | 수용 경계 |
|---|---|---|
| [x] [S01](S01.md) | 공통 저장 상태 | core 검증 |
| [x] [S02](S02.md) | 저장 receipt | core 검증 |
| [x] [S03](S03.md) | 환경 프로필 편집 | core/UI 검증 |
| [x] [S04](S04.md) | 테스트 데이터 편집 | core/UI 검증 |
| [x] [E01](E01.md) | 미저장 이동 경계 | core/UI 검증 |
| [x] [E02](E02.md) | 입력 화면 보호 | core/UI 검증 |
| [x] [E03](E03.md) | 사람이 읽는 검증 편집 | core/UI 검증 |
| [x] [E04](E04.md) | 단계·기대 결과 | core/UI 검증 |
| [x] [N01](N01.md) | 현재 프로젝트 검색 | core/UI 검증 |
| [x] [N02](N02.md) | 프로젝트 탐색 | core/UI 검증 |
| [x] [N03](N03.md) | 케이스 작업 공간 | core/UI 검증 |
| [x] [N04](N04.md) | 실제 시범 준비 | core/UI 검증 · native 대기 |
| [x] [N05](N05.md) | 사후 검토·결정 | core/합성 UI 검증 |
| [x] [N06](N06.md) | 전체 재녹화 | core 검증 · native 대기 |
| [x] [R01](R01.md) | 기기 우선 진입 | core/UI 검증 |
| [x] [R02](R02.md) | Web 초안 | core/UI 검증 |
| [x] [R03](R03.md) | Android·대상 전환 | core/UI 검증 · 설치 앱 자동 선택 미지원 |
| [x] [R04](R04.md) | 시작 준비·접수 | core/UI 검증 · native 대기 |
| [x] [D01](D01.md) | 연결 상태 안내 | core/UI 검증 |
| [x] [D02](D02.md) | 최근 관찰 | core/합성 UI 검증 · 실제 관찰 대기 |
| [x] [M01](M01.md) | 목록 projection | core/UI 검증 |
| [x] [M02](M02.md) | 페이지·선택 범위 | core/UI 검증 · 일괄 실행 별도 |
| [x] [M03](M03.md) | 3000개 규모 | 합성 목록 성능 검증 |
| [x] [A01](A01.md) | AI 역할·키 관리 | core/UI 검증 · 연결 해제 별도 |
| [x] [A02](A02.md) | 정책·비용 구분 | 정책/UI 검증 · 최종 비용 집계 미연결 |
| [x] [V01](V01.md) | 초기 샘플 UI 적용 | 1440/1024 전문가 확인 |
| [x] [V02](V02.md) | 전체 구성·증거 보기 | 전문가 UI 확인 · native 대기 |
| [x] [K01](K01.md) | 접근성 | 의미/키보드 확인 · 스크린리더 미실시 |
| [x] [K02](K02.md) | 목적 기반 여정 | 전문가 UI 확인 · 독립 사용자/실기기 미실시 |

## 남은 경계와 재개 조건

- 실제 녹화/재생/관찰: 기존 W01/W07/W13/W14/W15/W16/W17의 VM·driver·장치·모델 선행이 준비된 경로만 재개한다. 이번 합성 시험으로 native leaf나 부모 gate를 완료하지 않는다.
- 일괄 실행: 이 UI의 단일 시범 화면은1 ITEM을 선택한다. 통합된 master의 선택·데이터 행·대상 전개와 정식 실행 API는 보존하며 여러 ITEM을 조용히 잘라 실행하지 않는다. 기존 suite/수행 화면의 기능과 샘플 기준 탐색 메뉴 연결 범위는 별개다. 월3000개 실제 회귀·장치 처리량을 검증한 것은 아니다. 복제/보관의 현재 페이지 일괄 처리는 별도 기존 API를 사용한다.
- 연결 해제: 모델 binding 삭제/해제 API가 없어서 활성 해제 행동을 제공하지 않는다. 유지/새 revision 교체만 지원한다. API 수명주기 계약을 확정한 뒤 별도 구현한다.
- 비용: 월3000개는 업무량 가정이다. 원본과 보정 기록을 섞어 확정 금액을 만들지 않는다. 최종 통화별/as_of 집계와 실제 provider 비용 대조는 usage/분석 소유 작업에서 연결한다. 이 화면의 최근10개는 최종 청구 합계가 아니다.
- 독립 사용자·스크린리더·실제 장치 성공은 미실시다. 이번 전문가 조작·DOM 의미·결정적 API 시험과 따로 수용한다.
- Android 설치 앱 자동 선택·설치는 기존 지원 경계 전까지 명시 패키지/저장 참조로 준비한다. 환경의 `account_ref` 문자열은 기존 계약을 보존하며 새 자격 원문을 입력하는 칸이 아니다.

외부 대기는 해당 경로만 막는다. 다음 개발 순서는 루트 [NEXT_ACTION](../../../NEXT_ACTION.md)의 기존 W Current를 따른다. 이 결과를 이유로 완료된 W를 재구현하거나 모든 카드를 처음부터 다시 읽지 않는다.

## 검증 명령

저장소의 기존 가상환경 Python을 사용했다. 새 설치는 하지 않았다.

```powershell
python -m pytest -q -k 'not test_w01_02' --basetemp <고유한 임시 디렉터리>
node --test tests/web/case_settings.test.cjs tests/web/command.test.cjs tests/web/definition_model.test.cjs tests/web/environment_editor.test.cjs tests/web/evidence_viewer.test.cjs tests/web/form_state.test.cjs tests/web/navigation.test.cjs tests/web/recording_setup.test.cjs
git diff --check
```

최종 전체 branch 리뷰는 별도 reviewer가 tracked diff와 untracked src/tests를 읽었다. Android profile 유실·wizard 저장 중 기대값 유실·빈 case 예외·설정 충돌 비교 불일치 및 페이지 limit 누락을 재현 후 수정했다. [리뷰 기록](REVIEW.md)에 판단과 후속 검증을 남긴다.

## 화면 증거

[개요1440](screenshots/overview-delivery.png) · [개요1024](screenshots/overview-1024.png) · [목록1440](screenshots/cases-final-1440.png) · [목록1024](screenshots/cases-1024.png) · [검증1440](screenshots/definition-1440.png) · [검토1440](screenshots/review-final-1440.png) · [검토1024](screenshots/review-1024.png) · [전체보기](screenshots/viewer-fullscreen.png).

큰 직사각형 그림은 합성 UI 증거다. 실제 앱의 녹화 캡처로 해석하지 않는다. 검토용 임시 런타임은 제품 저장소에 fixture를 삽입하지 않고 별도로 실행했다.
