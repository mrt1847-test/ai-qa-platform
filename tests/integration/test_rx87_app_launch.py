"""Fixed selected-package launch; no model, discovery, retry or arbitrary command."""
from pathlib import Path
import subprocess
import pytest


def driver(calls,result=None):
    from aiqa.environments.android_app_launch import AndroidAppLauncher
    def run(argv,timeout):
        calls.append(tuple(argv))
        if isinstance(result,Exception):raise result
        body=b'mCurrentFocus=Window{42 u0 com.ebay.kr.gmarket/.Main}' if 'dumpsys' in argv else b'Status: ok\nActivity: com.ebay.kr.gmarket/.Main\n'
        return result or subprocess.CompletedProcess(argv,0,body,b'')
    return AndroidAppLauncher(Path('C:/platform-tools/adb.exe'),'emulator-5580',run=run)


def test_launch_uses_only_selected_package_fixed_argv_and_final_gate():
    calls=[];events=[];launch=driver(calls)
    receipt=launch.launch('com.ebay.kr.gmarket',before_native_send=lambda:events.append('gate'))
    assert events==['gate'] and len(calls)==2 and receipt.package=='com.ebay.kr.gmarket'
    assert calls[0][-1]=='com.ebay.kr.gmarket' and 'android.intent.action.MAIN' in calls[0]
    assert 'android.intent.category.LAUNCHER' in calls[0] and '-W' in calls[0]
    assert 'android.settings.SETTINGS' not in calls[0]


@pytest.mark.parametrize('package',['','-W','a;reboot','com.test/app','https://x','com.x x'])
def test_bad_package_never_reaches_device(package):
    from aiqa.environments.android_app_launch import AppLaunchRejected
    calls=[];launch=driver(calls)
    with pytest.raises(AppLaunchRejected):launch.launch(package,before_native_send=lambda:None)
    assert calls==[]


def test_final_gate_rejection_never_starts_native_command():
    calls=[];launch=driver(calls)
    def deny():raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError):launch.launch('com.ebay.kr.gmarket',before_native_send=deny)
    assert calls==[]


@pytest.mark.parametrize('result',[subprocess.TimeoutExpired('mock',1),subprocess.CompletedProcess([],1,b'',b'error'),subprocess.CompletedProcess([],0,b'Error: intent failed',b''),subprocess.CompletedProcess([],0,b'Status: ok\nActivity: com.other/.Main',b'')])
def test_unknown_native_outcomes_never_retry(result):
    from aiqa.environments.android_app_launch import AppLaunchUnknown
    calls=[];launch=driver(calls,result)
    with pytest.raises(AppLaunchUnknown):launch.launch('com.ebay.kr.gmarket',before_native_send=lambda:None)
    assert len(calls)==1


@pytest.mark.parametrize('window',[b'mCurrentFocus=Window{42 u0 com.other/.Activity}',b'mCurrentFocus=Window{42 u0 Application Not Responding: com.android.systemui}'])
def test_blocking_or_foreign_window_does_not_confirm_selected_app(window):
    from aiqa.environments.android_app_launch import AndroidAppLauncher,AppLaunchUnknown
    def run(argv,timeout):
        body=window if 'dumpsys' in argv else b'Status: ok\nActivity: com.ebay.kr.gmarket/.Main\n'
        return subprocess.CompletedProcess(argv,0,body,b'')
    launch=AndroidAppLauncher(Path('C:/platform-tools/adb.exe'),'emulator-5580',run=run)
    with pytest.raises(AppLaunchUnknown):launch.launch('com.ebay.kr.gmarket',before_native_send=lambda:None)


def test_real_adb_crlf_output_confirms_same_selected_foreground():
    from aiqa.environments.android_app_launch import AndroidAppLauncher
    calls=[]
    def run(argv,timeout):
        calls.append(tuple(argv))
        body=(b'mCurrentFocus=Window{42 u0 com.ebay.kr.gmarket/.LauncherDefault}\r\n' if 'dumpsys' in argv
              else b'Starting: Intent {}\r\nStatus: ok\r\nLaunchState: UNKNOWN (0)\r\nActivity: com.ebay.kr.gmarket/.eBayKoreaGmarketActivity\r\nComplete\r\n')
        return subprocess.CompletedProcess(argv,0,body,b'')
    launch=AndroidAppLauncher(Path('C:/platform-tools/adb.exe'),'emulator-5580',run=run)
    receipt=launch.launch('com.ebay.kr.gmarket',before_native_send=lambda:None)
    assert receipt.package=='com.ebay.kr.gmarket' and launch.native_calls==1 and len(calls)==2
