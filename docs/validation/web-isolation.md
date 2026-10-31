# Web 격리 탐색

상태: **차단.** 같은 PC에 disposable Linux VM이 없고, 합성 script를 실행하지 못했다. 아래 값은 호스트에서 방금 실행한 명령의 결과이며 격리 합격이 아니다.

## 호스트

| 항목 | 관찰 |
|---|---|
| 제품 | Windows 10 Home, EditionID `Core`, DisplayVersion 25H2, build 26200 |
| HypervisorPresent | `True`. VM 관리 서비스는 없다 |
| `sc query vmms` | exit 1060, 서비스 없음 |
| `sc query vmcompute` | exit 1060, 서비스 없음 |
| `sc query LxssManager` | exit 1060, 서비스 없음 |
| `wsl.exe --status` | exit 50. Linux용 Windows 하위 시스템이 설치되어 있지 않음 |
| docker / qemu-system-x86_64 / VBoxManage | 없음 |
| 선택적 기능 조회 | 관리자 권한이 없어 `Get-WindowsOptionalFeature`는 실행하지 않았다 |

Windows Home에서는 Hyper-V VM 역할을 켤 수 없다. `HypervisorPresent`는 그 역할이 있다는 뜻이 아니다.

## 아직 실행하지 않은 준비와 파기

의도한 backend는 `hyper-v` disposable Linux VM이다. 제품·버전·게스트 계정·네트워크 정책은 관찰하지 못했다. `prepare`와 `destroy`는 `not executed`다. WSL, Docker, QEMU를 대신 설치하지 않았다. 기본 WSL은 `/mnt/c`와 호스트 네트워크를 공유하므로, 설치만으로 이 카드의 거부가 증명되지 않는다.

## 합성 script

CDP 직접 접속, model endpoint 접속, host credential 읽기, subprocess 우회는 **시도하지 않았다.** `driver_ipc`, `direct_cdp`, `script_model_network`, `host_secret_access`는 모두 미측정이다.

프로세스 안의 IPC가 `cdp_url` 필드를 거부하는 것은 driver가 handle을 메시지에 넣지 않는다는 타입 제약이다. VM 밖 script의 네트워크 거부와는 다른 사실이다.

## 재개

같은 PC에서 script 권한의 Linux VM을 만든 뒤, 그 안에서 위 네 시도를 실행하고 거부 근거를 stdout JSON 한 건으로 남긴다. 그 전에 이 카드를 완료로 두지 않는다. Home 에디션에서 Hyper-V 역할을 켜는 것은 재개 방법이 아니다.
