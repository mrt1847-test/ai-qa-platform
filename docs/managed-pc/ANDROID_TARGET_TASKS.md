# RX87 B2.2b · 선택 앱 준비/저장 근거

Spec: CASE_CONTEXT_CONSUMER_TASKS B2.2b. 실행은 executing-plans/TDD inline, 마지막 fresh review1회/필수 수정1회. BASE cd07bf4, master. 사용자 C:/apk APK는 G마켓 com.ebay.kr.gmarket 10.8.6-debugFinal, sha256:8b1cc87206eb5fbaaae6ee6ba4f97cab8b6e573bd157d279af536ca33ac68a1a, 47,049,119 bytes. 앱 이름/파일은 검증 fixture이며 제품에 하드코딩하지 않는다.

1. 새 environments/android_app_launch.py: 명시 absolute adb/등록 serial, package 문법, 고정 MAIN/LAUNCHER am start -W argv, 전송 직전 callback, timeout/비정상 응답 unknown/no retry. 설치/초기화/임의 shell 없음. 공식 https://developer.android.com/tools/adb#am 및 intent arguments의 package 인자 근거.
2. 새 worker/android_prepare.py: immutable WorkerCaseContext만 소비. secret refs coverage 미확인 시 upload/native 전 차단. 같은 attempt 준비는1회. capture/filter→durable planned→native 직전 fresh gate/dispatch_started→after capture/filter→observed→정제 PNG2+구조화 log1 ACK. 전송 전 실패 not_sent, native 이후 미확정 unknown. 같은 요청 ACK 확인은 증거만 재전송하고 앱 시작/촬영 재실행0.
3. 준비 ACK는 events=[]로 prefix를 바꾸지 않는다. StepEvidenceCommitter에 고정 namespace를 추가하고 기존 step 기본값은 유지한다. 준비 전용 key로 기존 gesture/source key와 분리한다. 아티팩트 owner/action은 REC/ITEM source 소유를 지킨다. 실패 재시작은 journal로 막고, 원래 ready/승인/FAIL을 수정하지 않는다.
4. Android recording/replay handler/builders에 preparer/직후 frame을 연결하고 Settings 하드코딩 제거. 기존 explicit development prepare callback은 테스트 seam. 공식 runtime은 client를 공급하며 current checkpoint/local time/cancel을 준비 전/실제 native 전/ACK 후 재검사한다. 초기화는 gesture plan과 구분해 attempt당1회 bounded operation(기존 준비 동작 범위), global native50 중 준비1회를 예약해 녹화 gesture<=49, replay50줄은 준비 전 거절한다. per-pin 한도는 별도로 유지한다. 실제 native 준비도 별도 journal/log에 남긴다.
5. 실제 API/DB의 prep/step key 충돌0·prefix0·ACK 유실/native timeout/취소/재사용·비밀/다른 owner·offline bytes 조회를 검증하고 UI에서 저장 근거 링크를 확인한다. 단순 helper 성공을 전체 검토/승인 성공으로 보고하지 않는다.
6. supplied APK 메타데이터/해시를 확인하고 전용 기존 AVD에서 설치 필요 여부부터 검사한다. 초기화/강제 재설치/계정·구매 동작 없이 선택 앱 시작만 수용한다. 실제 모델 API0이며 앱 시작 확인은 assertion/회귀 최종 수용이 아니다. 전체 baseline 비교·handoff/큐/master commit.

Review focus: hardcoded/wrong package, callback 뒤 native가 나가는 시각, known-before-send vs unknown, journal 재시작/ACK 유실 뒤 재시작, raw pixels/secret refs, prefix/key collision, 준비1회와 gesture cap 분리, 실제 app start와 QA 성공 구분. UI/서버에 새 grant를 만들지 않는다.
