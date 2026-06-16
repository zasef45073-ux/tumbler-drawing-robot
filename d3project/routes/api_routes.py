from pathlib import Path
import re
import time

from flask import Blueprint, current_app, jsonify, request
from firebase_admin import db
from werkzeug.utils import secure_filename

from services import process_flow as pf
from services.firebase_service import (
    get_customer_request_status,
    get_dashboard_data,
    get_robot_status,
    request_start_job,
)


api_bp = Blueprint("api", __name__, url_prefix="/api")


# ============================================================
# 공통 유틸
# ============================================================

def now_text():
    """
    Firebase에 기록할 현재 시간 문자열
    """

    return time.strftime("%Y-%m-%d %H:%M:%S")


def sanitize_filename_text(value):
    """
    파일명에 쓰기 위험한 문자를 안전한 문자로 바꾼다.
    """

    clean_value = str(value or "").strip()

    if not clean_value:
        return "unknown"

    return re.sub(r"[^A-Za-z0-9_.-]", "_", clean_value)


def normalize_request_id_input(value):
    """
    고객 접수번호 정리

    고객 상태 상세 페이지에서 실시간 조회 API를 호출할 때 사용한다.
    - 앞뒤 공백 제거
    - 소문자로 들어와도 대문자로 변환
    """

    return str(value or "").strip().upper()


def get_file_extension(filename, default_extension="png"):
    """
    업로드 파일명에서 확장자를 추출한다.
    """

    clean_filename = str(filename or "").strip()

    if "." not in clean_filename:
        return default_extension

    extension = clean_filename.rsplit(".", 1)[1].lower().strip()

    if not extension:
        return default_extension

    return extension


def is_allowed_image_extension(extension):
    """
    config.py의 ALLOWED_IMAGE_EXTENSIONS 기준으로 이미지 확장자를 검사한다.
    """

    allowed_extensions = current_app.config.get(
        "ALLOWED_IMAGE_EXTENSIONS",
        {"png", "jpg", "jpeg", "webp", "gif"},
    )

    return extension.lower().strip(".") in allowed_extensions


def is_allowed_json_extension(extension):
    """
    progress path 업로드용 JSON 확장자 검사.
    """

    return str(extension or "").lower().strip(".") == "json"


def make_converted_image_url(filename):
    """
    저장된 변환 이미지 파일명을 브라우저 접근 URL로 변환한다.
    """

    public_base_url = str(
        current_app.config.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000")
    ).rstrip("/")

    converted_prefix = str(
        current_app.config.get(
            "CONVERTED_UPLOAD_URL_PREFIX",
            "/static/uploads/converted",
        )
    ).strip("/")

    return f"{public_base_url}/{converted_prefix}/{filename}"


def make_progress_json_url(filename):
    """
    저장된 드로잉 경로 JSON 파일명을 브라우저 접근 URL로 변환한다.

    저장 위치:
    static/uploads/progress

    반환 예:
    http://서버PC_IP:5000/static/uploads/progress/TMB-xxxx_drawing_path.json
    """

    public_base_url = str(
        current_app.config.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000")
    ).rstrip("/")

    progress_prefix = str(
        current_app.config.get(
            "PROGRESS_UPLOAD_URL_PREFIX",
            "/static/uploads/progress",
        )
    ).strip("/")

    return f"{public_base_url}/{progress_prefix}/{filename}"


def get_commands_path():
    """
    Firebase commands 경로 반환

    config.py에 COMMANDS_PATH가 있으면 그 값을 사용하고,
    없으면 기본값 commands를 사용한다.
    """

    return str(current_app.config.get("COMMANDS_PATH", "commands")).strip("/")


def get_current_job_path():
    """
    Firebase current_job 경로 반환.
    """

    return str(current_app.config.get("CURRENT_JOB_PATH", "current_job")).strip("/")


def get_requests_path():
    """
    Firebase requests 경로 반환.
    """

    return str(current_app.config.get("REQUESTS_PATH", "requests")).strip("/")


# ============================================================
# control action 유틸
# ============================================================

CONTROL_ACTION_STOP = "stop"
CONTROL_ACTION_PAUSE = "pause"
CONTROL_ACTION_RESUME = "resume"

VALID_CONTROL_ACTIONS = {
    CONTROL_ACTION_STOP,
    CONTROL_ACTION_PAUSE,
    CONTROL_ACTION_RESUME,
}

CONTROL_ACTION_LABEL_MAP = {
    CONTROL_ACTION_STOP: "작업 중지",
    CONTROL_ACTION_PAUSE: "일시정지",
    CONTROL_ACTION_RESUME: "다시 시작",
}

CONTROL_ACTION_STATUS_TEXT_MAP = {
    CONTROL_ACTION_STOP: "작업 중지 요청",
    CONTROL_ACTION_PAUSE: "일시정지 요청",
    CONTROL_ACTION_RESUME: "다시 시작 요청",
}

CONTROL_ACTION_DEFAULT_REASON_MAP = {
    CONTROL_ACTION_STOP: "관리자 작업 중지 요청",
    CONTROL_ACTION_PAUSE: "관리자 일시정지 요청",
    CONTROL_ACTION_RESUME: "관리자 다시 시작 요청",
}


def normalize_control_action(action):
    """
    관리자 제어 명령 action 정리

    지원값:
    - stop
    - pause
    - resume
    """

    clean_action = str(action or "").strip().lower()

    if clean_action in VALID_CONTROL_ACTIONS:
        return clean_action

    return ""


def write_control_command(
    job_id,
    action,
    requested_by="admin",
    reason="",
):
    """
    Firebase commands/control에 작업 제어 명령 저장

    저장 경로:
    /commands/control

    지원 action:
    - stop
    - pause
    - resume
    """

    commands_path = get_commands_path()
    requested_at = now_text()

    action_label = CONTROL_ACTION_LABEL_MAP.get(action, action)
    status_text = CONTROL_ACTION_STATUS_TEXT_MAP.get(action, "제어 요청")

    control_data = {
        "jobId": job_id,
        "action": action,
        "actionLabel": action_label,
        "status": "REQUESTED",
        "statusText": status_text,
        "requestedBy": requested_by,
        "requestedAt": requested_at,
        "reason": reason,
        "source": "admin_dashboard",
    }

    db.reference(f"{commands_path}/control").set(control_data)

    return control_data


# ============================================================
# 기존 API
# ============================================================

@api_bp.route("/robot-status")
def api_robot_status():
    """
    로봇 상태값 API

    반환 내용:
    - J1~J6
    - X, Y, Z, rX, rY, rZ
    - 로봇 연결 상태
    - 마지막 업데이트 시간
    """

    robot_status = get_robot_status(current_app.config)

    return jsonify({
        "ok": True,
        "robot_status": robot_status,
    })


@api_bp.route("/dashboard")
def api_dashboard():
    """
    관리자 대시보드 전체 데이터 API

    dashboard.js에서 주기적으로 호출해서 화면을 갱신함.
    """

    dashboard_data = get_dashboard_data(current_app.config)

    return jsonify({
        "ok": True,
        "data": dashboard_data,
    })


@api_bp.route("/status/<request_id>")
def api_customer_status(request_id):
    """
    고객 제작 상태 상세 실시간 조회 API

    사용 주소:
    GET /api/status/TMB-xxxx

    목적:
    - customer_status_detail.html에서 1초마다 호출
    - 새로고침 없이 고객 진행률/단계/이미지/상태 문구 갱신

    반환 예:
    {
        "ok": true,
        "requestStatus": {
            "id": "TMB-...",
            "status": "DRAWING",
            "statusText": "로봇 드로잉 중",
            "progress": 55,
            ...
        }
    }
    """

    clean_request_id = normalize_request_id_input(request_id)

    if not clean_request_id:
        return jsonify({
            "ok": False,
            "message": "접수번호가 없습니다.",
        }), 400

    request_status = get_customer_request_status(
        current_app.config,
        clean_request_id,
    )

    if request_status is None:
        return jsonify({
            "ok": False,
            "message": "해당 접수번호의 제작 요청을 찾을 수 없습니다.",
            "requestId": clean_request_id,
        }), 404

    return jsonify({
        "ok": True,
        "requestId": clean_request_id,
        "requestStatus": request_status,
        "data": request_status,
    })


@api_bp.route("/commands/start", methods=["POST"])
def api_start_job():
    """
    공정 시작 명령 API

    요청 예시:
    {
        "jobId": "TMB-20260504-001",
        "requestedBy": "admin",
        "commandType": "drawing"
    }

    commandType:
    - tumbler_place
    - drawing
    - glue
    - paper_attach
    - rolling_return

    Firebase 저장 위치:
    /commands/start
    """

    body = request.get_json(silent=True) or {}

    job_id = body.get("jobId")
    requested_by = body.get("requestedBy", "admin")

    command_type = (
        body.get("commandType")
        or body.get("command_type")
        or pf.COMMAND_TYPE_PAPER
    )

    command_type = pf.normalize_command_type(command_type)

    if not job_id:
        return jsonify({
            "ok": False,
            "message": "jobId가 없습니다.",
        }), 400

    if not command_type:
        return jsonify({
            "ok": False,
            "message": "지원하지 않는 commandType입니다.",
            "allowedCommandTypes": sorted(list(pf.VALID_COMMAND_TYPES)),
        }), 400

    command_definition = pf.get_command_definition(command_type)

    success = request_start_job(
        current_app.config,
        job_id=job_id,
        requested_by=requested_by,
        command_type=command_type,
    )

    if not success:
        return jsonify({
            "ok": False,
            "message": (
                "Firebase에 공정 시작 명령을 저장하지 못했습니다. "
                "현재 요청 상태에서 해당 공정을 시작할 수 없는 상태일 수 있습니다."
            ),
            "jobId": job_id,
            "commandType": command_type,
            "commandLabel": command_definition.get("label") if command_definition else "",
        }), 409

    return jsonify({
        "ok": True,
        "message": f"{command_definition['label']} 명령을 저장했습니다.",
        "jobId": job_id,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
    })


# ============================================================
# 관리자 → 로봇 PC 제어 명령 API
# ============================================================

@api_bp.route("/commands/control", methods=["POST"])
def api_control_command():
    """
    관리자 제어 명령 API

    지원 action:
    - stop
      현재 실행 중인 subprocess 종료 후 STOPPED 처리 요청.
      작업 완전 종료.

    - pause
      현재 실행 중인 subprocess 종료 후 PAUSED 처리 요청.
      나중에 resume 가능.

    - resume
      PAUSED 상태의 현재 공정을 다시 시작 요청.

    요청 예시:
    {
        "jobId": "TMB-20260504-001",
        "action": "pause",
        "requestedBy": "admin",
        "reason": "관리자 일시정지 요청"
    }

    Firebase 저장 위치:
    /commands/control

    주의:
    - 이 API는 제어 요청을 Firebase에 저장만 한다.
    - 실제 subprocess 종료, PAUSED/STOPPED/RESUME 처리는
      robot_command_listener.py에서 수행한다.
    """

    body = request.get_json(silent=True) or {}

    job_id = str(body.get("jobId") or body.get("job_id") or "").strip()
    raw_action = body.get("action") or body.get("controlAction") or ""
    action = normalize_control_action(raw_action)

    requested_by = str(body.get("requestedBy") or "admin").strip()

    default_reason = CONTROL_ACTION_DEFAULT_REASON_MAP.get(
        action,
        "관리자 제어 요청",
    )

    reason = str(body.get("reason") or default_reason).strip()

    if not job_id:
        return jsonify({
            "ok": False,
            "message": "jobId가 없습니다.",
        }), 400

    if not action:
        return jsonify({
            "ok": False,
            "message": "지원하지 않는 제어 명령입니다.",
            "allowedActions": sorted(list(VALID_CONTROL_ACTIONS)),
        }), 400

    try:
        control_data = write_control_command(
            job_id=job_id,
            action=action,
            requested_by=requested_by,
            reason=reason,
        )

    except Exception as e:
        return jsonify({
            "ok": False,
            "message": f"Firebase에 제어 명령을 저장하지 못했습니다: {e}",
            "jobId": job_id,
            "action": action,
        }), 500

    print("=" * 70)
    print("[API][Control] 작업 제어 명령 저장")
    print(f"[API][Control] job_id       : {job_id}")
    print(f"[API][Control] action       : {action}")
    print(f"[API][Control] requested_by : {requested_by}")
    print(f"[API][Control] reason       : {reason}")
    print("=" * 70)

    return jsonify({
        "ok": True,
        "message": f"{control_data['actionLabel']} 요청을 저장했습니다.",
        "control": control_data,
    })


# ============================================================
# 로봇 PC → 네 PC 서버 변환 이미지 업로드 API
# ============================================================

@api_bp.route("/upload-converted-image", methods=["POST"])
def api_upload_converted_image():
    """
    로봇 PC에서 생성한 preview/converted 이미지를
    네 PC Flask 서버의 static/uploads/converted 폴더로 업로드하는 API.

    사용 예:
    POST /api/upload-converted-image

    multipart/form-data:
    - file: 이미지 파일
    - jobId: TMB-...
    - suffix: preview_before_robot 또는 converted 등

    반환:
    {
        "ok": true,
        "convertedImagePath": "...",
        "convertedImageUrl": "http://서버PC_IP:5000/static/uploads/converted/..."
    }
    """

    uploaded_file = (
        request.files.get("file")
        or request.files.get("convertedImage")
        or request.files.get("image")
    )

    if uploaded_file is None:
        return jsonify({
            "ok": False,
            "message": "업로드된 이미지 파일이 없습니다. file 필드로 전송하세요.",
        }), 400

    original_filename = secure_filename(uploaded_file.filename or "")

    extension = get_file_extension(original_filename, default_extension="png")

    if not is_allowed_image_extension(extension):
        return jsonify({
            "ok": False,
            "message": f"허용되지 않는 이미지 확장자입니다: {extension}",
        }), 400

    job_id = request.form.get("jobId") or request.form.get("job_id") or "unknown"
    suffix = request.form.get("suffix") or "preview_from_robot"

    safe_job_id = sanitize_filename_text(job_id)
    safe_suffix = sanitize_filename_text(suffix)

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    converted_filename = f"{safe_job_id}_{safe_suffix}_{timestamp}.{extension}"

    converted_folder = Path(
        current_app.config.get(
            "CONVERTED_UPLOAD_FOLDER",
            Path(current_app.root_path) / "static" / "uploads" / "converted",
        )
    )

    converted_folder.mkdir(parents=True, exist_ok=True)

    save_path = converted_folder / converted_filename

    uploaded_file.save(str(save_path))

    converted_image_url = make_converted_image_url(converted_filename)

    print("=" * 70)
    print("[API][ConvertedUpload] 변환 이미지 업로드 완료")
    print(f"[API][ConvertedUpload] job_id : {job_id}")
    print(f"[API][ConvertedUpload] saved  : {save_path}")
    print(f"[API][ConvertedUpload] url    : {converted_image_url}")
    print("=" * 70)

    return jsonify({
        "ok": True,
        "message": "변환 이미지 업로드 완료",
        "jobId": job_id,
        "convertedFilename": converted_filename,
        "convertedImagePath": str(save_path),
        "convertedImageUrl": converted_image_url,
    })


# ============================================================
# 로봇 PC → 네 PC 서버 드로잉 경로 JSON 업로드 API
# ============================================================

@api_bp.route("/upload-progress-json", methods=["POST"])
def api_upload_progress_json():
    """
    로봇 PC에서 생성한 preview_robot_path.json을
    네 PC Flask 서버의 static/uploads/progress 폴더로 업로드하는 API.

    이 API가 필요한 이유:
    - preview_main.py는 로봇 PC에서 실행된다.
    - preview_robot_path.json도 로봇 PC 로컬에 생성된다.
    - 브라우저는 네 PC Flask 서버의 static 파일만 접근할 수 있다.
    - 따라서 JSON도 이미지처럼 서버로 업로드해야 dashboard canvas가 fetch할 수 있다.

    사용 예:
    POST /api/upload-progress-json

    multipart/form-data:
    - file: preview_robot_path.json
    - jobId: TMB-...
    - suffix: drawing_path 또는 preview_robot_path

    반환:
    {
        "ok": true,
        "drawingPathJsonPath": "...",
        "drawingPathJsonUrl": "http://서버PC_IP:5000/static/uploads/progress/..."
    }
    """

    uploaded_file = (
        request.files.get("file")
        or request.files.get("json")
        or request.files.get("progressJson")
        or request.files.get("drawingPathJson")
    )

    if uploaded_file is None:
        return jsonify({
            "ok": False,
            "message": "업로드된 JSON 파일이 없습니다. file 필드로 전송하세요.",
        }), 400

    original_filename = secure_filename(uploaded_file.filename or "")
    extension = get_file_extension(original_filename, default_extension="json")

    if not is_allowed_json_extension(extension):
        return jsonify({
            "ok": False,
            "message": f"허용되지 않는 JSON 확장자입니다: {extension}",
        }), 400

    job_id = request.form.get("jobId") or request.form.get("job_id") or "unknown"
    suffix = request.form.get("suffix") or "drawing_path"

    safe_job_id = sanitize_filename_text(job_id)
    safe_suffix = sanitize_filename_text(suffix)

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    progress_filename = f"{safe_job_id}_{safe_suffix}_{timestamp}.json"

    progress_folder = Path(
        current_app.config.get(
            "PROGRESS_UPLOAD_FOLDER",
            Path(current_app.root_path) / "static" / "uploads" / "progress",
        )
    )

    progress_folder.mkdir(parents=True, exist_ok=True)

    save_path = progress_folder / progress_filename

    uploaded_file.save(str(save_path))

    drawing_path_json_url = make_progress_json_url(progress_filename)

    now = now_text()

    update_data = {
        "drawingPathJsonFilename": progress_filename,
        "drawingPathJsonPath": str(save_path),
        "drawingPathJsonUrl": drawing_path_json_url,
        "previewJsonUploadedAt": now,
        "updatedAt": now,
    }

    # jobId가 있으면 Firebase current_job / requests/{jobId}에도 같이 반영
    # adapter에서 별도 progress_callback을 못 타더라도 dashboard가 URL을 받을 수 있게 하기 위함.
    if job_id and job_id != "unknown":
        try:
            current_job_path = get_current_job_path()
            requests_path = get_requests_path()

            db.reference(current_job_path).update(update_data)
            db.reference(f"{requests_path}/{job_id}").update(update_data)

        except Exception as e:
            print(f"[API][ProgressJsonUpload][WARN] Firebase 업데이트 실패: {e}")

    print("=" * 70)
    print("[API][ProgressJsonUpload] 드로잉 경로 JSON 업로드 완료")
    print(f"[API][ProgressJsonUpload] job_id : {job_id}")
    print(f"[API][ProgressJsonUpload] saved  : {save_path}")
    print(f"[API][ProgressJsonUpload] url    : {drawing_path_json_url}")
    print("=" * 70)

    return jsonify({
        "ok": True,
        "message": "드로잉 경로 JSON 업로드 완료",
        "jobId": job_id,
        "progressJsonFilename": progress_filename,
        "drawingPathJsonFilename": progress_filename,
        "drawingPathJsonPath": str(save_path),
        "drawingPathJsonUrl": drawing_path_json_url,
    })