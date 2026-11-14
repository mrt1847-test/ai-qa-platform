# RX87 B0.5 · 증거 시각·purpose 권한 인계

- 상태: complete(core_contract). 기준 master1eb17af, 2026-11-14. C00/C04/C05/C14. DB migration/기존 데이터 수정·실제 모델 API/AVD 최종 수용·배포/설치 없음.
- evidence-commits와 legacy events HTTP 경로의 worker now는 metadata로만 검증한다. 두 경로가 전달하는 관리 서버 clock callable을 writer transaction 취득 뒤 샘플링해 새 데이터의 lease/late/stale를 판정한다. API JSON으로 trusted clock을 선택할 수 없다.
- store/evidence.py의 공통 gate는 project와 실제 job purpose를 worker scope와 대조하며 cached receipt 조회에도 적용한다. 같은 worker ID의 다른 용도 토큰으로 recording evidence/event를 저장하지 못한다. 직접 호출되는 trusted core의 명시 deterministic time seam은 보존한다.
- 이미 commit한 같은 key/본문 receipt는 lease 만료 뒤에도 같은 ACK로 읽는다. 새 만료 업로드는 late/stale inbox로 분리하며 ready artifact/활성 prefix로 올리지 않는다. 과거 source/FAIL/승인/bytes를 변경하지 않았다. 다음 실제 동작에는 별도 fresh checkpoint가 필요하다.
- RED4→GREEN: evidence/event 양쪽의 과거 시각 임대 우회와 wrong-purpose 저장 허용을 실제 API에서 재현했다. 기존 receipt 재조회, 지연 wrapper, 실제 SQLite writer lock 대기 중 시각 변경도 확인했다. 관련 집중39pass, 재개 후 owning file6pass(8.04s), 최종 전체9failed825passed1skipped(558.85s). failure node9는 기존 기준선과 정확히 같으며 전체 green은 아니다. 로그 .review-work/evidence-authority/resume-full.log.
- 별도 리뷰 Critical/Important/Minor 없음. 실제 SQLite contention coverage 부족은 추가 actual-lock 회귀로 보완했으며 재리뷰는 하지 않았다. live provider/기기/배포와 I/O 응답성은 미수용이다.
- 범위: 별도 worker/artifacts는 api/artifacts.py의 pre-wait 시간과 store/artifact_ingest.py의 final transaction 이전 시각을 사용한다. 모든 artifact ingress가 post-wait authority를 샘플링한다고 주장하지 않는다. 파일 I/O/DB writer 점유와 이 저장 경계는 B0.6 후속이다.
- 판단: purpose를 central store에서 확인한다(잘못 설정한 worker role은 새403이 될 수 있음). server authority와 worker capture time을 분리한다(새 late 데이터는 승인 준비로 승격되지 않음). 저장 receipt와 실행 권한을 분리한다(다음 action은 fresh fence 필요). trusted time seam은 HTTP가 선택하지 못한다(다른 내부 호출자는 clock 출처를 명시해야 함).
- 다음 B0.6. B/C/D·replay/Web·선택 package와 실제 환경 수용은 미완료이며 상위 RX87 in_progress 유지.
