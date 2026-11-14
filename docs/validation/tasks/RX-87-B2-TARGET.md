# RX87 B2.2b · 선택 앱 준비와 저장 근거

- 상태: complete(core_contract) for B2.2b, 최종 전체 회귀 기준선 비교 완료. 기준 master cd07bf4, 작업2026-11-14→최종검증2026-11-15. C00/C01/C04/C05/C14. 상위 RX87 in_progress·전체87/99·기능49/53 유지. 운영 배포/유료 AI/API 키 사용·사용자 DB 초기화 없음. 사용자 dirty metadata-load.md 제외.
- 파일: environments/android_app_launch.py, worker/android_prepare.py, android_jobs.py/runtime.py/step_evidence.py, store/evidence.py/evidence_io.py, recording/review_manifest.py, web/review_context.py. 정상 runtime client와 선택 package를 연결했으며 Settings fallback을 제거했다. 직접 legacy 개발 constructor의 prepare callback은 명시 seam으로만 유지한다.
- 입력은 resolve_claim_case_context의 immutable pin이다. claim project/job/attempt/generation과 context_hash를 준비 캐시에 결합한다. 같은 attempt의 다른 package/context는 pending/cached ACK를 반환하지 않고 거절한다. builder 생성·불량 pin/없는 fence·SecretRef coverage 부재 시 native/model/upload0이다. SecretRef가 있으면 화면 정제 성공을 가정하지 않는다.
- 고정 ADB MAIN/LAUNCHER package argv의 bounded start1회 + 읽기 전용 focused window 대조다. 전송 직전 현재 fence→durable dispatch_started→현재 fence를 검사하고 미전송은 not_sent, 전송 뒤 응답/관찰 불명은 unknown이다. CLI stdout CRLF를 정규화하되 Status/Activity/package/focus 검사를 유지한다. 자동 native retry0이다. 관찰 성공도 QA assertion 성공이 아니다.
- before PNG를 native 전 fsync하고 after/구조화 log·frozen scope/context/time/key/body를 ACK 전 fsync한다. namespace prepare, events=[]이며 gesture prefix/기존 step key를 침범하지 않는다. observed 로그는 before/after/log를 요구하며 unknown은 before/log와 가능한 after다. 서버는 예약 prepare-<attempt> identity·roles·log disposition을 검증해 unknown/outcome_known0을 보존한다. 다른 disposition으로 같은 ready 기록을 덮지 않는다.
- 서버 ACK가 유실되면 동일 body/time/key의 증거만 추가1회 확인한다. 재생성은 남은 payload의 scope/context/hash를 검증해 receipt만 복구하고 no-resume으로 실패한다. 이 복구는 expired/cancel checkpoint와 독립이어도 현재 서버 인증·cached/late 규칙을 그대로 따르며 capture/native/model0이다. 정상 ACK 뒤 지정4파일만 제거한다. payload 생성 전 crash 또는 미ACK spool의 자동 TTL은 미구현이며 journal 차단/수동 조사 대상이다.
- API 준비/첫 gesture에 같은 PNG bytes를 넣어 실제로 artifact 소유가 섞이던 결함을 재현했다. dedup을 project/attempt/hash/role/owner kind/id/action/media로 맞춰 각 동작의 링크를 보존했다. 준비는 REC/ITEM timeline에서 조회하되 trial readiness·review candidates·직접 review entry에서는 제외한다. source seal의 gesture mapping·기존 승인/원본 FAIL은 바꾸지 않는다.
- global native50 중 준비1회를 예약한다. recording gesture cap=min(요청 cap,49), replay50줄 이상은 준비 전 action_budget으로 거절한다. per-pin gesture/model/time 한도는 별도로 더 작은 값을 따른다. UI 요청 한도50 안내는 아래 Minor 후속이며 silent native51을 허용하지 않는다.

## 실제 선택 APK 관찰

- 사용자 지정 C:/apk/GmarketMobile-prod-debugFinal-20260429_032548.apk, com.ebay.kr.gmarket, versionCode352/versionName10.8.6-debugFinal, 47,049,119bytes. SHA256 8b1cc87206eb5fbaaae6ee6ba4f97cab8b6e573bd157d279af536ca33ac68a1a. 제품에 앱명/파일 경로를 하드코딩하지 않았다. SDK aapt2 dump badging/파일 해시로 확인했다.
- 명시 기존 Medium_Phone_API_36/emulator-5580에 미설치 여부 확인 후 fresh install Success. 재설치/초기화/데이터 삭제/권한 허용/로그인/구매0. 기존 다른 AVD/사용자 앱은 건드리지 않았다. 초기 start timeout/SystemUI ANR은 성공으로 보지 않았으며 자동 start retry하지 않았다.
- 동일 AVD를 snapshot 없이 RAM4096/cores4/swiftshader로 기동하고 명확히 관찰한 SystemUI Close app만 수동1회 눌렀다. 앱 초기 권한 안내의 확인/권한 허용은 누르지 않았다. 이후 CRLF parser 수정 뒤 새 수동 기술 검증에서 launch1회/focused package 일치/PNG observed를 확인했다. 최종 activity com.ebay.kr.gmarket/.eBayKoreaGmarketActivity. 이는 authenticated product claim→AI 녹화→검증→승인 수용이 아니다. 운영 모델 호출0/비용0이다.
- [관찰 JSON](../evidence/RX-87/gmarket-proof.json) · [실제 전면 화면](../evidence/RX-87/gmarket-foreground.png). PNG SHA256 38804e30cfba395d0e7c62b4fe03945d2df5cfe92028d8839475b5c534564cfd, 218046bytes. 검증 후 이 배치가 시작한 전용 AVD는 종료했고 APK/앱 데이터는 유지한다. AVD config 파일은 수정하지 않았다.

## 검증·리뷰

- TDD: launch 부재 RED12→GREEN12, foreign/ANR focus RED2→GREEN, 실패 증거 유실 RED2→GREEN, 실제 provenance RED1→GREEN, post-ACK cancel rewrite RED1→GREEN, 실제 ADB CRLF RED1→GREEN.
- fresh review1회 Important4를 한 수정 배치로 해결했다. (1) 재생성 ACK 복구 RED2 (2) 실제 API unknown timeline RED1 (3) offline/candidates/direct setup-only review 허용 RED3 (4) pending/cached 다른 pin 재사용 RED2. malformed log state TypeError RED2도 같은 검증 경계에서 해결했다. 실제 HTTP가 commit한 뒤 응답2회 유실→lease 만료→false checkpoint인 재생성에서도 receipt만 회복하고 기기 재개0/서버 artifact3/events0을 확인했다. 복구 ACK가 또 유실된 뒤 확인해도 실행이 재개되지 않는 latch도 RED1→GREEN으로 확인했다. 재리뷰 없음.
- 최종 집중(재생성 복구 latch 포함): pytest -q -p no:cacheprovider tests/integration/test_rx87_target_prepare.py tests/integration/test_rx87_app_launch.py tests/integration/test_rx87_case_context_consumer.py tests/acceptance/test_rx_52.py tests/acceptance/test_managed_pc_review.py --tb=short →87passed66.93s. 정상 trial/review/approval의 기존 양성 여정도 유지했다. 실제 API/DB에서 준비 prefix0→gesture prefix2, 서로 다른 action artifact IDs, lease 종료 뒤 browser timeline/PNG/log 조회를 확인했다.
- 리뷰 전 전체:9failed948passed1skipped783.40s, 실패 node9는 기존 기준선과 동일. 최종 리뷰 수정/복구 latch 후 전체: **9failed963passed1skipped641.84s**. 실패 node9는 B2.2a/기존 기준선과 정확히 같다. 신규 실패0이며 전체 green은 아니다. interrupted final-full.log는 수용 근거로 쓰지 않는다. 로그 .review-work/android-target/{verified-focus,full,verified-full}.log. 전체 green으로 표현하지 않는다.
- 미룬 Minor: Android 녹화·환경 폼의 요청50 표시에 준비1/gesture49 안내 추가. B2.3 체크리스트에 편성했다. 앞 배치의 SecretRef UUID 형식/private rejected candidate Minor2도 별도 보존한다.

## 판단·후속

1. 준비는 별도 operation으로 기록하되 global50에 포함한다. gesture 최대49 때문에50줄 package는 범위 축소/명시 오류가 필요하다.
2. SecretRef pixel coverage 미증명은 준비를 차단한다. coverage 구현 전 해당 케이스는 기동할 수 없다.
3. dedup에 owner/action/media를 포함한다. 동일 PNG라도 다른 동작은 별도 immutable object를 써 저장량이 늘어난다. blob content addressing은 후속이다.
4. 증거 복구는 execution checkpoint와 독립이다. 서버가 cached ACK/new late를 계속 구분해야 하며 어떠한 동작 재개 권한도 얻지 않는다.
5. exact prepare-<attempt> ID와 구조화 log를 예약한다. 외부 worker는 이 계약을 지켜야 하며 준비 기록을 gesture 검토 근거로 제출할 수 없다.
6. 기존 전체9개 실패를 기준선과 비교하며 안전 gate를 완화하지 않는다. 그 실패 자체가 해결된 것은 아니다.
7. 리뷰 유보 B2.3/C/D는 미완료다. 실제 앱 foreground 관찰은 모델/검증 수용을 보장하지 않고 final suite는 작성자가 직접 실행한다.

다음: [B2.3 검사 mapping·결과 저장](../../managed-pc/CASE_CONTEXT_CONSUMER_TASKS.md). _NoTransport placeholder 교체와 논리 step→gesture mapping/required checks/ITEM 결과를 구현한 뒤 C 서버 verifier/episode 권한·D 제한 치유를 연결한다. 운영 키 부재로 로컬 구현을 멈추지 않는다.

기존 tests/integration/test_w27.py는 전체 실행에서 docs/validation/metadata-load.md의 성능 보고서를 자동 재생성한다. 테스트 전부터 dirty였던 이 파일은 수동 편집/복원하지 않고 commit에서 제외했다.
