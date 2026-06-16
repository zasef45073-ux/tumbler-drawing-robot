"""
robot_algorithm_adapter.py

Doosan M0609 로봇 드로잉 알고리즘 연결 어댑터

실행 모드:
- preview
  preview_main.py 실행
  로봇은 움직이지 않음

- robot
  알고리즘 팀 원본 main.py 실행
  실제 로봇 동작

- preview_then_robot
  preview_main.py 실행
  preview 이미지 생성
  preview 이미지를 네 PC Flask 서버로 업로드
  3초 대기
  pen_grip.py 실행
  알고리즘 팀 원본 main.py 실행
  pen_release.py 실행

제어 기능:
- subprocess 실행은 robot_process_control.run_managed_process()로 감싼다.
- listener의 control watcher가 terminate_current_process()를 호출하면
  현재 실행 중인 preview/pen/main subprocess를 종료할 수 있다.
"""

import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path

from robot_activity.robot_process_control import run_managed_process


# ============================================================
# 경로 / 실행 환경 설정
# ============================================================

D3PROJECT_DIR = Path(__file__).resolve().parent

ALGORITHM_DIR = Path(
    os.getenv(
        "COBOT1_ALGORITHM_DIR",
        "/home/lee/cobot_ws/src/cobot1/cobot1",
    )
).expanduser()

PREVIEW_MAIN_FILE = ALGORITHM_DIR / "preview_main.py"
ROBOT_MAIN_FILE = ALGORITHM_DIR / "main.py"

ALGORITHM_INPUT_DIR = ALGORITHM_DIR / "_input"
ALGORITHM_INPUT_IMAGE = ALGORITHM_INPUT_DIR / "test.png"

PREVIEW_OUTPUT_ROOT = Path(
    os.getenv(
        "COBOT1_PREVIEW_OUTPUT_ROOT",
        str(D3PROJECT_DIR / "converted_jobs"),
    )
).expanduser()

PREVIEW_PYTHON = os.getenv(
    "COBOT1_PREVIEW_PYTHON",
    "/usr/bin/python3",
)

ROBOT_PYTHON = os.getenv(
    "COBOT1_ROBOT_PYTHON",
    "/usr/bin/python3",
)

PREVIEW_TIMEOUT_SEC = int(
    os.getenv(
        "COBOT1_PREVIEW_TIMEOUT_SEC",
        "180",
    )
)

ROBOT_TIMEOUT_SEC = int(
    os.getenv(
        "COBOT1_ROBOT_TIMEOUT_SEC",
        "3600",
    )
)

PREVIEW_TO_ROBOT_DELAY_SEC = int(
    os.getenv(
        "COBOT1_PREVIEW_TO_ROBOT_DELAY_SEC",
        "0",
    )
)

ADAPTER_MODE = os.getenv(
    "COBOT1_ADAPTER_MODE",
    "preview_then_robot",
).strip().lower()

RESTORE_TEST_IMAGE = os.getenv(
    "COBOT1_RESTORE_TEST_IMAGE",
    "1",
).strip().lower() in {"1", "true", "yes", "y"}


# ============================================================
# 펜 잡기 / 펜 반납 설정
# ============================================================

PEN_GRIP_FILE = Path(
    os.getenv(
        "COBOT1_PEN_GRIP_FILE",
        str(D3PROJECT_DIR / "pen_grip.py"),
    )
).expanduser()

PEN_RELEASE_FILE = Path(
    os.getenv(
        "COBOT1_PEN_RELEASE_FILE",
        str(D3PROJECT_DIR / "pen_release.py"),
    )
).expanduser()

PEN_TOOL_PYTHON = os.getenv(
    "COBOT1_PEN_TOOL_PYTHON",
    ROBOT_PYTHON,
)

PEN_TOOL_TIMEOUT_SEC = int(
    os.getenv(
        "COBOT1_PEN_TOOL_TIMEOUT_SEC",
        "180",
    )
)


# ============================================================
# preview 이미지 서버 업로드 설정
# ============================================================

PREVIEW_UPLOAD_TIMEOUT_SEC = int(
    os.getenv(
        "COBOT1_PREVIEW_UPLOAD_TIMEOUT_SEC",
        "30",
    )
)

# 0이면 preview 이미지 서버 업로드 실패해도 로봇 작업은 계속 진행
# 1이면 preview 이미지 서버 업로드 실패 시 전체 작업 ERROR 처리
REQUIRE_PREVIEW_UPLOAD = os.getenv(
    "COBOT1_REQUIRE_PREVIEW_UPLOAD",
    "0",
).strip().lower() in {"1", "true", "yes", "y"}


# ============================================================
# 실제 드로잉 진행률 파일 감시 설정
# ============================================================

DRAWING_PROGRESS_FILE_ROOT = Path(
    os.getenv(
        "COBOT1_DRAWING_PROGRESS_FILE_ROOT",
        str(D3PROJECT_DIR / "runtime" / "drawing_progress"),
    )
).expanduser()

DRAWING_PROGRESS_POLL_INTERVAL_SEC = float(
    os.getenv(
        "COBOT1_DRAWING_PROGRESS_POLL_INTERVAL_SEC",
        "0.15",
    )
)


# ============================================================
# config.py 기반 웹 표시 경로
# ============================================================

try:
    from config import Config
except Exception:
    Config = None


def get_converted_static_folder():
    if Config is not None and hasattr(Config, "CONVERTED_UPLOAD_FOLDER"):
        return Path(Config.CONVERTED_UPLOAD_FOLDER)

    return D3PROJECT_DIR / "static" / "uploads" / "converted"


def get_converted_url_prefix():
    if Config is not None and hasattr(Config, "CONVERTED_UPLOAD_URL_PREFIX"):
        return str(Config.CONVERTED_UPLOAD_URL_PREFIX).strip("/")

    return "static/uploads/converted"


def get_progress_static_folder():
    """
    드로잉 진행 애니메이션용 JSON 파일을 저장할 static 폴더.

    브라우저에서 fetch()로 읽을 수 있도록
    d3project/static/uploads/progress 아래에 저장한다.
    """

    return D3PROJECT_DIR / "static" / "uploads" / "progress"


def get_progress_url_prefix():
    """
    드로잉 진행 애니메이션용 JSON 파일 URL prefix.
    """

    return "static/uploads/progress"


def get_public_base_url():
    if Config is not None and hasattr(Config, "PUBLIC_BASE_URL"):
        return str(Config.PUBLIC_BASE_URL).rstrip("/")

    return os.getenv(
        "PUBLIC_BASE_URL",
        "http://127.0.0.1:5000",
    ).rstrip("/")


def get_converted_upload_api_url():
    return f"{get_public_base_url()}/api/upload-converted-image"


def get_progress_json_upload_api_url():
    return f"{get_public_base_url()}/api/upload-progress-json"


# ============================================================
# 공통 유틸
# ============================================================

def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def sanitize_filename_text(value):
    clean_value = str(value or "").strip()

    if not clean_value:
        return "unknown"

    return re.sub(r"[^A-Za-z0-9_.-]", "_", clean_value)


def ensure_file_exists(path, label):
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"{label} 파일을 찾을 수 없습니다: {file_path}"
        )

    if not file_path.is_file():
        raise FileNotFoundError(
            f"{label} 경로가 파일이 아닙니다: {file_path}"
        )

    return file_path


def ensure_dir_exists(path, label):
    dir_path = Path(path)

    if not dir_path.exists():
        raise FileNotFoundError(
            f"{label} 폴더를 찾을 수 없습니다: {dir_path}"
        )

    if not dir_path.is_dir():
        raise FileNotFoundError(
            f"{label} 경로가 폴더가 아닙니다: {dir_path}"
        )

    return dir_path


def print_subprocess_output(result):
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if stdout:
        print("-" * 70)
        print("[Robot Adapter][stdout]")
        print(stdout)
        print("-" * 70)

    if stderr:
        print("-" * 70)
        print("[Robot Adapter][stderr]")
        print(stderr)
        print("-" * 70)


def report_progress(
    progress_callback,
    job_id,
    status_text,
    step,
    progress,
    status="DRAWING",
    extra_data=None,
):
    if progress_callback is None:
        return

    progress_callback(
        job_id=job_id,
        status=status,
        status_text=status_text,
        step=step,
        progress=progress,
        extra_data=extra_data or {},
    )


def make_success_result(
    message="작업 완료",
    converted_image_path="",
    converted_image_url="",
    extra=None,
):
    return {
        "success": True,
        "message": message,
        "converted_image_path": converted_image_path,
        "converted_image_url": converted_image_url,
        "extra": extra or {},
    }


def make_failure_result(
    message="작업 실패",
    error_message="",
    converted_image_path="",
    converted_image_url="",
    extra=None,
):
    return {
        "success": False,
        "message": message,
        "errorMessage": error_message or message,
        "converted_image_path": converted_image_path,
        "converted_image_url": converted_image_url,
        "extra": extra or {},
    }


def make_process_terminated_error(label, returncode):
    """
    process manager에 의해 종료된 subprocess 에러 메시지를 보기 좋게 만든다.

    Linux에서 SIGTERM 종료는 보통 returncode=-15,
    SIGKILL 종료는 보통 returncode=-9로 잡힌다.
    """

    if returncode == -15:
        return f"{label} 실행이 SIGTERM으로 중지되었습니다."

    if returncode == -9:
        return f"{label} 실행이 SIGKILL로 강제 중지되었습니다."

    return f"{label} 실행 실패 (returncode={returncode})"


# ============================================================
# 실제 드로잉 progress JSON 감시
# ============================================================

def make_drawing_progress_file_path(job_id):
    """
    main.py / ik_solver.py가 기록할 실제 드로잉 진행률 JSON 경로를 만든다.
    """

    safe_job_id = sanitize_filename_text(job_id)

    DRAWING_PROGRESS_FILE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    return DRAWING_PROGRESS_FILE_ROOT / f"{safe_job_id}_drawing_progress.json"


def read_drawing_progress_payload(progress_file):
    """
    progress JSON 파일을 읽는다.

    파일이 아직 없거나 쓰는 중이라 JSON이 잠깐 깨져 있으면 None을 반환한다.
    """

    progress_path = Path(progress_file)

    if not progress_path.exists():
        return None

    try:
        with progress_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return None


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def publish_drawing_progress_payload(
    progress_callback,
    job_id,
    payload,
):
    """
    main.py / ik_solver.py가 기록한 progress JSON 내용을 Firebase current_job으로 올린다.
    """

    if progress_callback is None:
        return False

    if not payload:
        return False

    phase = str(
        payload.get("drawingPhase")
        or payload.get("phase")
        or "drawing"
    )

    point_index = _safe_int(
        payload.get("drawingPointIndex")
        or payload.get("pointIndex")
        or 0
    )

    total_points = _safe_int(
        payload.get("drawingTotalPoints")
        or payload.get("totalPoints")
        or 0
    )

    drawing_percent = _safe_int(
        payload.get("drawingProgressPercent")
        or payload.get("progressPercent")
        or 0
    )

    drawing_percent = max(0, min(drawing_percent, 100))

    # 전체 제작 진행률은 기존 흐름을 크게 흔들지 않기 위해
    # 실제 드로잉 중에는 90~95 사이에서만 움직이게 둔다.
    # canvas 표시는 drawingProgressPercent를 따로 사용한다.
    overall_progress = 90 + int(drawing_percent * 5 / 100)

    if phase == "ready":
        status_text = "실제 로봇 드로잉 준비 중"
        overall_progress = 90

    elif phase == "done":
        status_text = "실제 로봇 드로잉 완료"
        overall_progress = 95

    elif phase == "stopped":
        status_text = f"실제 로봇 드로잉 중지 - {drawing_percent}%"

    elif phase == "error":
        status_text = f"실제 로봇 드로잉 오류 - {drawing_percent}%"

    else:
        status_text = f"실제 로봇 드로잉 중 - {drawing_percent}%"

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text=status_text,
        step="6 / 6",
        progress=overall_progress,
        extra_data={
            "drawingPhase": phase,
            "drawingPointIndex": point_index,
            "drawingTotalPoints": total_points,
            "drawingProgressPercent": drawing_percent,
            "drawingProgressUpdatedAt": payload.get("updatedAt", now_text()),
        },
    )

    print(
        "[Robot Adapter][DrawingProgress] "
        f"{phase} | {drawing_percent}% | "
        f"{point_index}/{total_points}",
        flush=True,
    )

    return True


def start_drawing_progress_monitor(
    progress_file,
    job_id,
    progress_callback,
    stop_event,
):
    """
    main.py 실행 중 progress JSON 파일을 감시한다.

    main.py / ik_solver.py는 로컬 JSON 파일만 기록하고,
    adapter가 이 파일을 읽어서 Firebase에 반영한다.
    """

    progress_path = Path(progress_file)

    def monitor_worker():
        last_signature = None

        print("=" * 70, flush=True)
        print("[Robot Adapter][DrawingProgress] monitor 시작", flush=True)
        print(f"[Robot Adapter][DrawingProgress] file: {progress_path}", flush=True)
        print("=" * 70, flush=True)

        while not stop_event.is_set():
            payload = read_drawing_progress_payload(progress_path)

            if payload:
                signature = (
                    payload.get("drawingPhase") or payload.get("phase"),
                    payload.get("drawingProgressPercent") or payload.get("progressPercent"),
                    payload.get("drawingPointIndex") or payload.get("pointIndex"),
                    payload.get("drawingTotalPoints") or payload.get("totalPoints"),
                )

                if signature != last_signature:
                    publish_drawing_progress_payload(
                        progress_callback=progress_callback,
                        job_id=job_id,
                        payload=payload,
                    )
                    last_signature = signature

            time.sleep(DRAWING_PROGRESS_POLL_INTERVAL_SEC)

        # 종료 직후 마지막 상태 한 번 더 반영
        payload = read_drawing_progress_payload(progress_path)

        if payload:
            publish_drawing_progress_payload(
                progress_callback=progress_callback,
                job_id=job_id,
                payload=payload,
            )

        print("[Robot Adapter][DrawingProgress] monitor 종료", flush=True)

    monitor_thread = threading.Thread(
        target=monitor_worker,
        name=f"drawing-progress-monitor-{sanitize_filename_text(job_id)}",
        daemon=True,
    )

    monitor_thread.start()

    return monitor_thread


# ============================================================
# preview / robot 결과 파일 찾기
# ============================================================

def find_preview_result_image(output_dir):
    candidates = [
        output_dir / "preview_two_opt.png",
        output_dir / "preview_greedy_order.png",
        output_dir / "preview_bezier_fit.png",
        output_dir / "preview_edges.png",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "preview 결과 이미지를 찾을 수 없습니다. "
        f"확인 경로: {output_dir}"
    )


def find_algorithm_debug_image():
    candidates = [
        ALGORITHM_INPUT_DIR / "two_opt_debug.png",
        ALGORITHM_INPUT_DIR / "greedy_order_debug.png",
        ALGORITHM_INPUT_DIR / "bezier_fit_debug.png",
        ALGORITHM_INPUT_DIR / "bezier_output.png",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return ""


# ============================================================
# preview 이미지 로컬 복사 + 서버 업로드
# ============================================================

def copy_image_to_local_converted(
    job_id,
    source_image_path,
    suffix="preview_before_robot",
):
    """
    로봇 PC 로컬에도 preview 이미지를 보관한다.
    이 파일은 웹서버가 네 PC에 있을 경우 직접 표시용으로는 쓰이지 않을 수 있다.
    """

    source_path = ensure_file_exists(
        source_image_path,
        "preview 결과 이미지",
    )

    converted_folder = get_converted_static_folder()
    converted_folder.mkdir(parents=True, exist_ok=True)

    safe_job_id = sanitize_filename_text(job_id)
    safe_suffix = sanitize_filename_text(suffix)

    extension = source_path.suffix.lower().lstrip(".") or "png"
    converted_filename = f"{safe_job_id}_{safe_suffix}.{extension}"

    destination_path = converted_folder / converted_filename

    if source_path.resolve() != destination_path.resolve():
        shutil.copy2(source_path, destination_path)

    local_url = (
        f"{get_public_base_url()}/"
        f"{get_converted_url_prefix()}/"
        f"{converted_filename}"
    )

    print("=" * 70)
    print("[Robot Adapter] preview 이미지 로컬 복사 완료")
    print(f"[Robot Adapter] source : {source_path}")
    print(f"[Robot Adapter] saved  : {destination_path}")
    print(f"[Robot Adapter] local url candidate: {local_url}")
    print("=" * 70)

    return {
        "converted_image_path": str(destination_path),
        "converted_image_url": local_url,
        "converted_filename": converted_filename,
    }


def copy_preview_json_to_progress_static(
    job_id,
    source_json_path,
):
    """
    preview_main.py가 만든 preview_robot_path.json을
    브라우저에서 읽을 수 있는 static/uploads/progress 폴더로 복사한다.

    반환:
    {
        "drawing_path_json_path": "...",
        "drawing_path_json_url": "...",
        "drawing_path_json_filename": "..."
    }
    """

    source_path = ensure_file_exists(
        source_json_path,
        "preview 좌표 JSON",
    )

    progress_folder = get_progress_static_folder()
    progress_folder.mkdir(parents=True, exist_ok=True)

    safe_job_id = sanitize_filename_text(job_id)
    json_filename = f"{safe_job_id}_drawing_path.json"

    destination_path = progress_folder / json_filename

    if source_path.resolve() != destination_path.resolve():
        shutil.copy2(source_path, destination_path)

    json_url = (
        f"{get_public_base_url()}/"
        f"{get_progress_url_prefix()}/"
        f"{json_filename}"
    )

    print("=" * 70)
    print("[Robot Adapter] 드로잉 경로 JSON 복사 완료")
    print(f"[Robot Adapter] source : {source_path}")
    print(f"[Robot Adapter] saved  : {destination_path}")
    print(f"[Robot Adapter] url    : {json_url}")
    print("=" * 70)

    return {
        "drawing_path_json_path": str(destination_path),
        "drawing_path_json_url": json_url,
        "drawing_path_json_filename": json_filename,
    }


def build_multipart_form_data(fields, file_field_name, file_path):
    """
    requests 패키지 없이 multipart/form-data body를 만든다.
    """

    file_path = Path(file_path)
    boundary = f"----ChatGPTFormBoundary{int(time.time() * 1000)}"
    line_break = b"\r\n"

    body_parts = []

    for key, value in fields.items():
        body_parts.append(f"--{boundary}".encode("utf-8"))
        body_parts.append(
            f'Content-Disposition: form-data; name="{key}"'.encode("utf-8")
        )
        body_parts.append(b"")
        body_parts.append(str(value).encode("utf-8"))

    filename = file_path.name
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

    body_parts.append(f"--{boundary}".encode("utf-8"))
    body_parts.append(
        (
            f'Content-Disposition: form-data; '
            f'name="{file_field_name}"; filename="{filename}"'
        ).encode("utf-8")
    )
    body_parts.append(f"Content-Type: {content_type}".encode("utf-8"))
    body_parts.append(b"")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body_parts.append(file_bytes)
    body_parts.append(f"--{boundary}--".encode("utf-8"))
    body_parts.append(b"")

    body = line_break.join(body_parts)

    content_type_header = f"multipart/form-data; boundary={boundary}"

    return body, content_type_header


def upload_converted_image_to_server(
    job_id,
    source_image_path,
    suffix="preview_before_robot",
):
    """
    로봇 PC에서 생성된 preview 이미지를 네 PC Flask 서버로 업로드한다.

    서버 API:
    POST {PUBLIC_BASE_URL}/api/upload-converted-image

    반환:
    {
        "ok": True,
        "convertedImageUrl": "...",
        ...
    }
    """

    source_path = ensure_file_exists(
        source_image_path,
        "서버 업로드용 preview 이미지",
    )

    upload_url = get_converted_upload_api_url()

    fields = {
        "jobId": job_id,
        "suffix": suffix,
    }

    body, content_type_header = build_multipart_form_data(
        fields=fields,
        file_field_name="file",
        file_path=source_path,
    )

    request_obj = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type_header,
            "Content-Length": str(len(body)),
        },
    )

    print("=" * 70)
    print("[Robot Adapter][Upload] preview 이미지 서버 업로드 시작")
    print(f"[Robot Adapter][Upload] upload_url : {upload_url}")
    print(f"[Robot Adapter][Upload] file       : {source_path}")
    print(f"[Robot Adapter][Upload] job_id     : {job_id}")
    print(f"[Robot Adapter][Upload] suffix     : {suffix}")
    print("=" * 70)

    try:
        with urllib.request.urlopen(
            request_obj,
            timeout=PREVIEW_UPLOAD_TIMEOUT_SEC,
        ) as response:
            response_body = response.read().decode("utf-8", errors="replace")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"preview 이미지 서버 업로드 HTTP 오류: "
            f"status={e.code}, body={error_body}"
        ) from e

    except Exception as e:
        raise RuntimeError(
            f"preview 이미지 서버 업로드 실패: {e}"
        ) from e

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"preview 이미지 업로드 응답 JSON 파싱 실패: {response_body}"
        ) from e

    if not data.get("ok"):
        raise RuntimeError(
            f"preview 이미지 서버 업로드 실패 응답: {data}"
        )

    converted_image_url = data.get("convertedImageUrl", "")

    if not converted_image_url:
        raise RuntimeError(
            f"preview 이미지 업로드 응답에 convertedImageUrl이 없습니다: {data}"
        )

    print("=" * 70)
    print("[Robot Adapter][Upload] preview 이미지 서버 업로드 완료")
    print(f"[Robot Adapter][Upload] convertedImageUrl: {converted_image_url}")
    print("=" * 70)

    return data


def prepare_preview_image_for_dashboard(
    job_id,
    source_image_path,
    suffix="preview_before_robot",
):
    """
    1. 로봇 PC 로컬에 preview 이미지 보관
    2. 네 PC Flask 서버로 preview 이미지 업로드
    3. 업로드 실패 시 기본값은 로봇 작업은 계속 진행
    """

    local_result = copy_image_to_local_converted(
        job_id=job_id,
        source_image_path=source_image_path,
        suffix=suffix,
    )

    upload_result = None
    upload_error = ""

    try:
        upload_result = upload_converted_image_to_server(
            job_id=job_id,
            source_image_path=source_image_path,
            suffix=suffix,
        )

    except Exception as e:
        upload_error = str(e)

        print("=" * 70)
        print("[Robot Adapter][Upload][WARN] preview 이미지 서버 업로드 실패")
        print(f"[Robot Adapter][Upload][WARN] {upload_error}")
        print("[Robot Adapter][Upload][WARN] 로봇 작업은 계속 진행합니다.")
        print("=" * 70)

        if REQUIRE_PREVIEW_UPLOAD:
            raise

    if upload_result:
        return {
            "converted_image_path": upload_result.get(
                "convertedImagePath",
                local_result["converted_image_path"],
            ),
            "converted_image_url": upload_result.get(
                "convertedImageUrl",
                local_result["converted_image_url"],
            ),
            "local_converted_image_path": local_result["converted_image_path"],
            "local_converted_image_url": local_result["converted_image_url"],
            "upload_ok": True,
            "upload_error": "",
            "server_response": upload_result,
        }

    return {
        "converted_image_path": local_result["converted_image_path"],
        "converted_image_url": local_result["converted_image_url"],
        "local_converted_image_path": local_result["converted_image_path"],
        "local_converted_image_url": local_result["converted_image_url"],
        "upload_ok": False,
        "upload_error": upload_error,
        "server_response": {},
    }


def upload_progress_json_to_server(
    job_id,
    source_json_path,
    suffix="drawing_path",
):
    """
    로봇 PC에서 생성된 preview_robot_path.json을 네 PC Flask 서버로 업로드한다.

    서버 API:
    POST {PUBLIC_BASE_URL}/api/upload-progress-json

    반환:
    {
        "ok": True,
        "drawingPathJsonUrl": "...",
        ...
    }
    """

    source_path = ensure_file_exists(
        source_json_path,
        "서버 업로드용 preview 경로 JSON",
    )

    upload_url = get_progress_json_upload_api_url()

    fields = {
        "jobId": job_id,
        "suffix": suffix,
    }

    body, content_type_header = build_multipart_form_data(
        fields=fields,
        file_field_name="file",
        file_path=source_path,
    )

    request_obj = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type_header,
            "Content-Length": str(len(body)),
        },
    )

    print("=" * 70)
    print("[Robot Adapter][ProgressJsonUpload] 드로잉 경로 JSON 서버 업로드 시작")
    print(f"[Robot Adapter][ProgressJsonUpload] upload_url : {upload_url}")
    print(f"[Robot Adapter][ProgressJsonUpload] file       : {source_path}")
    print(f"[Robot Adapter][ProgressJsonUpload] job_id     : {job_id}")
    print(f"[Robot Adapter][ProgressJsonUpload] suffix     : {suffix}")
    print("=" * 70)

    try:
        with urllib.request.urlopen(
            request_obj,
            timeout=PREVIEW_UPLOAD_TIMEOUT_SEC,
        ) as response:
            response_body = response.read().decode("utf-8", errors="replace")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"드로잉 경로 JSON 서버 업로드 HTTP 오류: "
            f"status={e.code}, body={error_body}"
        ) from e

    except Exception as e:
        raise RuntimeError(
            f"드로잉 경로 JSON 서버 업로드 실패: {e}"
        ) from e

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"드로잉 경로 JSON 업로드 응답 JSON 파싱 실패: {response_body}"
        ) from e

    if not data.get("ok"):
        raise RuntimeError(
            f"드로잉 경로 JSON 서버 업로드 실패 응답: {data}"
        )

    drawing_path_json_url = data.get("drawingPathJsonUrl", "")

    if not drawing_path_json_url:
        raise RuntimeError(
            f"드로잉 경로 JSON 업로드 응답에 drawingPathJsonUrl이 없습니다: {data}"
        )

    print("=" * 70)
    print("[Robot Adapter][ProgressJsonUpload] 드로잉 경로 JSON 서버 업로드 완료")
    print(f"[Robot Adapter][ProgressJsonUpload] drawingPathJsonUrl: {drawing_path_json_url}")
    print("=" * 70)

    return data


def prepare_progress_json_for_dashboard(
    job_id,
    source_json_path,
    local_json_path="",
    local_json_url="",
    suffix="drawing_path",
):
    """
    preview_main.py가 만든 preview_robot_path.json을 웹 서버로 업로드한다.

    성공하면 서버 static/uploads/progress 기준 URL을 반환한다.
    실패하면 local_json_path/local_json_url을 fallback으로 반환하지만,
    서버 PC와 로봇 PC가 분리되어 있으면 fallback URL은 브라우저에서 안 보일 수 있다.
    """

    upload_result = None
    upload_error = ""

    try:
        upload_result = upload_progress_json_to_server(
            job_id=job_id,
            source_json_path=source_json_path,
            suffix=suffix,
        )

    except Exception as e:
        upload_error = str(e)

        print("=" * 70)
        print("[Robot Adapter][ProgressJsonUpload][WARN] 드로잉 경로 JSON 서버 업로드 실패")
        print(f"[Robot Adapter][ProgressJsonUpload][WARN] {upload_error}")
        print("[Robot Adapter][ProgressJsonUpload][WARN] 로컬 JSON URL을 fallback으로 사용합니다.")
        print("=" * 70)

    if upload_result:
        return {
            "drawing_path_json_path": upload_result.get(
                "drawingPathJsonPath",
                local_json_path,
            ),
            "drawing_path_json_url": upload_result.get(
                "drawingPathJsonUrl",
                local_json_url,
            ),
            "drawing_path_json_filename": upload_result.get(
                "drawingPathJsonFilename",
                "",
            ),
            "progress_json_upload_ok": True,
            "progress_json_upload_error": "",
            "server_response": upload_result,
        }

    return {
        "drawing_path_json_path": local_json_path,
        "drawing_path_json_url": local_json_url,
        "drawing_path_json_filename": "",
        "progress_json_upload_ok": False,
        "progress_json_upload_error": upload_error,
        "server_response": {},
    }


# ============================================================
# 펜 잡기 / 펜 반납 실행
# ============================================================

def run_pen_tool_script(
    action,
    job_id,
    progress_callback=None,
):
    """
    pen_grip.py 또는 pen_release.py를 관리형 subprocess로 실행한다.

    action:
    - grip
    - release
    """

    clean_action = str(action or "").strip().lower()

    if clean_action == "grip":
        script_path = PEN_GRIP_FILE
        label = "pen_grip.py"
        status_text_running = "펜 잡기 동작 실행 중"
        status_text_done = "펜 잡기 완료"
        progress_running = 84
        progress_done = 85
        step = "5 / 6"

    elif clean_action == "release":
        script_path = PEN_RELEASE_FILE
        label = "pen_release.py"
        status_text_running = "펜 반납 동작 실행 중"
        status_text_done = "펜 반납 완료"
        progress_running = 96
        progress_done = 97
        step = "6 / 6"

    else:
        raise ValueError(
            f"지원하지 않는 펜 동작입니다: {action}. "
            "grip 또는 release를 사용하세요."
        )

    script_file = ensure_file_exists(script_path, label)

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text=status_text_running,
        step=step,
        progress=progress_running,
        extra_data={
            "penToolAction": clean_action,
            "penToolScript": str(script_file),
        },
    )

    command = [
        PEN_TOOL_PYTHON,
        str(script_file),
    ]

    print("=" * 70)
    print(f"[Robot Adapter][Pen] {label} 실행")
    print(f"[Robot Adapter][Pen] action : {clean_action}")
    print(f"[Robot Adapter][Pen] python : {PEN_TOOL_PYTHON}")
    print(f"[Robot Adapter][Pen] script : {script_file}")
    print(f"[Robot Adapter][Pen] cwd    : {D3PROJECT_DIR}")
    print(f"[Robot Adapter][Pen] command: {' '.join(command)}")
    print("[Robot Adapter][Pen] 주의: 실제 로봇이 움직입니다.")
    print("=" * 70)

    try:
        result = run_managed_process(
            command=command,
            label=f"{label}:{job_id}",
            cwd=str(D3PROJECT_DIR),
            timeout=PEN_TOOL_TIMEOUT_SEC,
            capture_output=False,
            text=True,
        )

    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"{label} 실행 시간이 초과되었습니다. "
            f"timeout={PEN_TOOL_TIMEOUT_SEC}초"
        ) from e

    if result.returncode != 0:
        raise RuntimeError(
            make_process_terminated_error(label, result.returncode)
        )

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text=status_text_done,
        step=step,
        progress=progress_done,
        extra_data={
            "penToolAction": clean_action,
            "penToolScript": str(script_file),
        },
    )

    print("=" * 70)
    print(f"[Robot Adapter][Pen] {label} 완료")
    print("=" * 70)

    return {
        "enabled": True,
        "action": clean_action,
        "script": str(script_file),
    }


# ============================================================
# preview_main.py 실행
# ============================================================

def run_preview_main(
    job_id,
    image_path,
    progress_callback=None,
):
    safe_job_id = sanitize_filename_text(job_id)

    source_image_path = ensure_file_exists(
        image_path,
        "입력 이미지",
    )

    algorithm_dir = ensure_dir_exists(
        ALGORITHM_DIR,
        "알고리즘",
    )

    preview_main_file = ensure_file_exists(
        PREVIEW_MAIN_FILE,
        "preview_main.py",
    )

    PREVIEW_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    output_dir = PREVIEW_OUTPUT_ROOT / f"{safe_job_id}_preview"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text="이미지 preview 알고리즘 준비 중",
        step="3 / 6",
        progress=45,
    )

    command = [
        PREVIEW_PYTHON,
        str(preview_main_file),
        "--image",
        str(source_image_path.resolve()),
        "--output",
        str(output_dir.resolve()),
    ]

    print("=" * 70)
    print("[Robot Adapter] preview_main.py 실행")
    print(f"[Robot Adapter] job_id        : {job_id}")
    print(f"[Robot Adapter] algorithm_dir : {algorithm_dir}")
    print(f"[Robot Adapter] preview_main  : {preview_main_file}")
    print(f"[Robot Adapter] image_path    : {source_image_path}")
    print(f"[Robot Adapter] output_dir    : {output_dir}")
    print(f"[Robot Adapter] command       : {' '.join(command)}")
    print("[Robot Adapter] 실제 로봇은 움직이지 않습니다.")
    print("=" * 70)

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text="이미지 preview 변환 중",
        step="4 / 6",
        progress=60,
    )

    try:
        result = run_managed_process(
            command=command,
            label=f"preview_main.py:{job_id}",
            cwd=str(algorithm_dir),
            timeout=PREVIEW_TIMEOUT_SEC,
            capture_output=True,
            text=True,
        )

    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"preview_main.py 실행 시간이 초과되었습니다. "
            f"timeout={PREVIEW_TIMEOUT_SEC}초"
        ) from e

    print_subprocess_output(result)

    if result.returncode != 0:
        raise RuntimeError(
            make_process_terminated_error("preview_main.py", result.returncode)
        )

    result_image_path = find_preview_result_image(output_dir)
    result_json_path = output_dir / "preview_robot_path.json"

    if not result_json_path.exists():
        raise FileNotFoundError(
            f"preview 좌표 JSON을 찾을 수 없습니다: {result_json_path}"
        )

    drawing_path_static = copy_preview_json_to_progress_static(
        job_id=job_id,
        source_json_path=result_json_path,
    )

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text="preview 경로 생성 완료",
        step="5 / 6",
        progress=80,
        extra_data={
            "convertedImagePath": str(result_image_path),
            "previewJsonPath": str(result_json_path),
            "drawingPathJsonPath": drawing_path_static["drawing_path_json_path"],
            "drawingPathJsonUrl": drawing_path_static["drawing_path_json_url"],
        },
    )

    print("=" * 70)
    print("[Robot Adapter] preview 결과 확인 완료")
    print(f"[Robot Adapter] result_image_path : {result_image_path}")
    print(f"[Robot Adapter] result_json_path  : {result_json_path}")
    print("=" * 70)

    return {
        "result_image_path": str(result_image_path),
        "result_json_path": str(result_json_path),
        "drawing_path_json_path": drawing_path_static["drawing_path_json_path"],
        "drawing_path_json_url": drawing_path_static["drawing_path_json_url"],
        "output_dir": str(output_dir),
    }


# ============================================================
# main.py 실제 로봇 실행
# ============================================================

def backup_current_test_image(job_output_dir):
    if not ALGORITHM_INPUT_IMAGE.exists():
        return ""

    backup_path = job_output_dir / "original_test_backup.png"
    shutil.copy2(ALGORITHM_INPUT_IMAGE, backup_path)

    print(f"[Robot Adapter][Robot] 기존 test.png 백업: {backup_path}")

    return str(backup_path)


def restore_test_image(backup_path):
    if not backup_path:
        return

    backup_file = Path(backup_path)

    if not backup_file.exists():
        return

    shutil.copy2(backup_file, ALGORITHM_INPUT_IMAGE)

    print(f"[Robot Adapter][Robot] test.png 원복 완료: {ALGORITHM_INPUT_IMAGE}")


def copy_input_image_to_algorithm(image_path):
    source_image_path = ensure_file_exists(
        image_path,
        "입력 이미지",
    )

    ALGORITHM_INPUT_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_image_path, ALGORITHM_INPUT_IMAGE)

    print("=" * 70)
    print("[Robot Adapter][Robot] 입력 이미지 복사 완료")
    print(f"[Robot Adapter][Robot] source : {source_image_path}")
    print(f"[Robot Adapter][Robot] target : {ALGORITHM_INPUT_IMAGE}")
    print("=" * 70)


def run_robot_main(
    job_id,
    image_path,
    progress_callback=None,
):
    """
    알고리즘 팀 원본 main.py를 관리형 subprocess로 실행한다.

    추가:
    - main.py 실행 전 progress JSON 파일 경로를 환경변수로 넘긴다.
    - main.py / ik_solver.py가 기록하는 progress JSON을 감시한다.
    - 1% 단위 실제 드로잉 진행률을 Firebase current_job에 반영한다.
    """

    safe_job_id = sanitize_filename_text(job_id)

    algorithm_dir = ensure_dir_exists(
        ALGORITHM_DIR,
        "알고리즘",
    )

    robot_main_file = ensure_file_exists(
        ROBOT_MAIN_FILE,
        "main.py",
    )

    source_image_path = ensure_file_exists(
        image_path,
        "입력 이미지",
    )

    PREVIEW_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    job_output_dir = PREVIEW_OUTPUT_ROOT / f"{safe_job_id}_robot"
    job_output_dir.mkdir(parents=True, exist_ok=True)

    backup_path = ""
    result = None

    drawing_progress_file = make_drawing_progress_file_path(job_id)

    # 이전 작업 progress 파일이 남아 있으면 삭제
    if drawing_progress_file.exists():
        try:
            drawing_progress_file.unlink()
        except Exception as e:
            print(
                f"[Robot Adapter][DrawingProgress][WARN] "
                f"이전 progress 파일 삭제 실패: {e}",
                flush=True,
            )

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text="실제 로봇 실행 준비 중",
        step="5 / 6",
        progress=86,
        extra_data={
            "drawingPhase": "preparing",
            "drawingPointIndex": 0,
            "drawingTotalPoints": 0,
            "drawingProgressPercent": 0,
        },
    )

    print("=" * 70)
    print("[Robot Adapter][Robot] 실제 로봇 실행 모드")
    print(f"[Robot Adapter][Robot] job_id        : {job_id}")
    print(f"[Robot Adapter][Robot] algorithm_dir : {algorithm_dir}")
    print(f"[Robot Adapter][Robot] main.py       : {robot_main_file}")
    print(f"[Robot Adapter][Robot] input image   : {source_image_path}")
    print(f"[Robot Adapter][Robot] test.png      : {ALGORITHM_INPUT_IMAGE}")
    print(f"[Robot Adapter][Robot] progress file : {drawing_progress_file}")
    print("[Robot Adapter][Robot] 주의: 실제 로봇이 움직입니다.")
    print("=" * 70)

    progress_stop_event = threading.Event()
    progress_monitor_thread = None

    env_keys = [
        "COBOT1_DRAWING_JOB_ID",
        "COBOT1_DRAWING_PROGRESS_FILE",
    ]

    env_backup = {
        key: os.environ.get(key)
        for key in env_keys
    }

    try:
        backup_path = backup_current_test_image(job_output_dir)

        copy_input_image_to_algorithm(source_image_path)

        report_progress(
            progress_callback,
            job_id=job_id,
            status_text="실제 로봇 드로잉 중",
            step="6 / 6",
            progress=90,
            extra_data={
                "drawingPhase": "starting",
                "drawingPointIndex": 0,
                "drawingTotalPoints": 0,
                "drawingProgressPercent": 0,
            },
        )

        command = [
            ROBOT_PYTHON,
            str(robot_main_file),
        ]

        print("=" * 70)
        print("[Robot Adapter][Robot] main.py 실행")
        print(f"[Robot Adapter][Robot] command: {' '.join(command)}")
        print(f"[Robot Adapter][Robot] env COBOT1_DRAWING_JOB_ID       : {job_id}")
        print(f"[Robot Adapter][Robot] env COBOT1_DRAWING_PROGRESS_FILE: {drawing_progress_file}")
        print("=" * 70)

        # run_managed_process가 별도 env 인자를 받는지 확실하지 않으므로,
        # 현재 process 환경변수에 잠깐 세팅한다.
        # subprocess는 기본적으로 부모 process 환경변수를 상속한다.
        os.environ["COBOT1_DRAWING_JOB_ID"] = str(job_id)
        os.environ["COBOT1_DRAWING_PROGRESS_FILE"] = str(drawing_progress_file)

        progress_monitor_thread = start_drawing_progress_monitor(
            progress_file=drawing_progress_file,
            job_id=job_id,
            progress_callback=progress_callback,
            stop_event=progress_stop_event,
        )

        result = run_managed_process(
            command=command,
            label=f"main.py:{job_id}",
            cwd=str(algorithm_dir),
            timeout=ROBOT_TIMEOUT_SEC,
            capture_output=False,
            text=True,
        )


        if result.returncode != 0:
            raise RuntimeError(
                make_process_terminated_error("main.py 실제 로봇", result.returncode)
            )

    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"main.py 실제 로봇 실행 시간이 초과되었습니다. "
            f"timeout={ROBOT_TIMEOUT_SEC}초"
        ) from e

    finally:
        progress_stop_event.set()

        if progress_monitor_thread is not None:
            progress_monitor_thread.join(timeout=2.0)

        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        if RESTORE_TEST_IMAGE:
            restore_test_image(backup_path)

    result_image_path = find_algorithm_debug_image()

    # 혹시 monitor가 마지막 done을 놓쳤을 경우 한 번 더 보정
    final_payload = read_drawing_progress_payload(drawing_progress_file)

    if final_payload:
        publish_drawing_progress_payload(
            progress_callback=progress_callback,
            job_id=job_id,
            payload=final_payload,
        )

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text="실제 로봇 드로잉 완료",
        step="6 / 6",
        progress=95,
        extra_data={
            "robotExecuted": True,
            "algorithmResultImage": str(result_image_path) if result_image_path else "",
            "drawingPhase": "done",
            "drawingProgressFile": str(drawing_progress_file),
        },
    )

    print("=" * 70)
    print("[Robot Adapter][Robot] main.py 실행 완료")
    print(f"[Robot Adapter][Robot] result_image_path     : {result_image_path}")
    print(f"[Robot Adapter][Robot] drawing_progress_file: {drawing_progress_file}")
    print("=" * 70)

    return {
        "result_image_path": str(result_image_path) if result_image_path else "",
        "output_dir": str(job_output_dir),
        "robotExecuted": True,
        "drawingProgressFile": str(drawing_progress_file),
    }

# ============================================================
# preview 후 서버 업로드 → 펜 잡기 → 실제 드로잉 → 펜 반납
# ============================================================

def run_preview_then_robot(
    job_id,
    image_path,
    option=None,
    request_text=None,
    progress_callback=None,
):
    print("=" * 70)
    print("[Robot Adapter] preview_then_robot 모드 시작")
    print("[Robot Adapter] 1단계: preview_main.py")
    print("[Robot Adapter] 2단계: preview 이미지 서버 업로드")
    print(f"[Robot Adapter] 3단계: {PREVIEW_TO_ROBOT_DELAY_SEC}초 대기")
    print("[Robot Adapter] 4단계: pen_grip.py 실행")
    print("[Robot Adapter] 5단계: main.py 실제 로봇 실행")
    print("[Robot Adapter] 6단계: pen_release.py 실행")
    print("=" * 70)

    preview_result = run_preview_main(
        job_id=job_id,
        image_path=image_path,
        progress_callback=progress_callback,
    )

    preview_static = prepare_preview_image_for_dashboard(
        job_id=job_id,
        source_image_path=preview_result["result_image_path"],
        suffix="preview_before_robot",
    )

    progress_json_static = prepare_progress_json_for_dashboard(
        job_id=job_id,
        source_json_path=preview_result["result_json_path"],
        local_json_path=preview_result.get("drawing_path_json_path", ""),
        local_json_url=preview_result.get("drawing_path_json_url", ""),
        suffix="drawing_path",
    )

    upload_status_text = "preview 이미지 표시 완료"

    if not preview_static.get("upload_ok"):
        upload_status_text = "preview 생성 완료 - 서버 업로드 실패, 로봇 작업 계속 진행"

    report_progress(
        progress_callback,
        job_id=job_id,
        status_text=(
            f"{upload_status_text} - "
            f"{PREVIEW_TO_ROBOT_DELAY_SEC}초 후 펜 잡기 시작"
        ),
        step="5 / 6",
        progress=82,
        extra_data={
            "convertedImagePath": preview_static["converted_image_path"],
            "convertedImageUrl": preview_static["converted_image_url"],
            "previewJsonPath": preview_result["result_json_path"],
            "drawingPathJsonPath": progress_json_static["drawing_path_json_path"],
            "drawingPathJsonUrl": progress_json_static["drawing_path_json_url"],
        },
    )

    for remaining in range(PREVIEW_TO_ROBOT_DELAY_SEC, 0, -1):
        print(f"[Robot Adapter] 펜 잡기 시작까지 {remaining}초")

        report_progress(
            progress_callback,
            job_id=job_id,
            status_text=f"preview 확인 중 - {remaining}초 후 펜 잡기 시작",
            step="5 / 6",
            progress=82,
            extra_data={
                "convertedImagePath": preview_static["converted_image_path"],
                "convertedImageUrl": preview_static["converted_image_url"],
                "previewJsonPath": preview_result["result_json_path"],
                "drawingPathJsonPath": progress_json_static["drawing_path_json_path"],
                "drawingPathJsonUrl": progress_json_static["drawing_path_json_url"],
                "progressJsonUploadOk": progress_json_static.get("progress_json_upload_ok", False),
                "progressJsonUploadError": progress_json_static.get("progress_json_upload_error", ""),
            },
        )

        time.sleep(1)

    print("[Robot Adapter] preview 대기 완료. 펜 잡기 동작으로 전환합니다.")
    time.sleep(3)

    pen_grip_result = run_pen_tool_script(
        action="grip",
        job_id=job_id,
        progress_callback=progress_callback,
    )

    print("[Robot Adapter] 펜 잡기 완료. 실제 로봇 드로잉으로 전환합니다.")

    robot_result = run_robot_main(
        job_id=job_id,
        image_path=image_path,
        progress_callback=progress_callback,
    )

    print("[Robot Adapter] 실제 드로잉 완료. 펜 반납 동작으로 전환합니다.")
    time.sleep(3)

    pen_release_result = run_pen_tool_script(
        action="release",
        job_id=job_id,
        progress_callback=progress_callback,
    )

    final_image_path = (
        robot_result.get("result_image_path")
        or preview_static["converted_image_path"]
    )

    return make_success_result(
        message="preview 후 서버 업로드, 펜 잡기, 실제 로봇 드로잉, 펜 반납 완료",
        converted_image_path=final_image_path,
        converted_image_url=preview_static["converted_image_url"],
        extra={
            "mode": "preview_then_robot",
            "robotExecuted": True,
            "penToolSequenceEnabled": True,
            "penGripResult": pen_grip_result,
            "penReleaseResult": pen_release_result,
            "previewImagePath": preview_result["result_image_path"],
            "previewJsonPath": preview_result["result_json_path"],
            "drawingPathJsonPath": progress_json_static["drawing_path_json_path"],
            "drawingPathJsonUrl": progress_json_static["drawing_path_json_url"],
            "previewStaticPath": preview_static["converted_image_path"],
            "previewStaticUrl": preview_static["converted_image_url"],
            "previewUploadOk": preview_static.get("upload_ok", False),
            "previewUploadError": preview_static.get("upload_error", ""),
            "robotOutputDir": robot_result["output_dir"],
            "option": option,
            "requestText": request_text,
        },
    )


# ============================================================
# robot_job_runner.py가 호출하는 함수
# ============================================================

def run_doosan_drawing_job(
    job_id,
    image_path,
    option=None,
    request_text=None,
    progress_callback=None,
):
    if not job_id:
        raise ValueError("job_id가 없습니다.")

    if not image_path:
        raise ValueError("image_path가 없습니다.")

    mode = ADAPTER_MODE

    if mode not in {"preview", "robot", "preview_then_robot"}:
        raise ValueError(
            f"지원하지 않는 COBOT1_ADAPTER_MODE입니다: {mode}. "
            "preview, robot, preview_then_robot 중 하나를 사용하세요."
        )

    print("=" * 70)
    print("[Robot Adapter] Doosan M0609 adapter 시작")
    print(f"[Robot Adapter] job_id       : {job_id}")
    print(f"[Robot Adapter] image_path   : {image_path}")
    print(f"[Robot Adapter] option       : {option}")
    print(f"[Robot Adapter] request_text : {request_text}")
    print(f"[Robot Adapter] adapter_mode : {mode}")
    print(f"[Robot Adapter] algorithm_dir: {ALGORITHM_DIR}")
    print(f"[Robot Adapter] preview_main : {PREVIEW_MAIN_FILE}")
    print(f"[Robot Adapter] robot_main   : {ROBOT_MAIN_FILE}")
    print(f"[Robot Adapter] pen_grip     : {PEN_GRIP_FILE}")
    print(f"[Robot Adapter] pen_release  : {PEN_RELEASE_FILE}")
    print(f"[Robot Adapter] upload api   : {get_converted_upload_api_url()}")
    print(f"[Robot Adapter] json upload  : {get_progress_json_upload_api_url()}")
    print("=" * 70)

    if mode == "preview":
        preview_result = run_preview_main(
            job_id=job_id,
            image_path=image_path,
            progress_callback=progress_callback,
        )

        preview_static = prepare_preview_image_for_dashboard(
            job_id=job_id,
            source_image_path=preview_result["result_image_path"],
            suffix="preview_only",
        )

        progress_json_static = prepare_progress_json_for_dashboard(
            job_id=job_id,
            source_json_path=preview_result["result_json_path"],
            local_json_path=preview_result.get("drawing_path_json_path", ""),
            local_json_url=preview_result.get("drawing_path_json_url", ""),
            suffix="drawing_path",
        )

        report_progress(
            progress_callback,
            job_id=job_id,
            status_text="preview 변환 이미지 생성 완료",
            step="5 / 6",
            progress=90,
            extra_data={
                "convertedImagePath": preview_static["converted_image_path"],
                "convertedImageUrl": preview_static["converted_image_url"],
                "previewJsonPath": preview_result["result_json_path"],
                "drawingPathJsonPath": progress_json_static["drawing_path_json_path"],
                "drawingPathJsonUrl": progress_json_static["drawing_path_json_url"],
                "progressJsonUploadOk": progress_json_static.get("progress_json_upload_ok", False),
                "progressJsonUploadError": progress_json_static.get("progress_json_upload_error", ""),
            },
        )

        return make_success_result(
            message="preview 이미지 처리 완료",
            converted_image_path=preview_static["converted_image_path"],
            converted_image_url=preview_static["converted_image_url"],
            extra={
                "mode": "preview_only",
                "robotExecuted": False,
                "previewJsonPath": preview_result["result_json_path"],
                "drawingPathJsonPath": progress_json_static["drawing_path_json_path"],
                "drawingPathJsonUrl": progress_json_static["drawing_path_json_url"],
                "progressJsonUploadOk": progress_json_static.get("progress_json_upload_ok", False),
                "progressJsonUploadError": progress_json_static.get("progress_json_upload_error", ""),
                "previewOutputDir": preview_result["output_dir"],
                "previewUploadOk": preview_static.get("upload_ok", False),
                "previewUploadError": preview_static.get("upload_error", ""),
                "option": option,
                "requestText": request_text,
            },
        )

    if mode == "robot":
        robot_result = run_robot_main(
            job_id=job_id,
            image_path=image_path,
            progress_callback=progress_callback,
            )

        return make_success_result(
            message="실제 로봇 드로잉 완료",
            converted_image_path=robot_result["result_image_path"],
            converted_image_url="",
            extra={
                "mode": "robot",
                "robotExecuted": True,
                "robotOutputDir": robot_result["output_dir"],
                "option": option,
                "requestText": request_text,
            },
        )

    return run_preview_then_robot(
        job_id=job_id,
        image_path=image_path,
        option=option,
        request_text=request_text,
        progress_callback=progress_callback,
    )