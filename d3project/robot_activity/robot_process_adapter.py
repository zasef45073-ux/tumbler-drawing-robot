import json
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from string import Template

from robot_activity.robot_process_control import run_managed_process


# ============================================================
# robot_process_adapter.py
#
# 역할:
# - drawing을 제외한 외부 공정 파일을 subprocess로 실행하기 위한 공통 adapter
# - 외부 팀/개별 공정 파일은 직접 수정하지 않고 command로 감싼다.
#
# 현재 5공정 구조:
# 1. tumbler_place  : 텀블러 놓기          → pick_tumbler.py
# 2. drawing        : 펜 잡기+그림+펜 놓기 → robot_job_runner.py 쪽에서 처리
# 3. glue           : 풀 바르기            → 아직 없으면 placeholder
# 4. paper_attach   : 종이 붙이기          → paper_grip.py
# 5. rolling_return : 롤링 후 원위치       → rolling.py
#
# 이 파일에서 처리하는 공정:
# - tumbler_place
# - glue
# - paper_attach
# - rolling_return
#
# 처리하지 않는 공정:
# - drawing
#   drawing은 기존 성공 구조인
#   preview_main.py → pen_grip.py → main.py → pen_release.py를 유지하므로
#   robot_job_runner.py / robot_algorithm_adapter.py에서 처리한다.
#
# 제어 기능:
# - real 모드 외부 공정 실행은 robot_process_control.run_managed_process()로 감싼다.
# - listener의 control watcher가 terminate_current_process()를 호출하면
#   현재 실행 중인 외부 subprocess를 종료할 수 있다.
#
# 기본 실행:
# - 환경변수를 export하지 않아도 d3project 루트의 기본 파일을 실행한다.
#
#   tumbler_place  → pick_tumbler.py
#   glue           → glue_placeholder_runner.py
#   paper_attach   → paper_grip.py
#   rolling_return → rolling.py
#
# 환경변수 override:
# - 나중에 실제 풀 바르기 파일이 생기거나 다른 파일로 바꾸고 싶으면
#   아래 환경변수만 지정하면 기본 command보다 환경변수가 우선된다.
#
#   ROBOT_TUMBLER_PLACE_RUNNER_CMD
#   ROBOT_GLUE_RUNNER_CMD
#   ROBOT_PAPER_ATTACH_RUNNER_CMD
#   ROBOT_ROLLING_RETURN_RUNNER_CMD
#
# 예:
#   export ROBOT_GLUE_RUNNER_CMD="/usr/bin/python3 /path/to/real_glue.py"
#
# command_json:
# - command_json이 필요한 외부 파일은 command template에서 ${command_json}을 사용하면 된다.
# - command_json이 필요 없는 파일은 그냥 python 파일만 실행하면 된다.
# ============================================================


# =========================
# 기본 경로
# =========================

PROJECT_DIR = Path(__file__).resolve().parent


# =========================
# commandType 정의
# =========================

COMMAND_TYPE_TUMBLER_PLACE = "tumbler_place"
COMMAND_TYPE_GLUE = "glue"
COMMAND_TYPE_PAPER_ATTACH = "paper_attach"
COMMAND_TYPE_ROLLING_RETURN = "rolling_return"

# 기존 commandType 호환용
COMMAND_TYPE_PAPER = COMMAND_TYPE_TUMBLER_PLACE
COMMAND_TYPE_ATTACH = COMMAND_TYPE_PAPER_ATTACH

LEGACY_COMMAND_TYPE_ALIAS_MAP = {
    "paper": COMMAND_TYPE_TUMBLER_PLACE,
    "attach": COMMAND_TYPE_PAPER_ATTACH,
}

SUPPORTED_PROCESS_TYPES = {
    COMMAND_TYPE_TUMBLER_PLACE,
    COMMAND_TYPE_GLUE,
    COMMAND_TYPE_PAPER_ATTACH,
    COMMAND_TYPE_ROLLING_RETURN,
}


# =========================
# 외부 runner 환경변수 이름
# =========================

RUNNER_COMMAND_ENV_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: "ROBOT_TUMBLER_PLACE_RUNNER_CMD",
    COMMAND_TYPE_GLUE: "ROBOT_GLUE_RUNNER_CMD",
    COMMAND_TYPE_PAPER_ATTACH: "ROBOT_PAPER_ATTACH_RUNNER_CMD",
    COMMAND_TYPE_ROLLING_RETURN: "ROBOT_ROLLING_RETURN_RUNNER_CMD",
}


# =========================
# 기본 runner command
# =========================
#
# 환경변수를 따로 export하지 않아도 listener 하나만 실행하면
# d3project 루트의 기본 공정 파일을 자동으로 실행하게 한다.
#
# 우선순위:
# 1. 환경변수 runner command
# 2. 아래 기본 runner command
#
# glue는 아직 실제 파일이 없으므로 placeholder를 기본값으로 둔다.

DEFAULT_RUNNER_COMMAND_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: (
        f"/usr/bin/python3 {PROJECT_DIR / 'pick_tumbler.py'}"
    ),
    COMMAND_TYPE_GLUE: (
        f"/usr/bin/python3 {PROJECT_DIR / 'pick_glue.py'} "
    ),
    COMMAND_TYPE_PAPER_ATTACH: (
        f"/usr/bin/python3 {PROJECT_DIR / 'paper_grip.py'}"
    ),
    COMMAND_TYPE_ROLLING_RETURN: (
        f"/usr/bin/python3 {PROJECT_DIR / 'rolling.py'}"
    ),
}


# =========================
# 공정 표시 정보
# =========================

PROCESS_LABEL_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: "텀블러 놓기",
    COMMAND_TYPE_GLUE: "풀 바르기",
    COMMAND_TYPE_PAPER_ATTACH: "종이 붙이기",
    COMMAND_TYPE_ROLLING_RETURN: "롤링 후 원위치",
}

PROCESS_RUNNING_MESSAGE_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: "텀블러 놓기 외부 공정 실행 중",
    COMMAND_TYPE_GLUE: "풀 바르기 외부 공정 실행 중",
    COMMAND_TYPE_PAPER_ATTACH: "종이 붙이기 외부 공정 실행 중",
    COMMAND_TYPE_ROLLING_RETURN: "롤링 후 원위치 외부 공정 실행 중",
}

PROCESS_DONE_MESSAGE_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: "텀블러 놓기 외부 공정 완료",
    COMMAND_TYPE_GLUE: "풀 바르기 외부 공정 완료",
    COMMAND_TYPE_PAPER_ATTACH: "종이 붙이기 외부 공정 완료",
    COMMAND_TYPE_ROLLING_RETURN: "롤링 후 원위치 외부 공정 완료",
}


# =========================
# 상태 / step / progress 정의
# =========================

PROCESS_RUNNING_STATUS_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: "TUMBLER_PLACING",
    COMMAND_TYPE_GLUE: "GLUING",
    COMMAND_TYPE_PAPER_ATTACH: "PAPER_ATTACHING",
    COMMAND_TYPE_ROLLING_RETURN: "ROLLING_RETURNING",
}

PROCESS_STEP_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: "1 / 5",
    COMMAND_TYPE_GLUE: "3 / 5",
    COMMAND_TYPE_PAPER_ATTACH: "4 / 5",
    COMMAND_TYPE_ROLLING_RETURN: "5 / 5",
}

PROCESS_RUNNING_PROGRESS_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: 22,
    COMMAND_TYPE_GLUE: 74,
    COMMAND_TYPE_PAPER_ATTACH: 88,
    COMMAND_TYPE_ROLLING_RETURN: 97,
}

PROCESS_DONE_PROGRESS_MAP = {
    COMMAND_TYPE_TUMBLER_PLACE: 30,
    COMMAND_TYPE_GLUE: 80,
    COMMAND_TYPE_PAPER_ATTACH: 92,
    COMMAND_TYPE_ROLLING_RETURN: 100,
}


# =========================
# 기본 설정
# =========================

DEFAULT_DEMO_DELAY_SEC = float(
    os.getenv("ROBOT_PROCESS_ADAPTER_DEMO_DELAY_SEC", "1")
)

DEFAULT_TIMEOUT_SEC = int(
    os.getenv("ROBOT_PROCESS_ADAPTER_TIMEOUT_SEC", "300")
)


# =========================
# 공통 유틸
# =========================

def now_text():
    """
    로그/결과에 사용할 현재 시간 문자열
    """

    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_command_type(command_type):
    """
    외부 process adapter가 처리할 commandType인지 정리한다.

    신규 지원값:
    - tumbler_place
    - glue
    - paper_attach
    - rolling_return

    기존 호환값:
    - paper  → tumbler_place
    - attach → paper_attach
    """

    clean_value = str(command_type or "").strip().lower()

    if clean_value in LEGACY_COMMAND_TYPE_ALIAS_MAP:
        return LEGACY_COMMAND_TYPE_ALIAS_MAP[clean_value]

    if clean_value in SUPPORTED_PROCESS_TYPES:
        return clean_value

    return ""


def get_process_label(command_type):
    """
    commandType 표시명 반환
    """

    return PROCESS_LABEL_MAP.get(command_type, command_type or "-")


def get_running_status(command_type):
    """
    commandType별 실행 중 status 반환
    """

    return PROCESS_RUNNING_STATUS_MAP.get(command_type, "IDLE")


def get_process_step(command_type):
    """
    commandType별 step 반환
    """

    return PROCESS_STEP_MAP.get(command_type, "0 / 5")


def get_running_progress(command_type):
    """
    commandType별 실행 중 progress 반환
    """

    return PROCESS_RUNNING_PROGRESS_MAP.get(command_type, 0)


def get_done_progress(command_type):
    """
    commandType별 완료 progress 반환
    """

    return PROCESS_DONE_PROGRESS_MAP.get(command_type, 0)


def make_process_terminated_error(label, return_code):
    """
    process manager에 의해 종료된 subprocess 에러 메시지를 보기 좋게 만든다.

    Linux에서 SIGTERM 종료는 보통 returncode=-15,
    SIGKILL 종료는 보통 returncode=-9로 잡힌다.
    """

    if return_code == -15:
        return f"{label} 외부 runner가 SIGTERM으로 중지되었습니다."

    if return_code == -9:
        return f"{label} 외부 runner가 SIGKILL로 강제 중지되었습니다."

    return f"{label} 외부 runner가 실패했습니다. returnCode={return_code}"


def make_result(
    success,
    command_type,
    job_id,
    message,
    error_message="",
    mode="demo",
    runner_command="",
    stdout="",
    stderr="",
    return_code=None,
    extra=None,
):
    """
    listener가 이해할 수 있는 표준 결과 형식
    """

    return {
        "success": bool(success),
        "jobId": job_id,
        "commandType": command_type,
        "commandLabel": get_process_label(command_type),
        "message": message,
        "errorMessage": error_message,
        "mode": mode,
        "runnerCommand": runner_command,
        "stdout": stdout,
        "stderr": stderr,
        "returnCode": return_code,
        "finishedAt": now_text(),
        "extra": extra or {},
    }


def call_progress(
    progress_callback,
    job_id,
    status,
    status_text,
    step,
    progress,
    command_type,
    extra_data=None,
):
    """
    listener 진행률 콜백 호출
    """

    print(
        f"[ProcessAdapter][Progress] {job_id} | "
        f"{command_type} | {status_text} | step={step} | progress={progress}%"
    )

    if progress_callback is None:
        return

    merged_extra = {
        "commandType": command_type,
        "commandLabel": get_process_label(command_type),
        "processAdapter": True,
    }

    if extra_data:
        merged_extra.update(extra_data)

    progress_callback(
        job_id=job_id,
        status=status,
        status_text=status_text,
        step=step,
        progress=progress,
        extra_data=merged_extra,
    )


def get_runner_command_template(command_type):
    """
    commandType별 외부 runner command template을 반환한다.

    우선순위:
    1. 환경변수에 지정된 command
    2. d3project 기본 runner command

    그래서 평소에는 export 없이 아래 명령만 실행하면 된다.

        python3 robot_command_listener.py --mode real

    나중에 실제 풀 바르기 파일이 생기면 그때만 환경변수로 덮어쓴다.

        export ROBOT_GLUE_RUNNER_CMD="/usr/bin/python3 /path/to/glue.py"
    """

    env_name = RUNNER_COMMAND_ENV_MAP.get(command_type)

    if env_name:
        env_command = str(os.getenv(env_name, "")).strip()

        if env_command:
            print(
                f"[ProcessAdapter] 환경변수 runner command 사용: "
                f"{env_name}={env_command}"
            )
            return env_command

    default_command = str(
        DEFAULT_RUNNER_COMMAND_MAP.get(command_type, "")
    ).strip()

    if default_command:
        print(
            f"[ProcessAdapter] 기본 runner command 사용: "
            f"{command_type} -> {default_command}"
        )

    return default_command


def make_command_context(command_type, command, command_json_path):
    """
    외부 runner command template에 주입할 변수 context 생성

    Template 변수 예:
    ${project_dir}
    ${job_id}
    ${command_type}
    ${command_label}
    ${image_url}
    ${converted_image_url}
    ${option}
    ${request_text}
    ${customer_name}
    ${command_json}
    """

    command = command or {}

    return {
        "project_dir": str(PROJECT_DIR),
        "job_id": str(command.get("jobId", "")),
        "command_type": command_type,
        "command_label": get_process_label(command_type),
        "image_url": str(command.get("imageUrl", "")),
        "converted_image_url": str(command.get("convertedImageUrl", "")),
        "option": str(command.get("option", "")),
        "request_text": str(command.get("requestText", "")),
        "customer_name": str(command.get("customerName", "")),
        "command_json": str(command_json_path),
    }


def render_runner_command(command_template, context):
    """
    환경변수 command template에 context 값을 치환한다.

    예:
    "/usr/bin/python3 ${project_dir}/pick_tumbler.py"
    "/usr/bin/python3 ${project_dir}/glue_placeholder_runner.py --command-json ${command_json}"
    """

    template = Template(command_template)

    return template.safe_substitute(context)


def split_command(command_text):
    """
    shell 문자열을 subprocess에 넣을 argv list로 변환한다.

    shell=True를 쓰지 않기 위해 shlex.split 사용.
    """

    return shlex.split(command_text)


def write_command_json(command_type, command):
    """
    외부 팀 코드에 넘길 수 있는 임시 JSON 파일 생성

    외부 파일이 command 정보가 필요하면
    command template에서 ${command_json}을 사용하면 된다.

    pick_tumbler.py, paper_grip.py, rolling.py처럼 command_json을 받지 않는 파일은
    command template에서 ${command_json}을 안 쓰면 된다.
    """

    payload = {
        "commandType": command_type,
        "commandLabel": get_process_label(command_type),
        "command": command or {},
        "createdAt": now_text(),
    }

    temp_dir = Path(tempfile.gettempdir()) / "d3project_robot_process"
    temp_dir.mkdir(parents=True, exist_ok=True)

    job_id = str((command or {}).get("jobId", "unknown")).replace("/", "_")
    json_path = temp_dir / f"{job_id}_{command_type}_command.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return json_path


# =========================
# demo 처리
# =========================

def run_demo_process(
    command_type,
    command,
    progress_callback=None,
):
    """
    외부 공정 demo 처리

    실제 외부 파일 실행 없음.
    listener와 Firebase 흐름 확인용.
    """

    job_id = command.get("jobId", "")
    label = get_process_label(command_type)

    print("=" * 70)
    print("[ProcessAdapter][DEMO] 공정 demo 시작")
    print(f"[ProcessAdapter][DEMO] job_id      : {job_id}")
    print(f"[ProcessAdapter][DEMO] commandType : {command_type}")
    print(f"[ProcessAdapter][DEMO] label       : {label}")
    print("[ProcessAdapter][DEMO] 실제 외부 공정 파일은 실행하지 않습니다.")
    print("=" * 70)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status=get_running_status(command_type),
        status_text=f"{label} demo 처리 중",
        step=get_process_step(command_type),
        progress=get_running_progress(command_type),
        command_type=command_type,
        extra_data={
            "demoProcess": True,
        },
    )

    time.sleep(DEFAULT_DEMO_DELAY_SEC)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status=get_running_status(command_type),
        status_text=f"{label} demo 완료 준비 중",
        step=get_process_step(command_type),
        progress=max(get_done_progress(command_type) - 1, 0),
        command_type=command_type,
        extra_data={
            "demoProcess": True,
        },
    )

    time.sleep(DEFAULT_DEMO_DELAY_SEC)

    return make_result(
        success=True,
        command_type=command_type,
        job_id=job_id,
        message=f"{label} demo 완료",
        mode="demo",
        extra={
            "demoProcess": True,
        },
    )


# =========================
# real 처리
# =========================

def run_external_process(
    command_type,
    command,
    progress_callback=None,
):
    """
    환경변수 또는 기본 runner command로 외부 공정 runner를 실행한다.

    real 모드 규칙:
    - 환경변수가 있으면 환경변수 command를 우선 사용
    - 환경변수가 없으면 DEFAULT_RUNNER_COMMAND_MAP의 기본 command 사용
    - 둘 다 없으면 실패 처리

    제어 기능:
    - run_managed_process()로 실행하므로 listener가 현재 subprocess를 종료할 수 있다.
    """

    job_id = command.get("jobId", "")
    label = get_process_label(command_type)

    command_template = get_runner_command_template(command_type)

    if not command_template:
        env_name = RUNNER_COMMAND_ENV_MAP.get(command_type, "-")

        error_message = (
            f"{label} 외부 runner command가 설정되지 않았습니다. "
            f"환경변수 {env_name} 또는 DEFAULT_RUNNER_COMMAND_MAP에 "
            "실행 명령이 필요합니다."
        )

        print("=" * 70)
        print("[ProcessAdapter][REAL][BLOCKED] 외부 runner 미설정")
        print(f"[ProcessAdapter][REAL][BLOCKED] job_id      : {job_id}")
        print(f"[ProcessAdapter][REAL][BLOCKED] commandType : {command_type}")
        print(f"[ProcessAdapter][REAL][BLOCKED] env         : {env_name}")
        print("=" * 70)

        return make_result(
            success=False,
            command_type=command_type,
            job_id=job_id,
            message=f"{label} 실행 실패",
            error_message=error_message,
            mode="real",
            extra={
                "blockReason": "RUNNER_COMMAND_NOT_CONFIGURED",
                "envName": env_name,
            },
        )

    command_json_path = write_command_json(command_type, command)

    context = make_command_context(
        command_type=command_type,
        command=command,
        command_json_path=command_json_path,
    )

    rendered_command = render_runner_command(
        command_template,
        context,
    )

    argv = split_command(rendered_command)

    print("=" * 70)
    print("[ProcessAdapter][REAL] 외부 공정 실행 시작")
    print(f"[ProcessAdapter][REAL] job_id      : {job_id}")
    print(f"[ProcessAdapter][REAL] commandType : {command_type}")
    print(f"[ProcessAdapter][REAL] label       : {label}")
    print(f"[ProcessAdapter][REAL] command     : {rendered_command}")
    print(f"[ProcessAdapter][REAL] commandJson : {command_json_path}")
    print("=" * 70)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status=get_running_status(command_type),
        status_text=PROCESS_RUNNING_MESSAGE_MAP.get(command_type, "외부 공정 실행 중"),
        step=get_process_step(command_type),
        progress=get_running_progress(command_type),
        command_type=command_type,
        extra_data={
            "externalProcess": True,
            "runnerCommand": rendered_command,
            "commandJson": str(command_json_path),
        },
    )

    try:
        completed = run_managed_process(
            command=argv,
            label=f"{command_type}_external_runner:{job_id}",
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SEC,
        )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        return_code = completed.returncode

        print("[ProcessAdapter][REAL] 외부 공정 stdout:")
        print(stdout)

        if stderr:
            print("[ProcessAdapter][REAL] 외부 공정 stderr:")
            print(stderr)

        if return_code != 0:
            error_message = make_process_terminated_error(
                label=label,
                return_code=return_code,
            )

            return make_result(
                success=False,
                command_type=command_type,
                job_id=job_id,
                message=f"{label} 실행 실패",
                error_message=error_message,
                mode="real",
                runner_command=rendered_command,
                stdout=stdout,
                stderr=stderr,
                return_code=return_code,
                extra={
                    "externalProcess": True,
                    "commandJson": str(command_json_path),
                },
            )

        call_progress(
            progress_callback=progress_callback,
            job_id=job_id,
            status=get_running_status(command_type),
            status_text=PROCESS_DONE_MESSAGE_MAP.get(command_type, "외부 공정 완료"),
            step=get_process_step(command_type),
            progress=max(get_done_progress(command_type) - 1, 0),
            command_type=command_type,
            extra_data={
                "externalProcess": True,
                "runnerCommand": rendered_command,
                "commandJson": str(command_json_path),
            },
        )

        return make_result(
            success=True,
            command_type=command_type,
            job_id=job_id,
            message=f"{label} 외부 공정 완료",
            mode="real",
            runner_command=rendered_command,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            extra={
                "externalProcess": True,
                "commandJson": str(command_json_path),
            },
        )

    except subprocess.TimeoutExpired as e:
        error_message = (
            f"{label} 외부 runner 실행 시간이 초과되었습니다. "
            f"timeout={DEFAULT_TIMEOUT_SEC}s"
        )

        return make_result(
            success=False,
            command_type=command_type,
            job_id=job_id,
            message=f"{label} 실행 시간 초과",
            error_message=error_message,
            mode="real",
            runner_command=rendered_command,
            stdout=e.stdout or "",
            stderr=e.stderr or "",
            return_code=None,
            extra={
                "externalProcess": True,
                "commandJson": str(command_json_path),
                "timeoutSec": DEFAULT_TIMEOUT_SEC,
            },
        )

    except Exception as e:
        error_message = str(e)

        return make_result(
            success=False,
            command_type=command_type,
            job_id=job_id,
            message=f"{label} 실행 중 예외 발생",
            error_message=error_message,
            mode="real",
            runner_command=rendered_command,
            return_code=None,
            extra={
                "externalProcess": True,
                "commandJson": str(command_json_path),
            },
        )


# =========================
# 외부 호출 메인 함수
# =========================

def run_process_job(
    command_type,
    command,
    mode="demo",
    progress_callback=None,
):
    """
    listener에서 호출할 외부 공정 adapter.

    Args:
        command_type:
            tumbler_place / glue / paper_attach / rolling_return

        command:
            Firebase commands/start dict

        mode:
            demo 또는 real

        progress_callback:
            listener의 update_progress_from_runner 같은 콜백

    Returns:
        표준 result dict
    """

    command_type = normalize_command_type(command_type)
    mode = str(mode or "demo").strip().lower()

    if not command_type:
        return make_result(
            success=False,
            command_type="",
            job_id=(command or {}).get("jobId", ""),
            message="지원하지 않는 공정",
            error_message=(
                "tumbler_place / glue / paper_attach / rolling_return 중 하나만 지원합니다."
            ),
            mode=mode,
            extra={
                "blockReason": "INVALID_PROCESS_COMMAND_TYPE",
            },
        )

    if not isinstance(command, dict):
        return make_result(
            success=False,
            command_type=command_type,
            job_id="",
            message="command 형식 오류",
            error_message="command는 dict 형태여야 합니다.",
            mode=mode,
            extra={
                "blockReason": "INVALID_COMMAND_OBJECT",
            },
        )

    job_id = command.get("jobId", "")

    if not job_id:
        return make_result(
            success=False,
            command_type=command_type,
            job_id="",
            message="jobId 누락",
            error_message="command에 jobId가 없습니다.",
            mode=mode,
            extra={
                "blockReason": "MISSING_JOB_ID",
            },
        )

    if mode == "demo":
        return run_demo_process(
            command_type=command_type,
            command=command,
            progress_callback=progress_callback,
        )

    if mode == "real":
        return run_external_process(
            command_type=command_type,
            command=command,
            progress_callback=progress_callback,
        )

    return make_result(
        success=False,
        command_type=command_type,
        job_id=job_id,
        message="지원하지 않는 실행 모드",
        error_message=f"지원하지 않는 mode입니다: {mode}. demo 또는 real만 지원합니다.",
        mode=mode,
        extra={
            "blockReason": "INVALID_PROCESS_MODE",
        },
    )


# =========================
# 단독 실행 테스트
# =========================

if __name__ == "__main__":
    sample_command = {
        "jobId": "TEST-PROCESS-001",
        "commandType": COMMAND_TYPE_TUMBLER_PLACE,
        "customerName": "테스트",
        "imageUrl": "",
        "option": "기본",
        "requestText": "adapter 단독 실행 테스트",
    }

    result = run_process_job(
        command_type=COMMAND_TYPE_TUMBLER_PLACE,
        command=sample_command,
        mode="demo",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))