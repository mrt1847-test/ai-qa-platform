# RX87 B0.6 · 증거 저장 I/O 구현 단위

기존 ANDROID_RUNTIME_TASKS B0.6의 실행 계획. Current는 NEXT_ACTION 하나다. API·파일·SQLite 실제 로컬 검증만 하며 유료 모델/설치/배포는 하지 않는다.

## 계약과 경계

- 파일 쓰기·flush·파일 lock 대기는 ASGI loop와 SQLite writer transaction 밖에서 수행한다. metadata/이벤트/refs/ready/ACK만 짧은 transaction에서 함께 게시한다.
- 기존 artifact_staging과 request-key 파일 lock을 재사용한다. 같은 key/본문은 같은 staged ID/파일을 재사용하고, cached ACK는 파일을 다시 쓰지 않는다. request-key lock은 SQL lock이 아니다.
- stage는 ready/승인 근거가 아니다. 최종 transaction에서 서버 시각·project/purpose/job/generation/worker·원 소유/bytes hash를 재검사한다. 실패·crash 후 남은 stage는 미게시로 유지해 같은 요청 재확인에 사용하며, 원래 ready 파일을 지우지 않는다.
- 원본 manifest/FAIL/승인은 불변이다. body/hash 충돌·다른 owner/늦은 generation으로 새 ready를 만들지 않는다. cached 저장 receipt는 현재 실행 권한과 별개다.

## 실행 순서

1. 느린 실제 publish 경계에서 heartbeat 응답·독립 DB writer 획득·업로드 중 임대 만료를 RED로 확인한다.
2. body/권한 preflight→durable stage(파일 I/O)→현재 권한과 최종 metadata commit을 분리한다. 큰 bytes는 SQL transaction에서 읽거나 쓰지 않는다. 동일 요청 경합은 기존 per-request 파일 lock으로 직렬화한다.
3. 인증/Store 생성/파일 작업을 worker thread로 옮긴다. Store는 사용 thread에서 열고 닫는다. API 테스트도 shared connection shortcut 대신 실제 thread별 connection을 사용한다.
4. 별도 worker/artifacts도 server callable을 각 writer transaction 취득 뒤 샘플링하고 thread 경계를 사용한다. direct trusted fixture의 명시 clock은 보존한다.
5. 같은 key/동시 요청·stage 재사용·변경 본문·실패/늦은 upload·readonly receipt·source/approval 불변성과 기존 회귀를 확인한다. fresh review→필수 수정1회→전체 회귀·인계·큐 동기화.

## 리뷰 초점

파일 쓰기 중 SQL/event-loop 차단, active→late 전환, metadata commit 실패 때 기존 ready bytes 보존, shared stage의 동시 삭제/재사용, 같은 key의 다른 본문, API thread affinity, direct fixture time과 untrusted HTTP authority의 구분. retained stage/정리 한계는 숨기지 않는다.

완료2026-11-14(core_contract): [인계](../validation/tasks/RX-87-B0-IO.md). 신규15·집중68·최종 전체9failed840passed1skipped(기존9). 실제 환경 수용/일반 GC는 미완료 범위를 따른다.
