# HS-6 분리 배치 여정 인계

- 구현/합성 검사 상태: **complete — 서버 저장 근거 조회·검토·승인·동일 package AI0 재생과 cache 손실 검사**.
- 실환경 수용 상태: **not_started — 다른 네트워크 브라우저/운영 IdP/현재 PC 전원 종료 여정 미실행**.
- 선행: HS-4 실제 배포와 HS-5 PC 등록. [운영 절차 5절](../../managed-pc/FLY_HOSTED_RUNBOOK.md#5-실제-수용-체크).

`test_hs3_remote_evidence.py`에서 정상 worker upload API→ACK 후 cache 손실/worker offline의 조회, 모의 private object에 저장한 source→사람 review/approval→동일 package actor AI0/healing OFF 재생을 확인했다. 실제 Postgres의 approval/package 원자성은 별도 HS-2 검사다. 모든 조합을 실제 배포에서 끝까지 실행한 것으로 합산하지 않는다.

실제 수용은 다음을 모두 기록한다:

1. 다른 네트워크 브라우저로 운영 OIDC 로그인과 프로젝트 접근.
2. online Android worker의 작은 실제 AI 녹화와 동작별 PNG/log의 SQL metadata·Storage object·ACK 일치.
3. 저장 후 사람 승인으로 테스트용 승격, 같은 package AI0/healing OFF 재생과 별도 검증 결과.
4. worker PC OFF 및 서버 cache 없는 재시작 뒤 이미 ACK된 녹화·근거 검토/승인 가능. 새 녹화·재생은 불가.
5. worker 재연결 뒤 중단 native 자동 재실행 0. 사용자가 새 실행을 명시해야 한다.

운영자 승인 없이 전원을 끄거나 실제 유료 호출을 하지 않는다. 실제 결과를 이 파일에 추가하기 전까지 HS-6 수용은 미완료다. 월3,000건 비용/처리량 RX-29와 Web VM 수용은 별도이며 위 합성 성공으로 완료하지 않는다.
