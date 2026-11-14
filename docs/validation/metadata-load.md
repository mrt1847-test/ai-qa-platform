# metadata 부하 측정

합성 전용 SQLite에서 최근 30일 추세와 event 페이지를 측정했다. 파일 입출력과 기기 지연은 이 수치에 넣지 않았다. 목표 밀리초는 제안 규모이며 실기기 성능 입증이 아니다.

- 항목 10000
- 행동 100000
- 추세 제안 목표 1000ms, 측정 p95 5.635ms
- event 페이지 제안 목표 500ms, 측정 p95 0.183ms
- 담당이 없는 시나리오 0

추세 query plan:

```text
6 0 0 SEARCH items USING COVERING INDEX items_requested (requested_at>? AND requested_at<?)
15 0 0 USE TEMP B-TREE FOR GROUP BY
```

event query plan:

```text
6 0 0 SEARCH events USING COVERING INDEX events_seq (seq>?)
```

| 시나리오 | 상태 | 담당 |
|---|---|---|
| DATA-1 | complete | W04-03, W05-02, W06-04, W18-01 |
| DATA-2 | complete | W08-04, W14-04, W16-05, W19-01 |
| DATA-3 | not_started | W16-08, W19-02, W19-04 |
| DATA-4 | not_started | W17-04, W18-04, W19-01 |
| DATA-5 | complete | W19-01, W19-03, W26-02 |
| DATA-6 | not_started | W19-04, W20-02, W21-03 |
| DATA-7 | not_started | W14-04, W16-07 |
| DATA-8 | complete | W24-05, W26-01, W26-05 |
| DATA-9 | complete | W22-03, W23-01, W24-01 |
| DATA-10 | complete | W05-01, W24-02, W24-04 |
| DATA-11 | complete | W06-04, W18-01, W18-03 |
| DATA-12 | complete | W06-04, W26-02 |
| DATA-13 | complete | W06-06, W15-02, W24-05, W25-01 |
| DATA-14 | complete | W27-04 |
| DATA-15 | not_started | W06-05, W29-04, W16-07 |
| DATA-16 | not_started | W15-01, W17-03, W29-05, W30-04 |
| DATA-17 | not_started | W13-03, W31-02, W31-03, W31-07 |
| DATA-18 | not_started | W17-04, W23-05, W31-04, W31-07 |
| DATA-19 | not_started | W16-08, W31-05, W19-04, W31-07 |
| DATA-20 | not_started | W06-06, W15-02, W24-02, W24-05, W31-07 |
| DATA-21 | blocked | W01-02, W07-02, W29-03 |
| DATA-22 | not_started | W32-01, W32-02, W32-03 |
| EXEC-1 | not_started | W29-05, W30-04 |
| EXEC-2 | not_started | W15-03, W17-03, W15-04, W17-04, W32-02 |
| EXEC-3 | not_started | W31-01, W31-02, W31-04, W31-07 |
| EXEC-4 | not_started | W06-05, W18-01, W31-02, W31-07 |
| EXEC-5 | not_started | W13-03, W31-02, W31-03, W31-04, W31-07 |
| EXEC-6 | not_started | W17-04, W23-01, W23-05, W31-07 |
| EXEC-7 | not_started | W31-05, W16-08, W19-04, W31-07 |
| EXEC-8 | blocked | W01-02, W29-02, W29-03 |
| EXEC-9 | complete | W24-05, W26-02 |
| EXEC-10 | not_started | W32-02, W32-03, W31-07 |

상태는 색인의 담당 작업 상태다. 미실행과 차단을 구현 완료로 바꾸지 않는다.
