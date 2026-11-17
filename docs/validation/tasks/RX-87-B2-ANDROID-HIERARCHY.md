# RX87 B2.3b3b0 · Android XML의 명시 대상 관찰

- 상태: complete (pure parser 범위). BASE master dca71ce; 이 파일을 포함하는 로컬 커밋이 완료 revision이다.
- 선행: B2-CHECK-BINDING-PIN, CHECK_BINDING_RUNTIME_TASKS b3b0. 계약 C05/C06. DB/UI/승인/실행 정책 변경 없음.
- 등급: in-memory UIAutomator 형식 XML fixture와 기존 observation/validator 회귀. 실제 ADB/모델/기기/XML 수집/정규화 저장0. 전체 hierarchy 실행 검증·RX87 완료로 세지 않는다.

## 제공 interface

`aiqa.environments.android_hierarchy.parse_android_hierarchy(raw:bytes,package:str,resource_ids:tuple[str,...],rotation:int)->AndroidHierarchy`는 frozen snapshot(rotation,targets)을 반환한다. target은 resource_id/status 및 local text/명시 enabled·checked·selected·focused·visible 사실만 담는다. status available/missing/ambiguous/redacted/unavailable는 관찰 품질이며 QA 판정이 아니다. text는 repr에서 제외하며 원문 정제·영속화를 주장하지 않는다. 후속 reader/evaluator가 적법한 검증 시점·권한·정제를 책임진다.

선택 앱의 exact resource-id만 수집하고 다른 앱/비선택 노드 text는 반환하지 않는다. 같은 native resource가 둘이면 ambiguous이며 첫 항목을 택하지 않는다. 요청 중복은 dedup한다. password=true는 redacted, password flag 누락/비정상 및 잘못된 boolean·과도한 선택 text는 unavailable이다. 어느 경우든 text/상태값을 노출하지 않는다. 없는 boolean은 None, visible-to-user가 없으면 visible=None이며 value=text로 추정하지 않는다.

strict UTF8의 단일 hierarchy/root rotation0..3을 요청 degrees0/90/180/270와 정확히 대조한다. 1MiB raw,4096 UI node,depth64(root 포함),선택 text4096 UTF8 bytes,요청256개를 제한한다. XMLPullParser를 chunk로 읽으며 node/depth를 제한하고 DTD/ENTITY/다른 태그/잘못된 XML을 거절한다. unknown attributes는 복사하지 않는다. rotation/좌표 비율 보정·파일/network/ADB/model 호출이 없다.

public 오류는 AndroidHierarchyRejected('hierarchy_invalid') 고정이며 decoder의 민감 입력 exception context를 연결하지 않는다. 실패는 handler 바깥에서 생성하고 public traceback frame의 입력 인수도 지운다. NUL을 먼저 거절해 BOM 없는 UTF16을 Expat가 재해석하는 우회를 차단한다. declaration의 encoding 공백 변형을 포함해 UTF8만 허용한다.

## 검증·검토

초기 missingmodule RED36→36pass0.12s. self-audit encoding 공백 우회 RED1을 보완했다. fresh review Important2(BOMlessUTF16/원 입력을 잡는 예외 context)를 RED3+이미 거절되던 UTF32 2case로 확인한 뒤 한 수정 배치로 해결했다. re-review 없음.

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/test_android_hierarchy.py tests/integration/test_android_observation.py tests/integration/test_w17.py -q -p no:cacheprovider --tb=short
```

최종 **76 passed0.60s**. nested/Unicode/escaping,exact byte/node/depth/text limits,duplicate/foreign/missing/password/boolean,rotation/ID 부정,DTD/외부 entity/fileIO0,UTF16/32 및 민감 exception context/traceback를 포함한다. 실제 앱 TC/live 수용 수로 세지 않는다. 기존 전체6개 baseline/87/99·49/53·RX87 미완료는 유지한다.

## 다음

b3b1에서 bounded native XML reader와 현재 lease/선택 target/rotation/deadline을 결합하고, b3a의 명시 boundary에서만 deterministic 검증한다. c가 normalized check_results/ITEM을 저장한다. 이 pure 포트는 아직 운영 capture/validator에 연결하지 않았으므로 실제 text/state QA 수용을 주장하지 않는다. 외부 키/독립 호스트가 이 구현을 막지 않는다. metadata-load.md는 기존 dirty 보고서로 보존·커밋 제외했다.
