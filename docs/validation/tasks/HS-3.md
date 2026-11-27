# HS-3 비공개 원격 증거 저장 구현 인계

- 상태: **complete — 코드/모의 REST·ASGI 계약 검사**. 실제 Supabase 서비스 수용은 미실행이다.
- 기준: master `3525226`; [저장 계약](../../managed-pc/PRIVATE_STORAGE.md), [HS-2](HS-2.md).

## 제공 interface와 실제 배선

`artifact_root()`는 local에서 기존 Path, hosted에서 `DurableArtifactRoot`를 만든다. API가 service key를 소유하고 worker는 기존 HTTPS artifact API만 사용한다. PNG/log, evidence commit/viewer/timeline, recovery, export, APK, retention 경로를 연결했다. package/승인 metadata는 SQL에, source 파일은 private Storage에 둔다.

private bucket 확인 → immutable object upload → authenticated GET의 hash/length 검증 후에만 ACK한다. cache는 없어져도 복원할 수 있고 cache만으로 성공을 만들지 않는다. upload 응답 유실 시 같은 key/bytes를 확인해 재사용한다. recovery manifest는 같은 요청의 UUID5 identity, export는 frozen snapshot의 queued job, APK는 project/hash stage를 재사용한다. 원격 I/O는 event loop와 SQL writer 밖에서 수행하고 마지막 SQL 확정만 짧은 트랜잭션에서 한다.

새 server secret key는 apikey header만, legacy service_role JWT는 Bearer도 사용한다. 실제 Storage의 HTTP400/structured NoSuchKey 응답만 정확히 missing으로 처리하고 일반400·auth·bucket 오류를 missing으로 보지 않는다. retention은 인증/권한 및 pin을 먼저 확인하고 실제 원격 삭제를 검증한 뒤 metadata를 갱신한다. HTTP redirect/ambient proxy를 사용하지 않으며 timeout과 크기를 제한한다.

## 검증

2026-11-27 집중 회귀:

```text
python -B -m pytest tests/unit/test_hosted_key_ref.py tests/unit/test_hs3_object_storage.py tests/integration/test_hs3_remote_evidence.py -q -p no:cacheprovider --tb=short
77 passed in 25.85s
```

실제 프로토콜 형태의 모의 Supabase REST와 임시 SQLite metadata/ASGI를 사용했다. cache 삭제 후 읽기/승인, 같은 승인 package의 AI0 재생, timeout/응답 유실·다른 bytes·권한 오류·delete 실패, APK/export retry, slow remote I/O 중 heartbeat를 확인했다. recovery retry의 중복 remote 객체, 권한 확인 전 retention download, 잘못된 UUID type의 500은 먼저 실패를 확인한 뒤 수정했다. 실제 Supabase/유료 모델/ADB 호출 0이다.

## 제약

임시 cache는 쓰기 가능해야 한다. 원격 전체 orphan 열거/운영 backup·복원/대용량 resumable upload는 제공하지 않는다. 불명 SQL 결과의 staged object는 보존한다. live video는 일시 transport이며 녹화 archive가 아니다. 상세 범위는 저장 계약을 따른다. 실제 bucket/서비스 key/네트워크와 worker PC가 꺼진 상태의 독립 브라우저 수용은 HS-4~6에 남는다.
