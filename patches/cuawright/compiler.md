# Web IPC compiler

상태: **정적 변환만.** 기준 문법 subset은 W01에서 확인한 `click`, `fill`, `scroll`, `select`이다.

`compile_replay_package`는 raw source를 실행하지 않는다. AST에서 `qa_runtime`의 그 네 호출과 문자열 expected만 남긴다. selector와 value와 expected 문장은 바꾸지 않고, 각 행동은 `qa_runtime` 호출로 매핑한다.

다음은 거절한다. 동적 import, reflection, helper 정의와 호출, raw Playwright/CDP/browser, subprocess, file, network, LLM 호출, 인자가 중첩된 compound 행동.

이 AST 검사는 sandbox가 아니다. 실제 driver 경계와 네트워크 분리는 W29-03에 남긴다. 이 문서는 Windows에서 VM이 열렸다는 뜻이 아니다.
