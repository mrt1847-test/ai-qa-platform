# RX87 B2.3b3b1a · 기존 XML 수집의 공통화

- 상태: complete (공통 collection/CLI·worker port 범위). BASE master66a9132; 이 파일을 포함한 로컬 커밋이 완료 revision이다.
- 선행: B2-ANDROID-HIERARCHY/B2-CHECK-BINDING-PIN, 중복 검토. 계약 C05/C06. DB migration/UI/승인/source 명령 변경 없음.
- Mobile-Agent의 원본 main·prompt·화면 판단은 변경하지 않는다. 일반 managed 녹화의 기존 PNG capture는 XML을 요구하지 않는다. 기존 실제 검증 CLI에 있던 XML 수집만 공통 포트로 옮겼다.

## 제공 interface·소비

`environments.android_hierarchy_reader.AndroidHierarchyReader(observer,package=...,checkpoint=...,extra_packages=(),command_timeout=15,total_timeout=30)`는 기존 AndroidObservationProvider와 bounded ADB runner를 쓴다. 명시 serial/AVD와 동결한 SDK/device identity, 선택 foreground, 전후 geometry/density, command/전체 deadline, 각 native read와 결과 projection 뒤 현재 제어를 확인한다. checkpoint는 명시 sync callable/true만 허용한다. 내부 read는 total/개별 command cap과 provider cap의 최솟값을 사용하고 shared provider 설정을 바꾸지 않는다.

- `capture_once()->(Observation,foreground)`: CLI용 PNG1회+local raw DOM. caller의 기존 sanitize 이후만 사용한다. 외부 업로드/정제 완료를 이 포트가 주장하지 않는다.
- `observe_targets(resource_ids)->AndroidHierarchyObservation`: frozen snapshot/geometry/captured_at/foreground. 선택한 source resource의 local 관찰 사실이며 PNG0/모델0/QA 판정0이다. captured_at은 XML read 완료 시각이며 별도 PNG와 원자적으로 같은 시각이라는 뜻이 아니다.
- public 실패는 고정 reason AndroidHierarchyReadError이며 raw stdout/stderr/decoder exception context를 담지 않는다. invalid 대상은 ADB 전에 거절한다.

고정 argv exec-out uiautomator dump /proc/self/fd/1을 사용한다. 장치 XML 임시 파일/cat/rm의 별도 사본을 없앴고 기존 CLI가 동일 Reader를 호출한다. 원래 wire 길이를 먼저 검사하고 공식 완료 suffix와 명시 LF/CRLF만 처리한다. 원문·추가 trailer·잘못된 UTF8/회전/XML은 결과로 반환하지 않는다.

`AndroidObservationProvider.observe(capture=True,deadline=None,checkpoint=None,command_timeout=None)`는 optional per-call 제약만 additive다. 기본 호출의 동작은 유지한다. ready 반환 전에도 제어/시간을 재확인한다.

`AndroidReplayContext.hierarchy_observer` optional callable과 실제 approved replay factory의 포트를 추가했다. 호출은 `package,resource_ids,checkpoint,timeout` keyword-only이며 native lookup은 호출할 때만 발생한다. builder 생성/일반 녹화에 추가 XML·모델 호출0이다. 실제 check 경계에서 호출하는 consumer는 다음 b3b1b다. 이 포트만으로 기존 required unknown/PASS를 바꾸지 않았다.

## XML·기존 재생 호환

`android_hierarchy_xml.read_hierarchy_xml(raw,rotation=None)`가 strict UTF8/NUL/DTD/ENTITY/단일 hierarchy/1MiB/4096 UI node/depth64를 소유한다. raw tree는 local 소비용이고 정제 결과가 아니다. selected-resource facts와 기존 frame guard가 같은 decoder를 쓰며 대상 보호와 기대값 assertion 의미는 합치지 않는다. frame guard의 기존5000/no-depth 제한을 이 공통4096/depth64로 통일했다. 실제 native root에 있는 rotation을 빠뜨린 기존 synthetic fixture1개를 올바른 형식으로 보완했다. 저장 source/pin bytes는 바꾸지 않았다.

replay reference XML 한도도 같은1MiB로 맞췄다. 1,000,000~1,048,576 사이를 녹화는 허용하고 재생은 거절하던 불일치를 제거했다. 최대 명령 수/좌표/expected/승인 조건은 완화하지 않았다.

CLI는 알려진 focus 전환/일시 dump 실패·빈 root read만 기존 capture_stable로 제한 재시도한다. wrong AVD/통제 상실/잘못된 증거는 즉시 중단한다. capture-transitions.json은 reason/count/시각만 최대50개로 보존하며 raw 진단을 복사하지 않는다.

## 검증·검토

초기 RED16, 추가 consumer/None rotation·mutable observer identity·wrong-AVD retry RED를 보완했다. 한 fresh reviewer Important5+Minor1을 RED9(wire padding/최종 projection gate/metadata command cap/녹화·재생 한도/일시 dump retry·transition 기록)로 재현해 한 fix pass로 해결했다. re-review 없음.

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_android_hierarchy_reader.py tests/unit/test_android_hierarchy.py tests/integration/test_android_observation.py tests/unit/test_mobile_agent_session.py tests/integration/test_mobile_agent_process.py tests/integration/test_rx87_case_context_consumer.py -q -p no:cacheprovider --tb=short
```

최종 **192 passed55.45s**. CLI closure는 실제 소스를 추출해 공통 Reader+기존 sanitize/transition retry를 실행하는 unit integration grade이며 CLI 전체 녹화/재생 수용이 아니다. 실제 worker factory port와 default recording PNG-only, 원본 child/process/history·frame guard 회귀를 포함했다. 전체 suite green/실제 앱 TC 수로 표시하지 않는다. 기존 전체6개 실패 기준선은 유지한다.

실제 전용 Medium_Phone_API_36/emulator-5580을 read-only/headless로 구동해 **Android launcher**에서 새 Reader를 호출했다. 1080x2400/rotation0,8.594s,선택3 resource가 available 관찰, composite PNG1/XML2회, check-only PNG0,모델0/gesture0/새 app launch0이었다. raw PNG/XML은 저장하지 않았다. [실제 관찰 report](../evidence/ANDROID-HIERARCHY-SHARED/live-system-report.json). available은 읽을 수 있다는 뜻이며 assertion PASS가 아니다.

이 인스턴스에는 G마켓이 설치돼 있지 않아 최초1회 app start의 확인이 AppLaunchUnknown으로 끝났다. readonly pm path 확인 후 재기동·추정 클릭·설치를 하지 않았다. [별도 준비 실패](../evidence/ANDROID-HIERARCHY-SHARED/live-gmarket-preparation.json)를 보존한다. 위 launcher 관찰을 G마켓 수용으로 대체하지 않는다. 실제 SDK 앱 준비는 명시 install policy/지정 APK가 있는 실행 단위에서 재개한다. 키/독립 서버 부족으로 로컬 구현을 차단하지 않는다. 검사 후 작업이 시작한 동일 AVD를 확인해 종료하며 snapshot/사용자 DB/앱 data reset/계정·권한 변경0이다.

## 다음

b3b1b는 actual claim의 logical mapping 시점에 이 read port를 사용하고 deterministic text/명시 state를 평가한다. 미연결/unsupported/value·visibility field 부재/읽기 실패는 unknown이다. AI fallback은 승인된 C 경로가 있을 때만 사용한다. c에서 normalized check_results/ITEM과 source provenance를 영속화한다. 녹화 기록은 저장 후 사람이 검토·승인하며 XML은 보조 관찰이다. 전체 RX87·87/99·49/53 완료 수는 유지하고 metadata-load.md는 기존 dirty로 보존·커밋 제외했다.
