# 작은 컨텍스트 모델 인계 · v0.7

[전체 작업서](README.md) · [공통 계약](CONTRACTS.md) · [상위 진행표](../../WORK_PROGRESS.md).
이 양식은 특정 모델의 기억·skill·플러그인을 전제로 하지 않는다.

매 실행은 [NEXT_ACTION](../../NEXT_ACTION.md)의 Current에서 시작한다. 그 파일의 최소 입력/종료 규칙으로 충분하면 이 문서 전체를 읽지 않는다. Current/실행 우선순위는 NEXT_ACTION만 관리한다.

## 작업 팩

한 요청에는 아래 자료만 묶는다.

1. 저장소 위치·실제 branch/commit·dirty 파일과 사용자의 현재 허용 범위.
2. 선택한 leaf 카드 전체. 부모 W나 영역 전체를 구현하라고 하지 않는다.
3. 카드의 CONTRACTS 필수 절. 모든 경우 C00/C01은 포함한다.
4. 직접 선행 ID별 완료 receipt의 interface·schema/route·검증·남은 제한. 원문 채팅 요약으로 대신하지 않는다.
5. 관련 현재 코드/저장소 지침의 위치. 선행이 문서상 완료지만 실제 산출물이 없으면 차단한다.

한 팩이 context 절반을 넘으면 계약별 참조를 더 좁히거나 그 카드만 추가 분할한다.
중요한 dispatch/승인/secret/FAIL 제약을 빼서 길이를 줄이지 않는다.
W06-07/W27/W28 같은 audit 작업은 여러 문서를 **축별로 순차 대조**하고 결과를 파일로 남겨 읽는다. 전체 원문을 한 context에 넣지 않는다.

## 요청 템플릿

```text
작업: {예: W16-03} 한 개만 구현한다.
저장소: {실제 절대 경로}
기준 revision: {branch + commit}; 기존 변경: {dirty 파일/소유자}
사용자 허용 범위: {이번 구현의 범위; 장비/모델 시험 가능 여부}
현재 제품 상태: {실제 근거만, prototype을 제품으로 세지 않음}

읽을 자료:
- docs/execution/{영역 문서}.md의 {ID} 카드
- CONTRACTS C00/C01 및 카드에 지정한 절
- docs/validation/tasks/{직접 선행 ID}.md
- 저장소 지침과 아래 관련 현재 코드: {경로}

진행:
1. 선행 interface/실제 코드/허용 범위를 확인한다.
2. 카드의 입력/부정 조건을 검사하고 필요한 실패 시험을 확인한다.
3. 지정 계약과 범위만 구현한다. 이미 있는 파일/사용자 변경을 덮어쓰지 않는다.
4. 지정 검사와 UI/실환경 확인을 수행한다. 필수 실환경 시험이 불가하면
   코드 검사 결과와 차단된 gate를 구분한다. SKIP/mock을 PASS로 적지 않는다.
5. diff와 UI 조작/상태 대응을 검토한다.
6. 아래 완료 인계를 저장하고 카드/TASK_INDEX/root 진행률을 일치시킨다.
7. NEXT_ACTION의 Current/Next를 갱신한다. 미완료면 Current와 재개 조건을 유지한다.

모호/충돌:
- DTO/route/상태를 임의 추측하거나 다음 작업을 미리 만들지 않는다.
- 재현된 충돌, 관련 계약, 영향 ID와 필요한 결정을 기록한다.
- 현재 허용된 독립 부분은 진행하고 선행이 없는 소비 구현은 차단한다.

종료:
- 변경 파일, 시험 명령/결과, 실제 근거, interface 변경, 미완료/다음 준비 ID를 보고한다.
- 승인하지 않은 배포/외부 메시지/전체 데이터 삭제/클라우드 전환은 하지 않는다.
```

## 완료 인계 파일

경로는 `docs/validation/tasks/{ID}.md`다. **구현 때 생성하며 이번 개정에서 빈 PASS 파일을 만들지 않는다.**

```markdown
# {ID} 구현 인계

- 상태: complete | blocked | verifying
- 기준/완료 revision: {실제 값; commit하지 않았다면 그렇게 명시}
- 적용 계약: {C절/카드/변경한 DTO schema version}
- 변경 파일: {생성/수정 경로}
- 제공 interface: {정확한 import path, signature, request/response fields, route/status}
- 소비한 선행: {ID + receipt 경로}
- DB 변경: {migration ID, constraints, 영향; 없으면 없음}
- UI: {UI 추적 ID별 조작/상태와 실제 연결; 없으면 없음}
- 자동 검사: {명령, 실행 시각, exit code, PASS/FAIL/SKIP 수}
- 실제 환경 검사: {VM/USB/browser/model 조건, 장치/버전, 결과, 근거}
- 보존 불변식: {해당 source/hash/default/FAIL/secret/lease 검사 근거}
- 실제 검증 projection: {카드 expected와 얻은 실제 값의 비교}
- 미완료/제한/차단: {코드 검사 PASS와 실환경 미실행을 분리}
- 다음 준비 ID: {모든 직접 선행이 끝난 작업만}
- 재검토 필요 ID: {계약 변경/실패로 다시 열어야 할 작업}
```

secret 값·키·원문 화면·hidden reasoning을 인계 문서에 붙이지 않는다.
정제한 artifact ID/hash/가용성·짧은 판정 이유·허용된 근거 경로만 쓴다.

## 완료 판정

- 한 leaf의 코드·필수 검사·UI/실환경 근거·인계가 모두 있어야 complete다.
- 다른 leaf가 제공할 기능을 mock으로 잠시 보여줬다면 그 기능의 담당 ID는 미완료다.
- 부모 W는 상세 작업 전부와 상위 통합 조건이 끝나야 완료다. W16-05만 끝나면 W16 전체는 미완료다.
- 재개 시 완료 표시를 믿기 전에 receipt의 코드/route/검사 근거가 실제로 있는지 확인한다.
- 실패가 발견되면 완료 체크 해제·status 재개·root 수치 변경·영향 ID를 함께 기록한다.

## 상태 동기화와 인계 중단

카드 체크·TASK_INDEX.status·root 요약·NEXT_ACTION의 Current/Next는 한 변경 묶음으로 수정한다.
구현 도중 모델 context가 부족하면 새 기능을 더 하지 않고 현재 diff/검증/미완료를 인계한다.
새 모델은 그 인계와 직접 선행만 읽고 같은 ID를 이어간다. 새 ID를 만들어 진행률을 부풀리지 않는다.
