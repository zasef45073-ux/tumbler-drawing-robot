import threading
from common_util_func import (
    get_command_type,
    get_control_signature,
    now_text,
)

# =========================
# 전역 제어 상태
# =========================
_ACTIVE_LOCK = threading.RLock()
_ACTIVE_COMMAND = None
_ACTIVE_MODE = ""
_ACTIVE_JOB_ID = ""
_ACTIVE_COMMAND_TYPE = ""
_LAST_CONTROL_ACTION_BY_JOB = {}
_SHUTDOWN_EVENT = threading.Event()

# =========================
# Active job 관리
# 현재 실행 중인 작업(command)과 마지막 제어 액션(stop/pause)을 스레드 안전하게 보관한다.
# 전역 변수(_ACTIVE_COMMAND, _ACTIVE_LOCK 등)는 상위 모듈에서 선언되어 있다.
# =========================
def set_active_command(command: dict | None, mode: str) -> None:
    # 현재 실행 중인 명령을 전역 변수에 등록한다.
    # input:  command={"jobId": "abc", "commandType": "drawing", ...}, mode="real"
    # output: None — _ACTIVE_COMMAND / _ACTIVE_MODE / _ACTIVE_JOB_ID / _ACTIVE_COMMAND_TYPE 갱신
    global _ACTIVE_COMMAND
    global _ACTIVE_MODE
    global _ACTIVE_JOB_ID
    global _ACTIVE_COMMAND_TYPE

    with _ACTIVE_LOCK:
        _ACTIVE_COMMAND = dict(command or {})
        _ACTIVE_MODE = mode
        _ACTIVE_JOB_ID = str((command or {}).get("jobId", "")).strip()
        _ACTIVE_COMMAND_TYPE = get_command_type(command) or ""

    print("=" * 70)
    print("[Listener][Active] 현재 실행 작업 등록")
    print(f"[Listener][Active] job_id      : {_ACTIVE_JOB_ID}")
    print(f"[Listener][Active] commandType : {_ACTIVE_COMMAND_TYPE}")
    print("=" * 70)


def clear_active_command() -> None:
    # 현재 실행 중인 명령을 전역 변수에서 초기화한다.
    # input:  없음
    # output: None — 모든 _ACTIVE_* 전역 변수를 초기값으로 되돌림
    global _ACTIVE_COMMAND
    global _ACTIVE_MODE
    global _ACTIVE_JOB_ID
    global _ACTIVE_COMMAND_TYPE

    with _ACTIVE_LOCK:
        _ACTIVE_COMMAND = None
        _ACTIVE_MODE = ""
        _ACTIVE_JOB_ID = ""
        _ACTIVE_COMMAND_TYPE = ""

    print("[Listener][Active] 현재 실행 작업 해제")


def get_active_command_snapshot() -> dict:
    # 현재 실행 중인 명령 정보를 복사본으로 반환한다(스레드 안전).
    # input:  없음
    # output: {"command": dict, "mode": str, "jobId": str, "commandType": str}
    #         실행 중인 작업이 없으면 command={}、jobId=""
    with _ACTIVE_LOCK:
        return {
            "command": dict(_ACTIVE_COMMAND or {}),
            "mode": _ACTIVE_MODE,
            "jobId": _ACTIVE_JOB_ID,
            "commandType": _ACTIVE_COMMAND_TYPE,
        }


def remember_control_action(job_id: str, action: str, control: dict) -> None:
    # 처리 완료된 제어 액션(stop/pause)을 job_id 키로 메모리에 기록한다.
    # 이후 mark_job_error / mark_process_completed에서 중복 처리를 방지하기 위해 참조한다.
    # input:  job_id="abc", action="stop",
    #         control={"jobId": "abc", "action": "stop", "requestedAt": "...", ...}
    # output: None — _LAST_CONTROL_ACTION_BY_JOB[job_id] 갱신
    signature = get_control_signature(control)

    with _ACTIVE_LOCK:
        _LAST_CONTROL_ACTION_BY_JOB[str(job_id)] = {
            "action": action,
            "signature": signature,
            "control": dict(control or {}),
            "handledAt": now_text(),
        }


def get_remembered_control_action(job_id: str) -> dict:
    # 기록된 마지막 제어 액션을 복사본으로 반환한다.
    # input:  job_id="abc"
    # output: {"action": "stop", "signature": "...", "control": {...}, "handledAt": "..."}
    #         기록이 없으면 {}
    with _ACTIVE_LOCK:
        return dict(_LAST_CONTROL_ACTION_BY_JOB.get(str(job_id), {}))


def clear_remembered_control_action(job_id: str) -> None:
    # 기록된 제어 액션을 삭제한다. 새 작업 시작 직전에 호출한다.
    # input:  job_id="abc"
    # output: None — _LAST_CONTROL_ACTION_BY_JOB에서 해당 job_id 항목 제거
    with _ACTIVE_LOCK:
        _LAST_CONTROL_ACTION_BY_JOB.pop(str(job_id), None)
