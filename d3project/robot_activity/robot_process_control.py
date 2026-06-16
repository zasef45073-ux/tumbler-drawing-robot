import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional


# ============================================================
# robot_process_control.py
#
# 역할:
# - robot_algorithm_adapter.py, robot_process_adapter.py에서 실행하는
#   subprocess를 공통으로 추적/종료하기 위한 process manager
#
# 사용 목적:
# - 작업 중지(stop): 현재 실행 중인 subprocess 종료 후 STOPPED 처리
# - 일시정지(pause): 현재 실행 중인 subprocess 종료 후 PAUSED 처리
#
# 주의:
# - 이 파일은 프로세스를 종료할 뿐, 로봇의 정확한 경로 재개 지점을 저장하지 않음.
# - 다시 시작은 "현재 공정을 처음부터 다시 실행"하는 방식으로 처리하는 것이 안전함.
# ============================================================


@dataclass
class ManagedProcessInfo:
    """
    현재 실행 중인 subprocess 정보
    """

    label: str
    command: list
    pid: int
    started_at: float


_PROCESS_LOCK = threading.RLock()
_CURRENT_PROCESS: Optional[subprocess.Popen] = None
_CURRENT_PROCESS_INFO: Optional[ManagedProcessInfo] = None

_LAST_TERMINATION_REASON = ""
_LAST_TERMINATION_AT = 0.0


# =========================
# 상태 조회
# =========================

def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def get_current_process_info():
    """
    현재 등록된 subprocess 정보 반환
    """

    with _PROCESS_LOCK:
        if _CURRENT_PROCESS is None or _CURRENT_PROCESS_INFO is None:
            return None

        return {
            "label": _CURRENT_PROCESS_INFO.label,
            "command": _CURRENT_PROCESS_INFO.command,
            "pid": _CURRENT_PROCESS_INFO.pid,
            "startedAt": _CURRENT_PROCESS_INFO.started_at,
            "startedAtText": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(_CURRENT_PROCESS_INFO.started_at),
            ),
            "poll": _CURRENT_PROCESS.poll(),
            "running": _CURRENT_PROCESS.poll() is None,
        }


def has_running_process():
    """
    현재 실행 중인 subprocess가 있는지 확인
    """

    info = get_current_process_info()
    return bool(info and info.get("running"))


def get_last_termination_info():
    """
    최근 종료 요청 정보 반환
    """

    with _PROCESS_LOCK:
        return {
            "reason": _LAST_TERMINATION_REASON,
            "terminatedAt": _LAST_TERMINATION_AT,
            "terminatedAtText": (
                time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(_LAST_TERMINATION_AT),
                )
                if _LAST_TERMINATION_AT
                else ""
            ),
        }


# =========================
# 프로세스 등록 / 해제
# =========================

def _register_process(process, label, command):
    """
    현재 실행 중인 subprocess 등록
    """

    global _CURRENT_PROCESS
    global _CURRENT_PROCESS_INFO

    with _PROCESS_LOCK:
        _CURRENT_PROCESS = process
        _CURRENT_PROCESS_INFO = ManagedProcessInfo(
            label=label,
            command=list(command),
            pid=process.pid,
            started_at=time.time(),
        )

    print("=" * 70)
    print("[ProcessControl] subprocess 등록")
    print(f"[ProcessControl] label : {label}")
    print(f"[ProcessControl] pid   : {process.pid}")
    print(f"[ProcessControl] cmd   : {' '.join(command)}")
    print("=" * 70)


def _clear_process(process=None):
    """
    현재 subprocess 등록 해제

    process 인자가 주어지면 현재 등록된 process와 같을 때만 해제.
    """

    global _CURRENT_PROCESS
    global _CURRENT_PROCESS_INFO

    with _PROCESS_LOCK:
        if process is not None and _CURRENT_PROCESS is not process:
            return

        _CURRENT_PROCESS = None
        _CURRENT_PROCESS_INFO = None

    print("[ProcessControl] subprocess 등록 해제")


# =========================
# 프로세스 종료
# =========================

def terminate_current_process(
    reason="관리자 작업 중지 요청",
    terminate_timeout_sec=3.0,
):
    """
    현재 실행 중인 subprocess 종료

    종료 순서:
    1. process group에 SIGTERM
    2. terminate_timeout_sec 대기
    3. 아직 살아 있으면 process group에 SIGKILL

    반환:
    {
        "terminated": bool,
        "pid": int 또는 None,
        "label": str,
        "message": str
    }
    """

    global _LAST_TERMINATION_REASON
    global _LAST_TERMINATION_AT

    with _PROCESS_LOCK:
        process = _CURRENT_PROCESS
        info = _CURRENT_PROCESS_INFO

    if process is None or info is None:
        return {
            "terminated": False,
            "pid": None,
            "label": "",
            "message": "현재 실행 중인 subprocess가 없습니다.",
        }

    if process.poll() is not None:
        _clear_process(process)

        return {
            "terminated": False,
            "pid": info.pid,
            "label": info.label,
            "message": "subprocess가 이미 종료되어 있습니다.",
        }

    _LAST_TERMINATION_REASON = reason
    _LAST_TERMINATION_AT = time.time()

    print("=" * 70)
    print("[ProcessControl] subprocess 종료 요청")
    print(f"[ProcessControl] label  : {info.label}")
    print(f"[ProcessControl] pid    : {info.pid}")
    print(f"[ProcessControl] reason : {reason}")
    print("=" * 70)

    try:
        # start_new_session=True로 실행된 프로세스는 process group kill 가능
        pgid = os.getpgid(process.pid)

        print(f"[ProcessControl] SIGTERM process group: {pgid}")
        os.killpg(pgid, signal.SIGTERM)

    except ProcessLookupError:
        _clear_process(process)

        return {
            "terminated": False,
            "pid": info.pid,
            "label": info.label,
            "message": "프로세스가 이미 존재하지 않습니다.",
        }

    except Exception as e:
        print(f"[ProcessControl][WARN] SIGTERM 실패: {e}")

        try:
            process.terminate()
        except Exception as terminate_error:
            return {
                "terminated": False,
                "pid": info.pid,
                "label": info.label,
                "message": f"terminate 실패: {terminate_error}",
            }

    deadline = time.time() + float(terminate_timeout_sec)

    while time.time() < deadline:
        if process.poll() is not None:
            return {
                "terminated": True,
                "pid": info.pid,
                "label": info.label,
                "message": "SIGTERM으로 subprocess 종료 완료",
            }

        time.sleep(0.1)

    # 아직 살아 있으면 강제 종료
    try:
        pgid = os.getpgid(process.pid)

        print(f"[ProcessControl] SIGKILL process group: {pgid}")
        os.killpg(pgid, signal.SIGKILL)

    except ProcessLookupError:
        pass

    except Exception as e:
        print(f"[ProcessControl][WARN] SIGKILL 실패: {e}")

        try:
            process.kill()
        except Exception as kill_error:
            return {
                "terminated": False,
                "pid": info.pid,
                "label": info.label,
                "message": f"kill 실패: {kill_error}",
            }

    return {
        "terminated": True,
        "pid": info.pid,
        "label": info.label,
        "message": "SIGKILL로 subprocess 강제 종료 완료",
    }


# =========================
# 관리형 subprocess 실행
# =========================

def run_managed_process(
    command,
    label="managed-process",
    cwd=None,
    env=None,
    timeout=None,
    capture_output=True,
    text=True,
):
    """
    subprocess.run() 대신 사용할 관리형 실행 함수.

    특징:
    - subprocess.Popen 사용
    - start_new_session=True로 process group 분리
    - 현재 프로세스를 전역 등록
    - terminate_current_process()로 외부에서 종료 가능
    - 종료 후 subprocess.CompletedProcess와 유사한 객체 반환

    반환:
    subprocess.CompletedProcess
    """

    if not command:
        raise ValueError("command가 비어 있습니다.")

    if isinstance(command, str):
        raise TypeError(
            "run_managed_process()에는 문자열이 아니라 argv list를 전달해야 합니다."
        )

    stdout_pipe = subprocess.PIPE if capture_output else None
    stderr_pipe = subprocess.PIPE if capture_output else None

    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=stdout_pipe,
        stderr=stderr_pipe,
        text=text,
        start_new_session=True,
    )

    _register_process(
        process=process,
        label=label,
        command=command,
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout)

        return subprocess.CompletedProcess(
            args=command,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    except subprocess.TimeoutExpired:
        terminate_current_process(
            reason=f"{label} timeout",
        )

        stdout, stderr = process.communicate()

        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=timeout,
            output=stdout,
            stderr=stderr,
        )

    finally:
        _clear_process(process)


# =========================
# 단독 테스트
# =========================

if __name__ == "__main__":
    print("[ProcessControl] 단독 테스트 시작")

    result = run_managed_process(
        command=["/bin/bash", "-lc", "echo start; sleep 1; echo done"],
        label="process-control-test",
        timeout=5,
    )

    print("returncode:", result.returncode)
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    print("[ProcessControl] 단독 테스트 완료")