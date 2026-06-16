import os

from command_type_and_status_const import (
    AUTO_RUN_SEQUENCE_FULL,
    COMMAND_TYPE_DRAWING,
    COMMAND_TYPE_GLUE,
    CONTROL_ACTION_STOP,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_IDLE,
)

from common_util_func import (
    get_command_definition,
    get_command_type,
    map_drawing_runner_progress,
    normalize_command_type,
    now_text,
)

from reset_firebase_func import (
    get_current_job_raw,
    set_start_command,
    update_command,
    update_current_job,
    update_request,
)

from active_job import get_remembered_control_action
from control_command_func import set_robot_state

# =========================
# Firebase 상태 업데이트 함수
# 명령 접수·진행률·완료·에러 등 공정 흐름에 따른 Firebase 갱신 로직을 담당한다.
# 자동 실행(autoRunAll) 다음 공정 생성 로직도 여기서 처리한다.
# =========================
def accept_command(command: dict, mode: str) -> None:
    # 명령을 접수하고 Firebase 4개 경로(command / current_job / request / robot_status)에 실행 중 상태를 기록한다.
    # input:  command={"jobId": "abc", "commandType": "drawing", ...}, mode="real"
    # output: None — Firebase 갱신
    # raises: ValueError — jobId 없음 또는 지원하지 않는 commandType
    # 유효성 검사
    job_id = command.get("jobId")
    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)

    if not job_id:
        raise ValueError("commands/start에 jobId가 없습니다.")

    if not command_definition:
        raise ValueError(
            f"지원하지 않는 commandType입니다: {command.get('commandType')}"
        )

    now = now_text()

    running_status = command_definition["runningStatus"]
    running_status_text = command_definition["runningStatusText"]

    # Firebase 4개 경로 갱신
    command_update = {
        "status": "ACCEPTED",
        "statusText": "작업 명령 확인",
        "acceptedAt": now,
        "listenerMode": mode,
        "adapterMode": os.getenv("COBOT1_ADAPTER_MODE", "-"),
        "commandType": command_type,
        "commandLabel": command_definition["label"],
    }

    current_job_update = {
        "status": running_status,
        "statusText": running_status_text,
        "step": command_definition["step"],
        "progress": command_definition["startProgress"],
        "startTime": command.get("requestedAt", now),
        "updatedAt": now,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
    }

    request_update = {
        "status": running_status,
        "statusText": running_status_text,
        "progress": command_definition["startProgress"],
        "startedAt": now,
        "updatedAt": now,
        "currentCommandType": command_type,
        "currentCommandLabel": command_definition["label"],
    }

    # drawing 시작 시 이전 작업의 preview/actual canvas 경로가 남아 있으면
    # 대시보드가 오래된 추정 경로를 계속 그릴 수 있다.
    # 따라서 새 drawing 명령을 받을 때 canvas 관련 필드를 반드시 초기화한다.
    if command_type == COMMAND_TYPE_DRAWING:
        clear_drawing_fields = {
            "drawingPathJsonPath": "",
            "drawingPathJsonUrl": "",
            "drawingPhase": "waiting_actual_path",
            "drawingProgressPercent": 0,
            "drawingPointIndex": 0,
            "drawingTotalPoints": 0,
        }
        current_job_update.update(clear_drawing_fields)
        request_update.update(clear_drawing_fields)

    update_command(command_update)
    update_current_job(current_job_update)
    update_request(job_id, request_update)

    set_robot_state(
        running_status,
        extra_data={
            "currentCommandType": command_type,
            "currentJobId": job_id,
        },
    )

    print("=" * 70)
    print("[Listener] 작업 명령 접수 완료")
    print(f"[Listener] job_id      : {job_id}")
    print(f"[Listener] commandType : {command_type}")
    print(f"[Listener] status      : {running_status}")
    print(f"[Listener] mode        : {mode}")
    print("=" * 70)


def update_progress_from_runner(
    job_id: str,
    status: str,
    status_text: str,
    step: str,
    progress: int | float,
    extra_data: dict | None = None,
) -> None:
    # 러너(robot_job_runner / robot_process_adapter)가 콜백으로 전달한 진행률을 Firebase에 반영한다.
    # drawing 공정은 러너 0~100%를 COMMAND_DEFINITIONS 구간으로 선형 매핑한다.
    # stop control이 처리된 작업이면 갱신을 건너뛴다.
    # input:  job_id="abc", status="DRAWING", status_text="드로잉 중", step="2 / 5",
    #         progress=50, extra_data={"commandType": "drawing", "drawingProgress": 50, ...}
    # output: None — Firebase current_job / requests / robot_status 갱신
    now = now_text()
    extra_data = extra_data or {}

    # stop control 처리된 작업은 진행률 갱신 불필요
    remembered = get_remembered_control_action(job_id)

    if remembered.get("action") == CONTROL_ACTION_STOP:
        print(
            f"[Listener][Progress][Skip] control 처리된 작업 진행률 무시: "
            f"job_id={job_id}, action={remembered.get('action')}"
        )
        return

    # extra_data에서 commandType 결정 (없으면 drawing 기본값)
    command_type = (
        extra_data.get("commandType")
        or extra_data.get("command_type")
        or COMMAND_TYPE_DRAWING
    )
    command_type = normalize_command_type(command_type) or COMMAND_TYPE_DRAWING

    command_definition = get_command_definition(command_type)

    display_step = step
    display_progress = progress

    # drawing 공정은 러너 진행률을 COMMAND_DEFINITIONS 구간으로 매핑
    if command_type == COMMAND_TYPE_DRAWING and command_definition:
        display_step = command_definition["step"]
        display_progress = map_drawing_runner_progress(progress)

    current_job_update = {
        "status": status,
        "statusText": status_text,
        "step": display_step,
        "progress": display_progress,
        "updatedAt": now,
    }

    request_update = {
        "status": status,
        "statusText": status_text,
        "progress": display_progress,
        "updatedAt": now,
    }

    if command_definition:
        current_job_update["commandType"] = command_type
        current_job_update["commandLabel"] = command_definition["label"]

        request_update["currentCommandType"] = command_type
        request_update["currentCommandLabel"] = command_definition["label"]

        extra_data_copy_keys = [
            # 이미지 URL (웹 표시용)
            "imageUrl",
            "convertedImageUrl",
            # 드로잉 canvas 진행률 (대시보드 실시간 반영)
            "drawingPathJsonUrl",
            "drawingPhase",
            "drawingProgressPercent",
            "drawingPointIndex",
            "drawingTotalPoints",
        ]

        for key in extra_data_copy_keys:
            if key not in extra_data:
                continue

            value = extra_data.get(key)

            if value is None:
                continue

            # 빈 문자열은 저장하지 않음.
            # 단, 0 / 0.0은 진행률에서 의미가 있으므로 저장해야 한다.
            if isinstance(value, str) and not value.strip():
                continue

            current_job_update[key] = value
            request_update[key] = value

    update_current_job(current_job_update)
    update_request(job_id, request_update)

    set_robot_state(
        status,
        extra_data={
            "currentCommandType": command_type,
            "currentJobId": job_id,
        },
    )

    print(
        f"[Listener][Progress] {job_id} | "
        f"{status_text} | {display_step} | {display_progress}% "
        f"(runner={step}, {progress}%)"
    )


def collect_result_image_data(result: dict) -> dict:
    # 러너 결과에서 이미지 URL 필드만 추출한다. 로컬 경로는 Firebase에 저장하지 않음.
    result = result or {}

    return {
        "normalizedImageUrl": result.get("normalizedImageUrl", ""),
        "convertedImageUrl": result.get("convertedImageUrl", ""),
    }


def collect_process_adapter_data(result: dict) -> dict:
    # 러너 결과에서 subprocess 실행 관련 필드만 추출한다.
    # input:  result={"runnerCommand": "python3 ...", "returnCode": 0, "stdout": "...", ...}
    # output: {"runnerCommand": str, "returnCode": int | None, "stdout": str, "stderr": str}
    result = result or {}

    return {
        "runnerCommand": result.get("runnerCommand", ""),
        "returnCode": result.get("returnCode", None),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


def apply_image_data_to_updates(
    image_data: dict,
    current_job_update: dict,
    request_update: dict,
    command_update: dict,
) -> None:
    # 이미지 데이터를 Firebase 갱신 payload 3개에 각각 주입한다.
    # input:  image_data={"normalizedImageUrl": "...", ...}, current_job_update={...}, ...
    # output: None — current_job_update / request_update / command_update 인플레이스 수정
    normalized_image_url = image_data.get("normalizedImageUrl", "")
    converted_image_url = image_data.get("convertedImageUrl", "")

    # 원본 이미지 URL
    if normalized_image_url:
        current_job_update["imageUrl"] = normalized_image_url
        request_update["imageUrl"] = normalized_image_url
        command_update["imageUrl"] = normalized_image_url

    # 변환 이미지 URL
    if converted_image_url:
        current_job_update["convertedImageUrl"] = converted_image_url
        request_update["convertedImageUrl"] = converted_image_url
        command_update["convertedImageUrl"] = converted_image_url


def apply_process_data_to_updates(
    process_data: dict,
    current_job_update: dict,
    request_update: dict,
    command_update: dict,
) -> None:
    # subprocess 실행 데이터는 command_update에만 기록
    # current_job / request에는 저장하지 않음
    stdout = process_data.get("stdout", "")
    stderr = process_data.get("stderr", "")

    # stdout/stderr는 command_update에만 저장하고 마지막 2000자로 잘라 크기 제한
    if stdout:
        command_update["stdoutPreview"] = stdout[-2000:]

    if stderr:
        command_update["stderrPreview"] = stderr[-2000:]


def to_bool(value: object) -> bool:
    # Firebase 값이 bool / string / int 어느 형태로 들어와도 bool로 정규화한다.
    # input:  True / 1 / "true" / "yes" / "1" / "on" → True
    #         False / 0 / "false" / "" / None → False
    # output: bool
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    clean_value = str(value or "").strip().lower()

    return clean_value in {"1", "true", "yes", "y", "on"}


def is_auto_run_enabled(command: object) -> bool:
    # 현재 명령이 전체 자동 실행 명령인지 확인한다.
    # input:  {"autoRunAll": True, ...} / {"autoRunAll": "true"} / {} / None
    # output: True — autoRunAll이 truthy / False — 그 외
    if not isinstance(command, dict):
        return False

    return to_bool(command.get("autoRunAll"))


def normalize_auto_run_sequence(command: object) -> list[str]:
    # command에 저장된 autoRunSequence를 정규화한다.
    # Firebase list가 {"0": "...", "1": "..."} dict로 들어오는 경우도 처리한다.
    # skipGlue=True면 sequence에서 glue를 제거한다.
    # input:  {"autoRunSequence": ["tumbler_place", "drawing", ...], "skipGlue": True}
    # output: ["tumbler_place", "drawing", "paper_attach", "rolling_return"]
    #         (기본값: AUTO_RUN_SEQUENCE_SKIP_GLUE)
    if not isinstance(command, dict):
        return list(AUTO_RUN_SEQUENCE_FULL)

    raw_sequence = command.get("autoRunSequence")

    if isinstance(raw_sequence, list):
        sequence = raw_sequence
    elif isinstance(raw_sequence, tuple):
        sequence = list(raw_sequence)
    elif isinstance(raw_sequence, dict):
        # Firebase list가 간혹 {"0": "...", "1": "..."} 형태로 들어올 수 있어 보정한다.
        try:
            sequence = [raw_sequence[key] for key in sorted(raw_sequence.keys(), key=lambda x: int(x))]
        except Exception:
            sequence = list(raw_sequence.values())
    else:
        sequence = list(AUTO_RUN_SEQUENCE_FULL)

    clean_sequence: list[str] = []

    for item in sequence:
        clean_item = normalize_command_type(item)

        if clean_item and clean_item not in clean_sequence:
            clean_sequence.append(clean_item)

    if not clean_sequence:
        clean_sequence = list(AUTO_RUN_SEQUENCE_FULL)

    return clean_sequence


def get_auto_run_current_index(command: dict, command_type: str | None, sequence: list[str]) -> int:
    # 현재 자동 실행 sequence에서 command_type의 인덱스를 계산한다.
    # autoRunIndex 힌트가 있으면 우선 사용하고, 없으면 sequence.index()로 탐색한다.
    # input:  command={"autoRunIndex": 1, ...}, command_type="drawing",
    #         sequence=["tumbler_place", "drawing", "paper_attach", "rolling_return"]
    # output: 1 (sequence 내 인덱스) / -1 (찾지 못한 경우)
    try:
        raw_index = command.get("autoRunIndex")
        index = int(raw_index)  # type: ignore[arg-type]
        if 0 <= index < len(sequence) and sequence[index] == command_type:
            return index
    except Exception:
        pass

    if command_type in sequence:
        return sequence.index(command_type)

    return -1


def make_auto_run_next_command(
    job_id: str,
    current_command: dict | None,
    current_job: dict | None,
    next_command_type: str,
    next_index: int,
    sequence: list[str],
    mode: str,
) -> dict:
    # 전체 자동 실행의 다음 공정 commands/start payload를 만든다.
    # current_job → current_command 순으로 값을 우선 조회해 고객 정보를 유지한다.
    # input:  job_id="abc", current_command={...}, current_job={...},
    #         next_command_type="paper_attach", next_index=2,
    #         sequence=["tumbler_place", "drawing", "paper_attach", "rolling_return"], mode="real"
    # output: commands/start에 set할 수 있는 완성된 command dict
    # raises: ValueError — next_command_type에 대한 COMMAND_DEFINITIONS 없음
    current_command = current_command or {}
    current_job = current_job or {}

    command_definition = get_command_definition(next_command_type)

    if not command_definition:
        raise ValueError(f"자동 실행 next commandType 정의를 찾을 수 없습니다: {next_command_type}")

    now = now_text()

    def pick_value(key: str, default: object = "") -> object:
        # current_job → current_command 순으로 값을 조회하고, 둘 다 없으면 default를 반환한다.
        value = current_job.get(key)

        if value not in [None, ""]:
            return value

        value = current_command.get(key)

        if value not in [None, ""]:
            return value

        return default

    return {
        # 로봇 PC가 실제로 읽는 핵심 필드
        "jobId": job_id,
        "commandType": next_command_type,
        "status": "REQUESTED",
        # 전체 자동 실행 플래그
        "autoRunAll": True,
        "autoRunSequence": sequence,
        "autoRunIndex": next_index,
        # 웹 표시용 필드
        "commandLabel": command_definition["label"],
        "customerName": pick_value("customerName", "-"),
        "imageUrl": pick_value("imageUrl", ""),
        "convertedImageUrl": pick_value("convertedImageUrl", ""),
        "requestedBy": "listener_auto_run",
        "requestedAt": now,
        "statusText": f"자동 실행 - {command_definition['label']} 요청",
    }


def schedule_auto_run_next_command(job_id: str, command: dict, mode: str = "real") -> bool:
    # 전체 자동 실행 명령이 완료되었을 때 다음 공정을 commands/start에 생성한다.
    # sequence 끝에 도달하면 autoRunFinished=True를 기록하고 False를 반환한다.
    # input:  job_id="abc", command={"autoRunAll": True, "commandType": "drawing", ...}, mode="real"
    # output: True — 다음 공정 생성 성공 / False — 자동 실행 아님·sequence 종료·현재 공정 미발견
    #
    # 예:
    # tumbler_place 완료 → drawing 자동 요청
    # drawing 완료       → paper_attach 자동 요청
    # paper_attach 완료  → rolling_return 자동 요청
    # rolling_return 완료 → 자동 실행 종료
    # 자동 실행 플래그 없으면 즉시 종료
    if not is_auto_run_enabled(command):
        return False

    # 현재 공정의 sequence 내 위치 파악
    command_type = get_command_type(command)
    sequence = normalize_auto_run_sequence(command)
    current_index = get_auto_run_current_index(command, command_type, sequence)

    if current_index < 0:
        print(
            f"[Listener][AutoRun][Skip] 현재 commandType이 자동 실행 sequence에 없습니다: "
            f"commandType={command_type}, sequence={sequence}"
        )
        return False

    next_index = current_index + 1

    # sequence 끝이면 자동 실행 종료 표시 후 반환
    if next_index >= len(sequence):
        now = now_text()
        update_current_job({
            "autoRunAll": True,
            "autoRunFinished": True,
            "autoRunFinishedAt": now,
            "autoRunUpdatedAt": now,
        })
        update_request(job_id, {
            "autoRunAll": True,
            "autoRunFinished": True,
            "autoRunFinishedAt": now,
            "autoRunUpdatedAt": now,
        })

        print("=" * 70)
        print("[Listener][AutoRun] 전체 자동 실행 완료")
        print(f"[Listener][AutoRun] job_id   : {job_id}")
        print(f"[Listener][AutoRun] sequence : {sequence}")
        print("=" * 70)
        return False

    # 다음 공정 payload 생성 후 commands/start에 기록
    next_command_type = sequence[next_index]
    current_job = get_current_job_raw()
    next_command = make_auto_run_next_command(
        job_id=job_id,
        current_command=command,
        current_job=current_job,
        next_command_type=next_command_type,
        next_index=next_index,
        sequence=sequence,
        mode=mode,
    )

    set_start_command(next_command)

    now = now_text()
    update_current_job({
        "autoRunAll": True,
        "autoRunSequence": sequence,
        "autoRunIndex": next_index,
    })
    update_request(job_id, {
        "autoRunAll": True,
        "autoRunSequence": sequence,
        "autoRunIndex": next_index,
    })

    print("=" * 70)
    print("[Listener][AutoRun] 다음 공정 자동 요청 생성")
    print(f"[Listener][AutoRun] job_id      : {job_id}")
    print(f"[Listener][AutoRun] current     : {command_type}")
    print(f"[Listener][AutoRun] next        : {next_command_type}")
    print(f"[Listener][AutoRun] index       : {next_index + 1} / {len(sequence)}")
    print(f"[Listener][AutoRun] skipGlue    : True")
    print("=" * 70)

    return True


def mark_process_completed(
    job_id: str,
    command: dict,
    result: dict | None = None,
    mode: str = "real",
) -> None:
    # 공정 완료를 Firebase 4개 경로에 기록하고 자동 실행 다음 공정을 생성한다.
    # stop control이 처리된 작업이면 완료 처리를 건너뛴다.
    # input:  job_id="abc", command={...}, result={"success": True, "normalizedImageUrl": "..."}, mode="real"
    # output: None — Firebase 갱신 + schedule_auto_run_next_command 호출
    # raises: ValueError — job_id 없음 또는 지원하지 않는 commandType
    # stop control이 처리된 작업은 완료 기록 생략
    remembered = get_remembered_control_action(job_id)

    if remembered.get("action") == CONTROL_ACTION_STOP:
        print(
            f"[Listener][Complete][Skip] control 처리된 작업 완료처리 무시: "
            f"job_id={job_id}, action={remembered.get('action')}"
        )
        return

    # 유효성 검사
    if not job_id:
        raise ValueError("job_id가 없습니다.")

    command_type = get_command_type(command)
    command_definition = get_command_definition(command_type)

    if not command_definition:
        raise ValueError(f"지원하지 않는 commandType입니다: {command_type}")

    now = now_text()

    done_status = command_definition["doneStatus"]
    done_status_text = command_definition["doneStatusText"]
    done_progress = command_definition["doneProgress"]

    # STATUS_COMPLETED면 전체 공정 최종 완료 → completedAt 기록
    is_final_completed = done_status == STATUS_COMPLETED

    # 완료 payload 구성
    current_job_update = {
        "status": done_status,
        "statusText": done_status_text,
        "step": command_definition["step"],
        "progress": done_progress,
        "updatedAt": now,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
    }

    request_update = {
        "status": done_status,
        "statusText": done_status_text,
        "progress": done_progress,
        "updatedAt": now,
        "lastCommandType": command_type,
        "lastCommandLabel": command_definition["label"],
        "currentCommandType": "",
        "currentCommandLabel": "",
    }

    command_update = {
        "status": "DONE",
        "statusText": f"{command_definition['label']} 완료",
        "doneAt": now,
        "doneStatus": done_status,
        "doneStatusText": done_status_text,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
        "listenerMode": mode,
        "adapterMode": os.getenv("COBOT1_ADAPTER_MODE", "-"),
    }

    if is_final_completed:
        current_job_update["completedAt"] = now
        request_update["completedAt"] = now
        command_update["completedAt"] = now
    else:
        request_update[f"{command_type}DoneAt"] = now
        command_update[f"{command_type}DoneAt"] = now

    # 이미지·프로세스 데이터를 payload에 병합
    image_data = collect_result_image_data(result or {})
    apply_image_data_to_updates(
        image_data=image_data,
        current_job_update=current_job_update,
        request_update=request_update,
        command_update=command_update,
    )

    process_data = collect_process_adapter_data(result or {})
    apply_process_data_to_updates(
        process_data=process_data,
        current_job_update=current_job_update,
        request_update=request_update,
        command_update=command_update,
    )

    # Firebase 갱신 후 로봇 상태를 IDLE로 복귀
    update_current_job(current_job_update)
    update_request(job_id, request_update)
    update_command(command_update)

    set_robot_state(
        STATUS_IDLE,
        extra_data={
            "lastCommandType": command_type,
            "lastJobId": job_id,
            "currentCommandType": "",
            "currentJobId": "",
        },
    )

    print("=" * 70)
    print("[Listener] 공정 완료 처리 완료")
    print(f"[Listener] job_id      : {job_id}")
    print(f"[Listener] commandType : {command_type}")
    print(f"[Listener] doneStatus  : {done_status}")
    print(f"[Listener] progress    : {done_progress}%")
    print("=" * 70)

    schedule_auto_run_next_command(
        job_id=job_id,
        command=command,
        mode=mode,
    )


def mark_job_error(
    job_id: str | None,
    error_message: str,
    command: dict | None = None,
) -> None:
    # 작업 오류를 Firebase 4개 경로에 기록한다.
    # stop control이 처리된 작업이면 에러 처리를 건너뛴다.
    # input:  job_id="abc" | None, error_message="알 수 없는 오류",
    #         command={"commandType": "drawing", ...} | None
    # output: None — Firebase 갱신
    # stop control이 처리된 작업은 에러 기록 생략
    remembered = get_remembered_control_action(job_id) if job_id else {}

    if remembered.get("action") == CONTROL_ACTION_STOP:
        print(
            f"[Listener][Error][Skip] control 처리된 작업 에러처리 무시: "
            f"job_id={job_id}, action={remembered.get('action')}, error={error_message}"
        )
        return

    now = now_text()

    # command가 없을 수 있으므로 빈 dict로 폴백
    command_type = get_command_type(command or {}) if command else ""
    command_definition = get_command_definition(command_type)

    print(f"[Listener][Error] {error_message}")

    # 에러 payload 구성
    command_update = {
        "status": "ERROR",
        "statusText": "오류 발생",
        "errorMessage": error_message,
        "errorAt": now,
        "adapterMode": os.getenv("COBOT1_ADAPTER_MODE", "-"),
    }

    current_job_update = {
        "status": STATUS_ERROR,
        "statusText": "오류 발생",
        "progress": 0,
        "updatedAt": now,
    }

    request_update = {
        "status": STATUS_ERROR,
        "statusText": "오류 발생",
        "errorMessage": error_message,
        "progress": 0,
        "updatedAt": now,
    }

    if command_type:
        command_update["commandType"] = command_type
        current_job_update["commandType"] = command_type
        request_update["lastCommandType"] = command_type

    if command_definition:
        command_update["commandLabel"] = command_definition["label"]
        current_job_update["commandLabel"] = command_definition["label"]
        request_update["lastCommandLabel"] = command_definition["label"]

    # Firebase 갱신 (job_id 없으면 request는 건너뜀)
    update_command(command_update)
    update_current_job(current_job_update)

    if job_id:
        update_request(job_id, request_update)

    set_robot_state(
        STATUS_ERROR,
        extra_data={
            "currentCommandType": command_type,
            "currentJobId": job_id or "",
        },
    )