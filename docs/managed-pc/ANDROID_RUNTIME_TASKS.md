# RX-87 · Android 실행 연결의 작업 단위

기존 [RX-87](UI_EXECUTION_TASKS.md#rx-87)의 구현 순서다. Current/Next는 NEXT_ACTION.md 하나만 관리한다. 상위 RX-87은 아래 모든 필수 단위의 증거가 있을 때만 완료한다. 실제 AVD/유료 모델 수용은 RX-23이다.

## A. 녹화의 고정 action/시간 한도

**계약:** RX-97 validate_authoring_pin(snapshot) 반환 한도를 사용한다. worker 전역 설정은 한도를 좁히기만 한다. 기존 pin 없는 개발 fixture는 호환한다. **파일:** worker/android_jobs.py, tests/integration/test_rx87_android_runtime.py.

- [x] 정상 API→claim의 pin을 AndroidRecordingHandler에 넣어 max_actions가 worker 기본50보다 작으면 그 수 이후 모델/gesture가 발생하지 않는 RED를 확인한다.
- [x] 모델 대기 동안 timeout 경과/취소를 재현한다. 응답 도착 뒤 제스처0이어야 한다. handler를 다른 claim에서 재사용해 한도·시계·호출량이 누적되지 않는지 확인한다.
- [x] worker의 더 작은 한도와 pin의 model-call 상한을 각각 지킨다. 잘못된 pin은 capture/model/gesture 전 거절한다. 서버 RX-98 영속 모델 quota를 대체하지 않는다.
- [x] 시간/취소 재검사를 실제 dispatch 직전에 둔다. 아직 실행하지 않은 모델/정제 실패를 불명 기기 실행으로 기록하지 않도록 journal 경계를 확인한다. 실제 전송 이후 불명은 재클릭하지 않는다.
- [x] RX48/RX65/RX67/RX97~99 및 새 테스트를 확인하고 부분 인계를 남긴다. A만으로 RX87 완료하지 않는다.

## A의 검증 상태

2026-11-14: A complete(core_contract), native-send callback/한도·journal 경계와 집중44/JS32 통과. 최종 전체9failed/749passed/1skipped는 기존9개 기준선과 같다. [부분 인계](../validation/tasks/RX-87.md)를 따른다. B/C/D 미완료다.

## B0. 현재 worker fence와 장기 실행 control

- [x] B0.1: POST worker/checkpoints에 현재 project/worker/purpose/job/attempt/ACK·generation·incarnation/lease margin·취소/종료·고정 job deadline 검사를 연결한다. worker now/과거 allowed receipt를 권한으로 믿지 않는다. 같은 key도 현재 상태를 새로 읽으며 model grant/실제 실행 quota가 아니다.
- [x] B0.2: worker client는 응답 소유/세대/phase·시간/lease 형식을 검증하고 전체 HTTP 왕복 시간을 빼고 판정한다. runtime이 handler의 모델 전/실제 native 전송 직전에 이 callback을 연결한다. 서버 취소가 모델/파일 I/O 중 생겨도 다음 gesture0이며 저장 증거/제안은 보존한다.
- [x] B0.3: Android recording의 장기 모델 대기/실행 중 heartbeat/renew/cancel poll과 종료·연결 유실·재접속을 연결한다. handler가 반환하기 전까지 초기 lease 상수를 계속 믿지 않는다. 자동 action/attempt 재개0이다.

B0.1/B0.2 완료2026-11-14, [인계](../validation/tasks/RX-87-B0.md). 신규40건·집중62, 최종 전체 기존9failed/789passed/1skipped. B0.3 Android recording lifecycle도 [인계](../validation/tasks/RX-87-B0-KEEPALIVE.md)로 완료했다. replay/Web 연결은 B/RX88이며 상위 RX87 미완료다. 현재 B0.4다.

## B0.4. 단계별 증거 ACK 유실의 안전한 재확인

확인한 코드 결함: runtime의 commit_step은 같은 step key에 매 호출 새 now를 넣는다. 실제 action/evidence commit 뒤 ACK가 유실되면 helper 재조회409, handler는 중단하고 저장된 prefix와 finish가 어긋날 수 있다. 현재 API는 원본문의 같은 key 재요청을 이미 지원하므로 새 저장소/gesture 재실행으로 해결하지 않는다.

- [x] 실제 API/정제 PNG에서 같은 step 재확인409와 commit 후 응답 유실을 RED로 확인한다.
- [x] worker 단일 소유 committer가 key/본문/최초 시각을 고정한다. 확인된 ACK는 작은 receipt만 보관하고 큰 PNG payload는 비운다. 미확인 pending step이 있으면 다음 step을 전송하지 않는다.
- [x] timeout/명시 transient 전송만 같은 본문으로 추가1회 확인한다. auth/TLS/409/422/429는 반복하지 않는다. body가 바뀐 같은 key는 거절하고 ACK 소유/late/연속 prefix를 확인한다.
- [x] 실제 runtime/handler에서 native1·모델2(click→finish)를 유지하면서 saved prefix를 회복한다. source commit/응답 유실·한도·중단·재사용과 RX67/RX33/전체 회귀를 검증하고 인계한다. 자동 gesture/attempt 재시작0이다.

B0.4 완료2026-11-14, [인계](../validation/tasks/RX-87-B0-EVIDENCE.md). 집중39·전체 기존9failed/819passed/1skipped. 현재 B0.5.

## B0.5. 증거 저장의 서버 시각·용도 권한

- [x] 새 업로드에 worker의 과거 now를 넣어 만료 임대가 active로 보이는 경로와 같은 worker ID/다른 purpose 토큰의 저장 허용을 실제 API에서 RED로 확인한다.
- [x] 서버 commit writer transaction을 얻은 뒤의 시각만 late/임대 권한에 사용한다. worker now는 요청 식별/기록 시각이며 실행 권한이 아니다. token의 project/purpose가 실제 job과 일치해야 한다.
- [x] 이미 commit한 같은 key/본문 receipt는 현재 임대와 독립 재조회한다. 새 late evidence를 ready/승인 근거로 승격하지 않는다. timestamp/토큰·다른 generation/반려·결과 불변성 회귀를 확인한다.

B0.5 완료2026-11-14, [인계](../validation/tasks/RX-87-B0-AUTHORITY.md). 최종 전체 기존9failed/825passed/1skipped. 현재 B0.6.

## B0.6. 증거 I/O와 control 응답성

기존 post_evidence_commit은 파일 작업을 ASGI loop에서 수행하고, active artifact 게시도 SQLite writer transaction 안에 있다. 단순 thread 이동만으로 DB write 대기 중인 heartbeat까지 해결했다고 보고하지 않는다.

- [ ] 느린 실제 artifact 게시 동안 heartbeat/취소·checkpoint 응답을 재현한다. API event-loop와 DB writer 대기를 각각 구분한다.
- [ ] body 검증/임시 파일 durable staging을 writer transaction 밖에서 처리하고 현재 scope/lease/receipt를 짧은 transaction에서 재검사해 게시한다. 같은 key/동시 응답 유실·orphan·실패 정리와 불변 ready bytes를 보존한다.
- [ ] 서버 store는 사용 thread에서 열고 닫는다. event-loop 차단/같은 요청 중복 파일·권한 변경·late 저장/중간 파일 노출 부정 경로를 검증한다. 외부 환경 대기로 처리하지 않는다.

## B. replay의 고정 정책과 한도

**입력:** resolve_claim_healing_pin(snapshot)의 detached WorkerHealingPin, 승인 package hash/plan. **파일:** android_jobs.py, worker/healing_pin.py, tests/integration/test_rx87_android_runtime.py.

- [ ] OFF/trial은 actor0, 정상 승인 code/좌표 반복을 보존한다. ON의 typed policy를 runtime에 전달하고 worker 환경 boolean/budget으로 대체하지 않는다.
- [ ] replay의 claim별 action/timeout·episode caps와 handler 재사용을 검증한다. 지원하지 않는 정상 ON 경로는 명시 실패로 남기며 fixture 성공을 넣지 않는다.
- [ ] 정상 package의 check/expected/target metadata와 handler의 정적 fixture check가 혼합되지 않게 서버 pin을 소비한다.

### B 구현 전 확인한 실제 코드 누락

- worker/runtime.py는 handler.handle 중 heartbeat/renew/cancel poll을 연결하지 않는다. 단순 context boolean이나 초기 lease_remaining 상수를 원격 현재 권한으로 사용하지 않는다. native 전송 전 현재 서버 fence와 장기 모델 대기 중 heartbeat/lease 갱신이 필요하다.
- Android builder의 _live_android_capture_pair.prepare는 선택 package 대신 Android Settings를 연다. 고정 case version의 선택 target을 서버 claim에 결합하고 allowlist된 launch 경계에서 소비할 후속 단위가 필요하다. 새 target schema/authority를 임의 원문 문자열로 대체하지 않는다.
- replay handler checks는 전역 context tuple뿐이다. 승인된 check/expected/target metadata를 package/현재 case-run과 묶어 공급해야 한다. 고정 plan 문자열만으로 이 부분이 완료되지 않는다.

## C. 서버 check/episode 전용 권한

**문제:** RX98 recording authoring grant는 replay의 verifier/healer 권한이 아니다. **파일:** worker model API, server model authorization/receipts, 기존 healing service, HTTP client.

- [ ] reserve_healing_episode의 현재 attempt 전체 dispatch_started 검사는 앞 step을 실행한 뒤의 정상 locator 실패까지 막는다. 실제 실패 action의 미전송 증거와 episode 소유를 먼저 고정해, 다른 action 실행 기록을 해당 action 불명 전송으로 혼동하지 않는다.
- [ ] 실제 regression claim/ACK·고정 package/check·healing policy·binding/key·현재 lease/취소를 확인하는 서버 포트를 연결한다. worker가 episode ID/allowed=true만 만들어 호출할 수 없게 한다.
- [ ] episode 예약1/호출2/30초와 전체 job 상한, 동일 key/응답 유실·pending 불명·재시도 차감을 영속화한다. authoring 권한 재사용0이다.
- [ ] 원본 FAIL/승인 package는 불변이고 episode/제안/검증은 별도 소유 기록이다. 저장된 근거 조회·사후 승인은 worker offline과 독립이다.

## D. 허용 실패에서 native 복구·제안까지

**입력:** B의 고정 정책, C의 실제 서버 episode/model port, RX96의 실제 응답 파서/unique locator proof.

- [ ] locator/레이아웃 실패만 진입한다. 제품 assertion 실패·불명 dispatch·expected/목표 변경은 제외한다.
- [ ] 현재 관찰/타깃 identity·유일성·동일 action/path를 증명한 후보만 native 제한 재동작한다. 취소/임대/시간/cleanup은 재검사한다.
- [ ] OFF0/ON허용/ON차단/소진/late/실패/재사용을 정상 API→claim→handler에서 확인한다. 성공 제안과 원본 QA를 분리한다.
- [ ] 전체 회귀·review 및 RX87 인계/색인/진행표를 갱신한다. 기존 기준선 실패와 실제 모델/AVD 미수용은 그대로 공개한다.
