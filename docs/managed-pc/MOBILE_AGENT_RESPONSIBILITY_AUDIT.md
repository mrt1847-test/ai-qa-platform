# Mobile-Agent와 플랫폼 기능 중복 검토

2026-11-17, original master71c92fc 기준. 검토 대상은 vendored Mobile-Agent v3.5 commit81fa28b564ef7a695521500bc15a0e1324b2b394와 현재 녹화/replay/계층 구현이다. 공개 프로젝트의 모든 버전에 기능이 없다고 일반화하지 않는다.

## 결론

최근 검증 연결 pin/명시 resource XML 관찰은 Mobile-Agent의 AI 행동 판단 재구현이 아니다. 다만 프로젝트 내부에 기존 XML 수집 CLI와 별도 frame guard XML 해석이 있다. 새 수집기를 병렬로 만들지 않고 기존 수집·관찰 경로를 제품 공통 포트로 추출해 재사용해야 한다. 검토 당시 새 production native XML reader는 아직 작성하지 않았으며 이 검토로 구현 방향을 수정했다. 이후 [b3b1a 인계](../validation/tasks/RX-87-B2-ANDROID-HIERARCHY-READER.md)대로 공통 수집 포트를 추출하고 기존 CLI가 이를 소비하도록 전환했다. 일반 managed 녹화의 PNG 경로는 XML을 요구하지 않는다.

| 책임 | 실제 원본/현재 코드 | 판단 |
|---|---|---|
| 화면→다음 AI 행동, prompt/history, action parser/좌표 변환 | 원본 run_gui_owl_1_5_for_mobile.main175~204와 utils.build_messages. adapters/mobile_agent_upstream.run_upstream은 실제 main을 실행한다 | 원본 재사용. 별도 AI 판단 루프를 추가하지 않는다 |
| screenshot/탭/스와이프/키/입력 I/O | 원본 utils.AdbTools에 있다. run_upstream이 AdbTools를 IO 어댑터로 교체하고 mobile_agent_child가 parent RPC로 위임한다 | 기능상 접점은 겹치지만 동시 이중 실행이 아니다. 플랫폼의 선택 기기/lease/전송 전 journal/정제/ACK를 통과시키는 어댑터다 |
| 기본 스크린샷/history 저장 | 원본 main274~280은 local history/annotated PNG를 남긴다 | 이 자료는 재사용한다. 플랫폼 DB의 attempt/typed physical source/ACK 증거·사후 승인·버전 관리를 원본 local history로 대신할 수는 없다 |
| 녹화 후 AI0 재생 | 원본 main175~190은 매 turn 새 화면으로 VLM을 호출한다. 플랫폼의 native trace/package/AndroidReplayHandler는 저장 명령을 실행한다 | 사용자 비용 목표를 위한 플랫폼 책임. 테스트 때 original AI main 전체를 다시 돌리지 않는다 |
| source check와 실제 gesture 경계/resource 연결 | recording.check_bindings와 worker.check_binding_pin | 플랫폼 TC/검증 계약. logical step과 gesture ordinal을 임의 동일시하지 않는다 |
| 지정 resource의 deterministic text/상태 관찰 | 새 environments.android_hierarchy; 원본 pinned main/utils/packages에는 UIAutomator XML/resource assertion 경로가 없다 | AI 없이 검증하기 위한 추가 책임. 화면 판단 AI를 복제한 것이 아니다 |
| 실제 XML 수집 | tools/android_mobile_agent_record_replay.py:51의 capture_once가 dump→cat→삭제→기존 PNG provider→focus 확인을 이미 수행한다 | 새 수집 알고리즘을 복제하지 않고 공통 모듈로 추출해야 한다. CLI와 운영 worker 모두 같은 포트를 사용한다 |
| XML 기반 재생 target 보호 | recording.mobile_agent_frames._anchor/require_guarded_frame | 클릭할 대상이 바뀌었는지 보호하는 기능이며 기대값 assertion과 다르다. 공통 bounded XML decode는 재사용하되 target 보호를 assertion PASS와 합치지 않는다 |

## 바로 반영한 실행 방향

1. original main/build_messages/parse_action/rescale을 유지한다. 모델 스크린샷 판단 루프·별도 탭/스와이프 명령 실행기를 새로 추가하지 않는다.
2. 다음 b3b1a는 기존 CLI capture_once의 native XML 수집을 공통 코드로 추출하는 작업이다. AndroidObservationProvider와 기존 bounded ADB runner를 재사용하고 focus/선택 serial·AVD/현재 제어/deadline/정제 계약을 보존한다. old CLI 구현을 남겨 둔 채 worker용 사본을 추가하지 않는다.
3. _anchor와 assertion의 목적은 유지하되 낮은 수준의 XML decoding/한도 검사가 둘로 계속 갈라지지 않게 공유 가능한 경계를 대조한다. bounds/target 보호를 새 selected-resource 관찰 API에 억지로 섞거나 guard를 제거하지 않는다.
4. b3b1b는 pin의 명시 경계에 observer/validator를 연결했다. c가 결과를 영속화한다. 검증 필요 시점만 계층을 읽고 매 행동의 AI 재호출/불필요한 중복 PNG 수집을 만들지 않는다. AI 보완과 제한 healing은 승인된 별도 경로다.

## 근거·확인 범위

- 원본 [main](../../third_party/mobile_agent/upstream/run_gui_owl_1_5_for_mobile.py), [AdbTools/build_messages](../../third_party/mobile_agent/upstream/utils.py), [source pin](../../third_party/mobile_agent/manifest.json).
- [원본 main I/O 교체](../../src/aiqa/adapters/mobile_agent_upstream.py), [child RPC](../../src/aiqa/worker/mobile_agent_child.py), [서버 연결 녹화](../../src/aiqa/worker/mobile_agent_recording.py), [기존 실제 검증 CLI](../../tools/android_mobile_agent_record_replay.py), [기존 frame guard](../../src/aiqa/recording/mobile_agent_frames.py).
- UIAutomator의 파일 대상/완료 메시지와 XML password/rotation 필드는 [고정 AOSP DumpCommand](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/+/88c7ff1cd72d6305ec59f97aadc2198cc2dc3592/android-34/com/android/commands/uiautomator/DumpCommand.java), [Dumper](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/+/88c7ff1cd72d6305ec59f97aadc2198cc2dc3592/android-34/com/android/uiautomator/core/AccessibilityNodeInfoDumper.java)를 대조했다. 코드를 복사하지 않았다.
- 실제 전용 Medium_Phone_API_36/emulator-5580을 read-only/headless로 시작해 고정 exec-out uiautomator dump /proc/self/fd/1의 XML+완료 suffix를 확인했다. 수집4.89s/13658bytes/1080x2400/rotation0이고 pure parser가 수용했다. XML 원문 저장/AI 호출/기기 gesture0이다. 이는 reader 전송 방법 probe이며 G마켓 assertion이나 운영 worker 연결의 수용 증거가 아니다. raw SDK 경로/키를 문서에 복사하지 않았다.

[현재 소비 계획](CHECK_BINDING_RUNTIME_TASKS.md)과 root NEXT에 이 추출 순서를 반영했다. 기존 구현 완료/AI-LIVE-03 증거와 RX87 전체 미완료를 유지한다.
