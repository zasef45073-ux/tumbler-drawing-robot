import time
# 전역상수 설정 불러오기
from command_type_and_status_const import (
    COMMAND_DEFINITIONS,
    COMMAND_TYPE_DRAWING,
    CONTROL_ACTION_PAUSE,
    CONTROL_ACTION_RESUME,
    CONTROL_ACTION_STOP,
    LEGACY_COMMAND_TYPE_ALIAS_MAP,
    VALID_COMMAND_TYPES,
)

# =========================
# 공통 유틸
# commandType 정규화·검증, 진행률 매핑, 제어 서명 생성 등 순수 헬퍼 함수 모음.
# Firebase / ROS2 의존성 없이 독립적으로 동작한다.
# =========================
def now_text() -> str:
    # 현재 시각을 "YYYY-MM-DD HH:MM:SS" 형식 문자열로 반환
    # input:  없음
    # output: "2026-05-08 12:00:00"
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_timestamp() -> float:
    # 현재 Unix 타임스탬프(초 단위)를 반환
    # input:  없음
    # output: 1746691200.123
    return time.time()


def validate_job_mode(mode: object) -> str:
    # None·공백 입력을 방어하고 소문자로 정규화한다.
    # input:  "Demo" / "REAL" / None
    # output: "demo" / "real"
    # raises: ValueError — demo / real 이외의 값
    clean_mode = str(mode or "").strip().lower()

    if clean_mode not in {"demo", "real"}:
        raise ValueError(
            f"지원하지 않는 listener mode입니다: {mode}. "
            "demo 또는 real 중 하나를 사용하세요."
        )

    return clean_mode


def normalize_command_type(command_type: object) -> str | None:
    # 레거시 alias("paper" → tumbler_place 등)를 현재 명칭으로 변환한다.
    # 유효하지 않은 값이면 None을 반환한다.
    # input:  "paper" / "Drawing" / "unknown" / None
    # output: "tumbler_place" / "drawing" / None
    clean_command_type = str(command_type or "").strip().lower()

    if clean_command_type in LEGACY_COMMAND_TYPE_ALIAS_MAP:
        return LEGACY_COMMAND_TYPE_ALIAS_MAP[clean_command_type]

    if clean_command_type in VALID_COMMAND_TYPES:
        return clean_command_type

    return None


def normalize_control_action(action: object) -> str:
    # stop / pause / resume 외의 값은 빈 문자열로 처리한다.
    # input:  "Stop" / "PAUSE" / "unknown" / None
    # output: "stop" / "pause" / ""
    clean_action = str(action or "").strip().lower()

    if clean_action in {
        CONTROL_ACTION_STOP,
        CONTROL_ACTION_PAUSE,
        CONTROL_ACTION_RESUME,
    }:
        return clean_action

    return ""


def get_command_type(command: object) -> str | None:
    # commandType 키가 없으면 command_type을 시도하고, 둘 다 없으면 drawing으로 폴백한다.
    # input:  {"commandType": "glue", ...} / {"command_type": "paper"} / {} / None
    # output: "glue" / "tumbler_place" / "drawing" — dict 아니면 None
    if not isinstance(command, dict):
        return None

    raw_command_type = (
        command.get("commandType")
        or command.get("command_type")
        or COMMAND_TYPE_DRAWING
    )

    return normalize_command_type(raw_command_type)


def get_command_definition(command_type: object) -> dict | None:
    # 정규화된 commandType으로 COMMAND_DEFINITIONS에서 정의 dict를 조회한다.
    # input:  "drawing" / "paper"(레거시) / "unknown" / None
    # output: COMMAND_DEFINITIONS["drawing"] dict / None
    clean_command_type = normalize_command_type(command_type)

    if not clean_command_type:
        return None

    return COMMAND_DEFINITIONS.get(clean_command_type)


def map_drawing_runner_progress(progress: object) -> int:
    # 드로잉 러너의 0~100 진행률을 COMMAND_DEFINITIONS의 startProgress~doneProgress-1 구간으로 선형 매핑한다.
    # input:  50.0 / "75" / None
    # output: startProgress(32)~doneProgress-1(64) 사이의 정수
    try:
        local_progress = float(progress)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        local_progress = 0.0

    if local_progress < 0:
        local_progress = 0.0

    if local_progress > 100:
        local_progress = 100.0

    start = COMMAND_DEFINITIONS[COMMAND_TYPE_DRAWING]["startProgress"]
    end = COMMAND_DEFINITIONS[COMMAND_TYPE_DRAWING]["doneProgress"] - 1

    mapped = start + (end - start) * (local_progress / 100.0)

    return int(round(mapped))


def get_control_signature(control: object) -> str:
    # jobId·action·requestedAt 조합으로 동일 제어 명령의 중복 처리를 방지하는 서명을 만든다.
    # input:  {"jobId": "abc", "action": "stop", "requestedAt": "2026-05-08 12:00:00", ...}
    # output: "abc|stop|2026-05-08 12:00:00" — dict 아니면 ""
    if not isinstance(control, dict):
        return ""

    job_id = control.get("jobId", "")
    action = control.get("action", "")
    requested_at = control.get("requestedAt", "")

    return f"{job_id}|{action}|{requested_at}"
