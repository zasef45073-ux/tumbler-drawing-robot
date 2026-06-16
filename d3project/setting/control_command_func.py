# =========================
# control command 처리
# Firebase commands/control 문서를 읽어 stop / pause / resume 액션을 수행한다.
# 전역 변수(_SHUTDOWN_EVENT 등)와 Firebase 접근 함수는 상위 모듈에서 주입된다.
# =========================
import time

from command_type_and_status_const import (
    COMMAND_DEFINITIONS,
    COMMAND_TYPE_DRAWING,
    CONTROL_ACTION_PAUSE,
    CONTROL_ACTION_RESUME,
    CONTROL_ACTION_STOP,
    CONTROL_STATUS_ACCEPTED,
    CONTROL_STATUS_DONE,
    CONTROL_STATUS_IGNORED,
    CONTROL_STATUS_REQUESTED,
    STATUS_IDLE,
    STATUS_PAUSE_REQUESTED,
    STATUS_PAUSED,
    STATUS_RESUME_REQUESTED,
    STATUS_STOP_REQUESTED,
    STATUS_STOPPED,
    TERMINAL_STATUSES,
)

from common_util_func import (
    get_command_definition,
    get_command_type,
    get_control_signature,
    normalize_command_type,
    normalize_control_action,
    now_text,
    now_timestamp,
)

from reset_firebase_func import (
    get_control_command,
    get_current_job_raw,
    update_command,
    update_control_command,
    update_current_job,
    update_request,
    update_robot_status,
)

from active_job import (
    _SHUTDOWN_EVENT,
    clear_remembered_control_action,
    get_active_command_snapshot,
    remember_control_action,
)

from doosan_exception_func import (
    call_robot_pause,
    call_robot_resume,
)

from listener_path_const import CONTROL_POLL_INTERVAL_SEC

from robot_activity.robot_process_control import (
    get_current_process_info,
    terminate_current_process,
)

def is_control_requested(control: object) -> bool:
    # 제어 명령이 처리 가능한 REQUESTED 상태인지 검증한다.
    # input:  {"status": "REQUESTED", "action": "stop", "jobId": "abc", ...}
    # output: True — 유효한 제어 요청 / False — dict 아님·status 불일치·action 누락·jobId 없음
    if not isinstance(control, dict):  # dict가 아니면 유효하지 않은 명령
        return False

    if control.get("status") != CONTROL_STATUS_REQUESTED:  # REQUESTED 상태가 아니면 이미 처리됐거나 무효
        return False

    action = normalize_control_action(control.get("action"))

    if not action:  # stop/pause/resume 이외의 action이면 무시
        return False

    if not control.get("jobId"):  # jobId 없으면 어떤 작업에 적용할지 알 수 없음
        return False

    return True


def get_active_control_for_job(job_id: str, allowed_actions: set[str] | None = None) -> dict | None:
    # Firebase에서 현재 제어 명령을 읽어 job_id와 action이 일치하는지 확인한다.
    # input:  job_id="abc", allowed_actions={"stop", "pause"}
    # output: 제어 명령 dict — 조건 불일치이면 None
    control = get_control_command()  # Firebase에서 현재 control 명령 조회

    if not is_control_requested(control):  # 유효한 REQUESTED 상태가 아니면 무시
        return None

    assert isinstance(control, dict)

    if str(control.get("jobId")) != str(job_id):  # 다른 작업의 control이면 무시
        return None

    action = normalize_control_action(control.get("action"))

    if allowed_actions and action not in allowed_actions:  # 허용된 action 목록 밖이면 무시
        return None

    return control


def accept_control(control: dict, message: str = "제어 요청 확인") -> None:
    # 제어 명령 상태를 ACCEPTED로 갱신한다(처리 시작을 Firebase에 알림).
    # input:  control={"jobId": "abc", ...}, message="작업 중지 요청 확인"
    # output: None — Firebase commands/control.status = "ACCEPTED"
    if not isinstance(control, dict):  # 잘못된 타입이면 Firebase 쓰기 없이 종료
        return

    update_control_command({
        "status": CONTROL_STATUS_ACCEPTED,
        "statusText": message,
        "acceptedAt": now_text(),  # 수락 시각 기록
    })


def complete_control(
    control: dict,
    final_status: str = CONTROL_STATUS_DONE,
    message: str = "제어 요청 처리 완료",
) -> None:
    # 제어 명령 처리가 끝났음을 Firebase에 기록한다.
    # input:  control={"jobId": "abc", ...}, final_status="DONE", message="작업 중지 처리 완료"
    # output: None — Firebase commands/control.status = final_status
    if not isinstance(control, dict):  # 잘못된 타입이면 Firebase 쓰기 없이 종료
        return

    # final_status는 성공 시 DONE, 실패 시 IGNORED로 호출됨
    update_control_command({
        "status": final_status,
        "statusText": message,
        "doneAt": now_text(),  # 처리 완료 시각 기록
    })


def ignore_control(control: dict, reason: str) -> None:
    # 처리할 수 없는 제어 명령을 IGNORED 상태로 기록한다.
    # input:  control={"jobId": "abc", ...}, reason="jobId가 없는 control 요청"
    # output: None — Firebase commands/control.status = "IGNORED"
    if not isinstance(control, dict):  # 잘못된 타입이면 Firebase 쓰기 없이 종료
        return
    # final_status는 성공 시 DONE, 실패 시 IGNORED로 호출됨
    update_control_command({
        "status": CONTROL_STATUS_IGNORED,
        "statusText": "제어 요청 무시",
        "ignoredAt": now_text(),   # 무시 처리 시각 기록
        "ignoreReason": reason,    # 무시 사유 — 디버깅·로그 추적용
    })


def build_command_from_current_job(current_job: dict | None, job_id: str) -> dict:
    # current_job 스냅샷으로 resume용 commands/start payload를 재구성한다.
    # input:  current_job={"commandType": "drawing", "customerName": "홍길동", ...}, job_id="abc"
    # output: commands/start에 set할 수 있는 command dict (resumedFromPaused=True 포함)
    current_job = current_job or {}

    # commandType → lastCommandType → pausedCommandType 순으로 폴백, 모두 없으면 drawing
    command_type = (
        current_job.get("commandType")
        or current_job.get("lastCommandType")
        or current_job.get("pausedCommandType")
        or COMMAND_TYPE_DRAWING
    )

    command_type = normalize_command_type(command_type) or COMMAND_TYPE_DRAWING
    command_definition = get_command_definition(command_type) or COMMAND_DEFINITIONS[COMMAND_TYPE_DRAWING]

    # resume 표시(resumedFromPaused=True)를 포함한 완성된 commands/start payload 반환
    return {
        "jobId": job_id,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
        "customerName": current_job.get("customerName", "-"),
        "imageUrl": current_job.get("imageUrl", ""),
        "convertedImageUrl": current_job.get("convertedImageUrl", ""),
        "option": current_job.get("option", "-"),
        "requestText": current_job.get("requestText", ""),
        "requestedBy": "listener_resume",
        "requestedAt": now_text(),
        "status": "REQUESTED",
        "statusText": f"{command_definition['label']} 다시 시작 요청",
        "runningStatus": command_definition["runningStatus"],
        "runningStatusText": command_definition["runningStatusText"],
        "doneStatus": command_definition["doneStatus"],
        "doneStatusText": command_definition["doneStatusText"],
        "nextReadyStatus": command_definition["nextReadyStatus"],
        "step": command_definition["step"],
        "startProgress": command_definition["startProgress"],
        "runningProgress": command_definition["runningProgress"],
        "doneProgress": command_definition["doneProgress"],
        "description": command_definition["description"],
        "resumedFromPaused": True,
    }


def set_robot_state(state: str, extra_data: dict | None = None) -> None:
    # robot_status 문서의 state 필드와 타임스탬프를 갱신한다.
    # input:  state="DRAWING", extra_data={"currentCommandType": "drawing", "currentJobId": "abc"}
    # output: None — Firebase robot_status 갱신
    update_data = {
        "state": state,
        "last_update_timestamp": now_timestamp(),  # 마지막 상태 변경 시각
    }

    if extra_data:
        update_data.update(extra_data)  # currentJobId·currentCommandType 등 상황별 추가 필드 병합

    update_robot_status(update_data)


def mark_control_requested(
    job_id: str,
    command: dict,
    control: dict,
    target_status: str,
) -> None:
    # stop / pause 요청을 Firebase current_job·requests·commands/start·robot_status에 기록한다.
    # input:  job_id="abc", command={...}, control={...}, target_status="STOP_REQUESTED"
    # output: None — 4개 Firebase 경로 일괄 갱신
    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)
    now = now_text()

    command_label = command_definition["label"] if command_definition else "-"
    reason = control.get("reason", "") if isinstance(control, dict) else ""

    # stop/pause에 따라 상태 텍스트와 타임스탬프 키 구분
    if target_status == STATUS_STOP_REQUESTED:
        status_text = "작업 중지 요청 확인"
        time_key = "stopRequestedAt"
    else:
        status_text = "일시정지 요청 확인"
        time_key = "pauseRequestedAt"

    # current_job / requests / commands/start / robot_status 4개 경로 동시 갱신
    update_current_job({
        "status": target_status,
        "statusText": status_text,
        "updatedAt": now,
        time_key: now,
        "controlReason": reason,
        "commandType": command_type or "",
        "commandLabel": command_label,
    })

    update_request(job_id, {
        "status": target_status,
        "statusText": status_text,
        "updatedAt": now,
        time_key: now,
        "controlReason": reason,
        "lastCommandType": command_type or "",
        "lastCommandLabel": command_label,
        "currentCommandType": "",
        "currentCommandLabel": "",
    })

    update_command({
        "status": target_status,
        "statusText": status_text,
        "updatedAt": now,
        time_key: now,
        "controlReason": reason,
    })

    set_robot_state(
        target_status,
        extra_data={
            "currentCommandType": command_type or "",
            "currentJobId": job_id,
        },
    )

    print("=" * 70)
    print("[Listener][Control] 제어 요청 확인")
    print(f"[Listener][Control] job_id       : {job_id}")
    print(f"[Listener][Control] commandType  : {command_type}")
    print(f"[Listener][Control] targetStatus : {target_status}")
    print(f"[Listener][Control] reason       : {reason}")
    print("=" * 70)


def mark_job_stopped(
    job_id: str,
    command: dict,
    control: dict | None = None,
    detail_message: str = "작업 중지됨",
) -> None:
    # 작업을 STOPPED 상태로 확정하고 Firebase 4개 경로에 기록한다.
    # input:  job_id="abc", command={...}, control={...}, detail_message="관리자 요청으로 중지"
    # output: None — Firebase 갱신 + complete_control + remember_control_action 호출
    # raises: ValueError — job_id가 빈 값인 경우
    if not job_id:  # job_id 없이는 어떤 요청을 종료할지 특정 불가
        raise ValueError("job_id가 없습니다.")

    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)
    now = now_text()

    command_label = command_definition["label"] if command_definition else "-"  # 정의 없으면 빈 레이블 대신 "-" 사용
    reason = control.get("reason", "") if isinstance(control, dict) else ""  # 중지 사유 (없으면 빈 문자열)

    # Firebase 갱신용 payload 구성 (current_job / requests / commands/start)
    current_job_update = {
        "status": STATUS_STOPPED,
        "statusText": "작업 중지됨",
        "updatedAt": now,
        "stoppedAt": now,
        "stopReason": reason,
        "stopDetail": detail_message,
        "commandType": command_type or "",
        "commandLabel": command_label,
        "nextReadyStatus": "",
    }

    request_update = {
        "status": STATUS_STOPPED,
        "statusText": "작업 중지됨",
        "updatedAt": now,
        "stoppedAt": now,
        "stopReason": reason,
        "stopDetail": detail_message,
        "lastCommandType": command_type or "",
        "lastCommandLabel": command_label,
        "currentCommandType": "",
        "currentCommandLabel": "",
        "nextReadyStatus": "",
    }

    command_update = {
        "status": "STOPPED",
        "statusText": "작업 중지됨",
        "updatedAt": now,
        "stoppedAt": now,
        "stopReason": reason,
        "stopDetail": detail_message,
        "commandType": command_type or "",
        "commandLabel": command_label,
    }

    # Firebase 3개 경로 갱신 후 robot_status도 STOPPED로 전환
    update_current_job(current_job_update)
    update_request(job_id, request_update)
    update_command(command_update)

    set_robot_state(
        STATUS_STOPPED,
        extra_data={
            "lastCommandType": command_type or "",
            "lastJobId": job_id,
            "currentCommandType": "",
            "currentJobId": "",
        },
    )

    complete_control(  # control 문서를 DONE으로 마감
        control or {},
        final_status=CONTROL_STATUS_DONE,
        message="작업 중지 처리 완료",
    )

    remember_control_action(job_id, CONTROL_ACTION_STOP, control or {})  # 이후 중복 처리 방지용 기록

    print("=" * 70)
    print("[Listener][Control] 작업 중지 처리 완료")
    print(f"[Listener][Control] job_id      : {job_id}")
    print(f"[Listener][Control] commandType : {command_type}")
    print(f"[Listener][Control] detail      : {detail_message}")
    print("=" * 70)


def mark_job_paused(
    job_id: str,
    command: dict,
    control: dict | None = None,
    detail_message: str = "일시정지됨",
) -> None:
    # 작업을 PAUSED 상태로 확정하고 Firebase 4개 경로에 기록한다.
    # input:  job_id="abc", command={...}, control={...}, detail_message="move_pause service 호출 완료"
    # output: None — Firebase 갱신 + complete_control 호출
    # raises: ValueError — job_id가 빈 값인 경우
    if not job_id:  # job_id 없이는 어떤 요청을 일시정지할지 특정 불가
        raise ValueError("job_id가 없습니다.")

    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)
    now = now_text()

    command_label = command_definition["label"] if command_definition else "-"  # 정의 없으면 빈 레이블 대신 "-" 사용
    reason = control.get("reason", "") if isinstance(control, dict) else ""  # 일시정지 사유 (없으면 빈 문자열)

    # pausedCommandType을 저장해 resume 시 어떤 공정을 재개할지 기억
    current_job_update = {
        "status": STATUS_PAUSED,
        "statusText": "일시정지됨",
        "updatedAt": now,
        "pausedAt": now,
        "pauseReason": reason,
        "pauseDetail": detail_message,
        "commandType": command_type or "",
        "commandLabel": command_label,
        "pausedCommandType": command_type or "",
        "pausedCommandLabel": command_label,
        "nextReadyStatus": "",
    }

    request_update = {
        "status": STATUS_PAUSED,
        "statusText": "일시정지됨",
        "updatedAt": now,
        "pausedAt": now,
        "pauseReason": reason,
        "pauseDetail": detail_message,
        "lastCommandType": command_type or "",
        "lastCommandLabel": command_label,
        "pausedCommandType": command_type or "",
        "pausedCommandLabel": command_label,
        "currentCommandType": "",
        "currentCommandLabel": "",
        "nextReadyStatus": "",
    }

    command_update = {
        "status": "PAUSED",
        "statusText": "일시정지됨",
        "updatedAt": now,
        "pausedAt": now,
        "pauseReason": reason,
        "pauseDetail": detail_message,
        "commandType": command_type or "",
        "commandLabel": command_label,
    }

    # Firebase 3개 경로 갱신 후 robot_status도 PAUSED로 전환
    update_current_job(current_job_update)
    update_request(job_id, request_update)
    update_command(command_update)

    set_robot_state(
        STATUS_PAUSED,
        extra_data={
            "lastCommandType": command_type or "",
            "lastJobId": job_id,
            "currentCommandType": "",
            "currentJobId": "",
        },
    )

    complete_control(
        control or {},
        final_status=CONTROL_STATUS_DONE,
        message="일시정지 처리 완료",
    )

    # remember_control_action(job_id, CONTROL_ACTION_PAUSE, control)

    print("=" * 70)
    print("[Listener][Control] 일시정지 처리 완료")
    print(f"[Listener][Control] job_id      : {job_id}")
    print(f"[Listener][Control] commandType : {command_type}")
    print(f"[Listener][Control] detail      : {detail_message}")
    print("=" * 70)


def resume_paused_job(control: dict) -> bool:
    # PAUSED 상태 작업에 move_resume service를 호출하고 실행 상태를 복원한다.
    # input:  control={"jobId": "abc", "action": "resume", "status": "REQUESTED", ...}
    # output: True — resume 성공 / False — jobId 없음·상태 불일치·service 호출 실패
    job_id = str(control.get("jobId", "")).strip()

    if not job_id:  # jobId 없으면 어떤 작업을 resume할지 알 수 없음
        ignore_control(control, "jobId가 없는 resume 요청")
        return False

    current_job = get_current_job_raw()  # Firebase에서 현재 작업 상태 조회
    current_job_id = str(current_job.get("jobId", current_job.get("id", ""))).strip()
    current_status = str(current_job.get("status", "")).strip()

    if current_job_id and current_job_id != job_id:  # 다른 작업의 resume 요청이면 무시
        ignore_control(
            control,
            f"현재 작업({current_job_id})과 resume 요청 작업({job_id})이 다릅니다.",
        )
        return False

    if current_status != STATUS_PAUSED:  # PAUSED 상태가 아니면 resume 불가
        ignore_control(
            control,
            f"현재 작업 상태가 PAUSED가 아닙니다: {current_status}",
        )
        return False

    # current_job 스냅샷으로 resume용 command payload 재구성
    command = build_command_from_current_job(current_job, job_id)
    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)

    if not command_definition:
        ignore_control(control, f"resume할 commandType을 확인할 수 없습니다: {command_type}")
        return False

    now = now_text()
    current_progress = current_job.get("progress", command_definition["runningProgress"])  # 일시정지 시점 진행률 유지

    accept_control(control, message="다시 시작 요청 확인")  # control 문서를 ACCEPTED로 갱신

    # Firebase에 RESUME_REQUESTED 상태 선기록 (service 호출 전 UI 반영용)
    update_current_job({
        "status": STATUS_RESUME_REQUESTED,
        "statusText": "다시 시작 요청 확인",
        "updatedAt": now,
        "resumeRequestedAt": now,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
    })

    update_request(job_id, {
        "status": STATUS_RESUME_REQUESTED,
        "statusText": "다시 시작 요청 확인",
        "updatedAt": now,
        "resumeRequestedAt": now,
        "currentCommandType": command_type,
        "currentCommandLabel": command_definition["label"],
    })

    try:
        service_result = call_robot_resume()  # Doosan ROS2 move_resume service 호출

    except Exception as e:
        # service 실패 시 PAUSED 상태로 롤백
        error_message = f"move_resume service 호출 실패: {e}"
        update_current_job({
            "status": STATUS_PAUSED,
            "statusText": "일시정지됨",
            "updatedAt": now_text(),
            "resumeError": error_message,
        })
        update_request(job_id, {
            "status": STATUS_PAUSED,
            "statusText": "일시정지됨",
            "updatedAt": now_text(),
            "resumeError": error_message,
        })
        complete_control(
            control,
            final_status=CONTROL_STATUS_IGNORED,
            message=error_message,
        )
        print(f"[Listener][Control][Resume Error] {error_message}")
        return False

    # service 성공 — 실행 중 상태로 복원
    running_status = command_definition["runningStatus"]       # ex) "DRAWING"
    running_status_text = command_definition["runningStatusText"]
    resumed_at = now_text()

    # current_job·requests·commands/start 3개 경로를 실행 중 상태로 갱신
    update_current_job({
        "status": running_status,
        "statusText": running_status_text,
        "step": command_definition["step"],
        "progress": current_progress,      # 일시정지 시점 진행률 그대로 유지
        "updatedAt": resumed_at,
        "resumedAt": resumed_at,
        "resumeDetail": "move_resume service 호출로 기존 subprocess 계속 진행",
        "commandType": command_type,
        "commandLabel": command_definition["label"],
        "processDescription": command_definition["description"],
        "nextReadyStatus": command_definition["nextReadyStatus"],
    })

    update_request(job_id, {
        "status": running_status,
        "statusText": running_status_text,
        "step": command_definition["step"],
        "progress": current_progress,
        "updatedAt": resumed_at,
        "resumedAt": resumed_at,
        "resumeDetail": "move_resume service 호출로 기존 subprocess 계속 진행",
        "currentCommandType": command_type,
        "currentCommandLabel": command_definition["label"],
        "nextReadyStatus": command_definition["nextReadyStatus"],
    })

    update_command({
        "status": "ACCEPTED",  # resume된 command는 ACCEPTED로 표시
        "statusText": "작업 재개됨",
        "updatedAt": resumed_at,
        "resumedAt": resumed_at,
        "resumeDetail": "move_resume service 호출로 기존 subprocess 계속 진행",
        "commandType": command_type,
        "commandLabel": command_definition["label"],
    })

    set_robot_state(  # robot_status를 실행 중 상태로 전환
        running_status,
        extra_data={
            "currentCommandType": command_type,
            "currentJobId": job_id,
            "lastMotionControlAction": CONTROL_ACTION_RESUME,
            "lastMotionControlService": service_result.get("serviceName", ""),
        },
    )

    complete_control(  # control 문서를 DONE으로 마감
        control,
        final_status=CONTROL_STATUS_DONE,
        message="move_resume service 처리 완료",
    )

    clear_remembered_control_action(job_id)  # stop 기록 초기화 — 새 작업 진행 허용

    print("=" * 70)
    print("[Listener][Control] move_resume 처리 완료")
    print(f"[Listener][Control] job_id      : {job_id}")
    print(f"[Listener][Control] commandType : {command_type}")
    print("[Listener][Control] 기존 subprocess를 다시 시작하지 않고 계속 진행합니다.")
    print("=" * 70)

    return True


def handle_stop_or_pause_control(control: dict) -> bool:
    # stop / pause 제어 명령을 처리한다.
    # input:  control={"jobId": "abc", "action": "stop"/"pause", "status": "REQUESTED", ...}
    # output: True — 처리 완료 / False — jobId 없음·대상 job 불일치·종료 상태·지원 안 하는 action
    action = normalize_control_action(control.get("action"))
    job_id = str(control.get("jobId", "")).strip()

    # 현재 메모리 상 실행 중인 작업 스냅샷 조회
    active = get_active_command_snapshot()
    active_job_id = active.get("jobId")
    active_command = active.get("command") or {}

    # Firebase에서 현재 작업 상태 조회 (active가 없을 때 폴백용)
    current_job = get_current_job_raw()
    current_job_id = str(current_job.get("jobId", current_job.get("id", ""))).strip()
    current_status = str(current_job.get("status", "")).strip()

    if not job_id:  # jobId 없으면 어떤 작업에 적용할지 알 수 없음
        ignore_control(control, "jobId가 없는 control 요청")
        return False

    if active_job_id:
        # 메모리에 실행 중인 작업이 있으면 우선 사용
        if str(active_job_id) != str(job_id):
            ignore_control(
                control,
                f"현재 실행 작업({active_job_id})과 control 요청 작업({job_id})이 다릅니다.",
            )
            return False

        command = active_command

    else:
        # 메모리에 없으면 Firebase current_job으로 폴백
        if current_job_id and current_job_id != job_id:
            ignore_control(
                control,
                f"현재 작업({current_job_id})과 control 요청 작업({job_id})이 다릅니다.",
            )
            return False

        if current_status in TERMINAL_STATUSES:  # 이미 종료된 작업이면 무시
            ignore_control(
                control,
                f"현재 작업이 이미 종료 상태입니다: {current_status}",
            )
            return False

        command = build_command_from_current_job(current_job, job_id)

    if action == CONTROL_ACTION_STOP:
        accept_control(control, message="작업 중지 요청 확인")
        mark_control_requested(job_id, command, control, STATUS_STOP_REQUESTED)

        final_detail = "관리자 작업 중지 요청으로 현재 subprocess 종료"
        process_info = get_current_process_info()  # 실행 중인 subprocess 확인

        if process_info and process_info.get("running"):
            terminate_result = terminate_current_process(  # subprocess 강제 종료
                reason=f"작업 중지 요청 확인: {job_id}",
                terminate_timeout_sec=3.0,
            )
            final_detail = f"{final_detail} / {terminate_result.get('message', '')}"
        else:
            final_detail = f"{final_detail} / 실행 중인 subprocess 없음"  # 이미 종료됐거나 아직 시작 전

        mark_job_stopped(
            job_id=job_id,
            command=command,
            control=control,
            detail_message=final_detail,
        )
        return True

    if action == CONTROL_ACTION_PAUSE:
        accept_control(control, message="일시정지 요청 확인")
        mark_control_requested(job_id, command, control, STATUS_PAUSE_REQUESTED)

        try:
            service_result = call_robot_pause()  # Doosan ROS2 move_pause service 호출 (subprocess는 유지)
            final_detail = (
                "move_pause service 호출 완료 / "
                "현재 subprocess는 종료하지 않고 유지"
            )
            if service_result.get("serviceName"):
                final_detail += f" / service={service_result['serviceName']}"  # 호출된 서비스명 로그에 포함

        except Exception as e:
            # pause service 실패 시 이전 상태로 롤백
            error_message = f"move_pause service 호출 실패: {e}"
            complete_control(
                control,
                final_status=CONTROL_STATUS_IGNORED,
                message=error_message,
            )
            update_current_job({
                "status": current_status or STATUS_IDLE,
                "statusText": current_job.get("statusText", "작업 상태 확인"),
                "updatedAt": now_text(),
                "pauseError": error_message,
            })
            update_request(job_id, {
                "updatedAt": now_text(),
                "pauseError": error_message,
            })
            print(f"[Listener][Control][Pause Error] {error_message}")
            return False

        mark_job_paused(
            job_id=job_id,
            command=command,
            control=control,
            detail_message=final_detail,
        )
        return True

    ignore_control(control, f"지원하지 않는 stop/pause action입니다: {action}")
    return False


def handle_control_command(control: dict) -> bool:
    # Firebase control 명령을 읽어 action에 맞는 핸들러로 라우팅한다.
    # input:  control={"action": "stop"/"pause"/"resume", "jobId": "abc", "status": "REQUESTED", ...}
    # output: True — 처리 완료 / False — 유효하지 않은 명령·지원 안 하는 action
    if not is_control_requested(control):  # 유효하지 않은 명령이면 즉시 반환
        return False

    action = normalize_control_action(control.get("action"))

    if action in {CONTROL_ACTION_STOP, CONTROL_ACTION_PAUSE}:  # stop/pause는 동일 핸들러로 처리
        return handle_stop_or_pause_control(control)

    if action == CONTROL_ACTION_RESUME:  # resume은 별도 핸들러로 처리
        return resume_paused_job(control)

    ignore_control(control, f"지원하지 않는 action입니다: {action}")
    return False


def control_watcher_loop() -> None:
    # CONTROL_POLL_INTERVAL_SEC 간격으로 Firebase control 명령을 폴링하는 무한 루프.
    # _SHUTDOWN_EVENT가 set되면 루프를 종료한다(데몬 스레드로 실행).
    # input:  없음 (전역 _SHUTDOWN_EVENT, CONTROL_POLL_INTERVAL_SEC 참조)
    # output: None
    print("[Listener][ControlWatcher] 시작")

    last_seen_signature = ""  # 동일 control 명령 중복 처리 방지용 서명 캐시

    while not _SHUTDOWN_EVENT.is_set():  # 종료 이벤트가 set되면 루프 탈출
        try:
            control = get_control_command()  # Firebase에서 control 명령 폴링

            if is_control_requested(control):
                assert isinstance(control, dict)
                signature = get_control_signature(control)  # jobId|action|requestedAt 조합 서명

                if signature != last_seen_signature:  # 새로운 명령일 때만 처리
                    print("=" * 70)
                    print("[Listener][ControlWatcher] control 요청 감지")
                    print(f"[Listener][ControlWatcher] signature: {signature}")
                    print(f"[Listener][ControlWatcher] action   : {control.get('action')}")
                    print(f"[Listener][ControlWatcher] jobId    : {control.get('jobId')}")
                    print("=" * 70)

                    handled = handle_control_command(control)

                    if handled:
                        last_seen_signature = signature  # 처리 완료된 서명 저장 — 재처리 방지

            time.sleep(CONTROL_POLL_INTERVAL_SEC)

        except Exception as e:
            print(f"[Listener][ControlWatcher][Error] {e}")
            time.sleep(CONTROL_POLL_INTERVAL_SEC)

    print("[Listener][ControlWatcher] 종료")
