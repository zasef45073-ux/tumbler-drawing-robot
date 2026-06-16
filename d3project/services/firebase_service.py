import time
import uuid
from datetime import datetime

import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

from services import process_flow as pf


# =========================
# 기본값
# =========================

DEFAULT_JOINT = {
    "J1": None,
    "J2": None,
    "J3": None,
    "J4": None,
    "J5": None,
    "J6": None,
}

DEFAULT_POSE = {
    "X": None,
    "Y": None,
    "Z": None,
    "rX": None,
    "rY": None,
    "rZ": None,
}


# =========================
# Firebase 기본 함수
# =========================

def init_firebase(app):
    """
    Firebase Admin SDK 초기화
    app.py에서 create_app() 실행 시 한 번 호출됨.
    """

    if firebase_admin._apps:
        app.logger.info("Firebase 앱이 이미 초기화되어 있습니다.")
        return

    service_account_key = app.config["FIREBASE_SERVICE_ACCOUNT_KEY"]
    database_url = app.config["FIREBASE_DATABASE_URL"]

    cred = credentials.Certificate(service_account_key)

    firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": database_url,
        },
    )

    app.logger.info("Firebase 초기화 완료")


def get_ref(path):
    """
    Firebase Realtime Database 경로 참조 반환
    """

    return db.reference(path)


def safe_get(path, default=None):
    """
    Firebase에서 특정 경로 값을 안전하게 읽어오는 함수
    """

    try:
        value = get_ref(path).get()
        return value if value is not None else default

    except Exception as e:
        print(f"[Firebase 읽기 실패] path={path}, error={e}")
        return default


def safe_update(path, data):
    """
    Firebase 특정 경로에 값을 안전하게 업데이트하는 함수
    """

    try:
        get_ref(path).update(data)
        return True

    except Exception as e:
        print(f"[Firebase 업데이트 실패] path={path}, error={e}")
        return False


def safe_set(path, data):
    """
    Firebase 특정 경로에 값을 안전하게 덮어쓰는 함수
    """

    try:
        get_ref(path).set(data)
        return True

    except Exception as e:
        print(f"[Firebase 저장 실패] path={path}, error={e}")
        return False


# =========================
# 화면 표시용 포맷 함수
# =========================

def get_status_text(status, fallback=None):
    """
    상태값을 화면 표시용 한글 문구로 변환
    """

    return pf.get_status_text(status, fallback=fallback)


def format_value(value, suffix=""):
    """
    화면 표시용 값 변환

    값이 없으면 '-' 표시.
    값이 있으면 소수점 둘째 자리까지 표시.
    """

    if value is None:
        return "-"

    try:
        number = float(value)
        return f"{number:.2f}{suffix}"

    except (TypeError, ValueError):
        return f"{value}{suffix}"


def format_timestamp(timestamp):
    """
    Firebase에 저장된 last_update_timestamp를 화면 표시용 시간으로 변환
    """

    if not timestamp:
        return "-"

    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%H:%M:%S")

    except (TypeError, ValueError, OSError):
        return "-"


def clamp_progress(value):
    """
    진행률을 0~100 사이 정수로 보정
    """

    try:
        progress = int(float(value))
    except (TypeError, ValueError):
        progress = 0

    if progress < 0:
        return 0

    if progress > 100:
        return 100

    return progress


def get_customer_status_guide(status):
    """
    고객 조회 페이지에 표시할 상태 안내 문구 반환
    """

    return pf.get_customer_status_guide(status)


def get_default_progress_by_status(status):
    """
    요청 상태 기준 기본 진행률 반환
    """

    return pf.get_default_progress_by_status(status)


def now_text():
    """
    현재 시각 문자열 반환
    """

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_compact_text():
    """
    commandSignature 등에 사용할 compact 시간 문자열
    """

    return datetime.now().strftime("%Y%m%d%H%M%S%f")


# =========================
# command / status 유틸
# =========================

def get_command_definition(command_type):
    """
    commandType 기준 공정 정의 반환
    """

    clean_command_type = pf.normalize_command_type(command_type)

    if not clean_command_type:
        return None

    return pf.get_command_definition(clean_command_type)


def make_command_signature(job_id, command_type, requested_at):
    """
    commands/start 중복 처리 방지를 돕기 위한 명령 서명 생성

    listener에서는 jobId + commandType + requestedAt 조합으로
    같은 프로세스 내 중복 처리를 방지한다.
    """

    safe_job_id = str(job_id or "").strip()
    safe_command_type = str(command_type or "").strip()
    safe_requested_at = str(requested_at or "").strip()

    return f"{safe_job_id}|{safe_command_type}|{safe_requested_at}"


def get_status_class(status):
    """
    CSS class에 사용할 상태 문자열 반환
    """

    return str(status or "").strip().lower().replace("_", "-")


def is_running_status(status):
    """
    현재 실제 공정 진행 중 상태인지 확인
    """

    return status in {
        pf.STATUS_WAITING,
        pf.STATUS_PAPER_SETTING,
        pf.STATUS_DRAWING,
        pf.STATUS_GLUING,
        pf.STATUS_ATTACHING,
    }


def is_ready_status(status):
    """
    다음 공정 시작 대기 상태인지 확인
    """

    return status in {
        pf.STATUS_PAPER_READY,
        pf.STATUS_DRAWING_READY,
        pf.STATUS_GLUE_READY,
        pf.STATUS_ATTACH_READY,
    }


def is_done_but_not_final_status(status):
    """
    중간 공정 완료 상태인지 확인
    """

    return status in {
        pf.STATUS_PAPER_DONE,
        pf.STATUS_DRAWING_DONE,
        pf.STATUS_GLUE_DONE,
    }


# =========================
# 로봇 상태 관련 함수
# =========================

def get_robot_connection_info(
    robot_status,
    online_threshold_sec=3,
    delayed_threshold_sec=10,
):
    """
    last_update_timestamp 기준으로 로봇 연결 상태 판단

    - 최근 3초 이내 업데이트: 연결됨
    - 3초 초과 ~ 10초 이내: 업데이트 지연
    - 10초 초과: 연결 끊김
    """

    last_update_timestamp = robot_status.get("last_update_timestamp")

    if not last_update_timestamp:
        return {
            "code": "NO_DATA",
            "label": "수신 대기",
            "badge_text": "● 수신 대기",
            "last_update_text": "-",
            "elapsed_sec": None,
        }

    now = time.time()

    try:
        elapsed_sec = now - float(last_update_timestamp)

    except (TypeError, ValueError):
        return {
            "code": "INVALID_TIME",
            "label": "시간값 오류",
            "badge_text": "● 시간값 오류",
            "last_update_text": "-",
            "elapsed_sec": None,
        }

    last_update_text = format_timestamp(last_update_timestamp)

    if elapsed_sec <= online_threshold_sec:
        return {
            "code": "ONLINE",
            "label": "연결됨",
            "badge_text": "● 로봇 연결됨",
            "last_update_text": last_update_text,
            "elapsed_sec": round(elapsed_sec, 1),
        }

    if elapsed_sec <= delayed_threshold_sec:
        return {
            "code": "DELAYED",
            "label": "업데이트 지연",
            "badge_text": "● 업데이트 지연",
            "last_update_text": last_update_text,
            "elapsed_sec": round(elapsed_sec, 1),
        }

    return {
        "code": "OFFLINE",
        "label": "연결 끊김",
        "badge_text": "● 로봇 연결 끊김",
        "last_update_text": last_update_text,
        "elapsed_sec": round(elapsed_sec, 1),
    }


def get_robot_status(config):
    """
    Firebase에서 robot_status 읽기
    """

    robot_status_path = config["ROBOT_STATUS_PATH"]

    robot_status = safe_get(robot_status_path, default={}) or {}

    if not isinstance(robot_status, dict):
        robot_status = {}

    joint = robot_status.get("joint") or {}
    pose = robot_status.get("pose") or {}

    merged_joint = {**DEFAULT_JOINT, **joint}
    merged_pose = {**DEFAULT_POSE, **pose}

    connection_info = get_robot_connection_info(
        robot_status,
        online_threshold_sec=config["ROBOT_ONLINE_THRESHOLD_SEC"],
        delayed_threshold_sec=config["ROBOT_DELAYED_THRESHOLD_SEC"],
    )

    state = robot_status.get("state", pf.STATUS_IDLE)

    joint_values = [
        ("J1", format_value(merged_joint.get("J1"), "°")),
        ("J2", format_value(merged_joint.get("J2"), "°")),
        ("J3", format_value(merged_joint.get("J3"), "°")),
        ("J4", format_value(merged_joint.get("J4"), "°")),
        ("J5", format_value(merged_joint.get("J5"), "°")),
        ("J6", format_value(merged_joint.get("J6"), "°")),
    ]

    pose_values = [
        ("X", format_value(merged_pose.get("X"), " mm")),
        ("Y", format_value(merged_pose.get("Y"), " mm")),
        ("Z", format_value(merged_pose.get("Z"), " mm")),
        ("rX", format_value(merged_pose.get("rX"), "°")),
        ("rY", format_value(merged_pose.get("rY"), "°")),
        ("rZ", format_value(merged_pose.get("rZ"), "°")),
    ]

    return {
        "state": state,
        "stateText": get_status_text(state, "대기 중"),
        "connection": connection_info,
        "joint": merged_joint,
        "pose": merged_pose,
        "joint_values": joint_values,
        "pose_values": pose_values,
        "last_update_timestamp": robot_status.get("last_update_timestamp"),
        "last_update_text": connection_info["last_update_text"],
        "currentCommandType": robot_status.get("currentCommandType", ""),
        "currentJobId": robot_status.get("currentJobId", ""),
        "lastCommandType": robot_status.get("lastCommandType", ""),
        "lastJobId": robot_status.get("lastJobId", ""),
    }


# =========================
# 고객 요청 생성 관련 함수
# =========================

def generate_request_id():
    """
    고객 요청 접수번호 생성

    예시:
    TMB-20260430-194512-A3F1
    """

    current_text = datetime.now().strftime("%Y%m%d-%H%M%S")
    random_text = uuid.uuid4().hex[:4].upper()

    return f"TMB-{current_text}-{random_text}"


def create_customer_request(
    config,
    request_id,
    customer_name,
    request_text,
    image_url,
    original_filename,
):
    """
    고객 이미지 업로드 요청을 Firebase requests 경로에 저장

    저장 경로:
    /requests/{request_id}
    """

    if not request_id:
        request_id = generate_request_id()

    now = datetime.now()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")

    request_data = {
        "requestId": request_id,
        "customerName": customer_name,
        "requestText": request_text,
        "imageUrl": image_url,
        "convertedImageUrl": "",
        "originalFilename": original_filename,
        "status": pf.STATUS_SUBMITTED,
        "statusText": get_status_text(pf.STATUS_SUBMITTED),
        "progress": get_default_progress_by_status(pf.STATUS_SUBMITTED),
        "createdAt": created_at,
        "updatedAt": created_at,
        "currentCommandType": "",
        "currentCommandLabel": "",
        "lastCommandType": "",
        "lastCommandLabel": "",
        "nextReadyStatus": "",
    }

    requests_path = config["REQUESTS_PATH"]
    success = safe_set(f"{requests_path}/{request_id}", request_data)

    if not success:
        return None

    return {
        "request_id": request_id,
        "data": request_data,
    }


# =========================
# 요청 조회 / 정리 함수
# =========================

def get_requests(config):
    """
    Firebase에서 고객 요청 목록 읽기
    """

    requests_path = config["REQUESTS_PATH"]
    requests = safe_get(requests_path, default={}) or {}

    if not isinstance(requests, dict):
        return {}

    return requests


def get_request_by_id(config, request_id):
    """
    요청 ID 기준으로 요청 1건 읽기
    """

    if not request_id:
        return None

    clean_request_id = str(request_id).strip()

    if not clean_request_id:
        return None

    requests_path = config["REQUESTS_PATH"]
    request_data = safe_get(f"{requests_path}/{clean_request_id}", default=None)

    if not isinstance(request_data, dict):
        return None

    return request_data


def normalize_request_item(request_id, data):
    """
    요청 목록 화면에서 쓰기 좋게 요청 1건을 정리
    """

    data = data or {}

    raw_status = data.get("status", pf.STATUS_SUBMITTED)
    status_text = data.get("statusText") or get_status_text(raw_status)

    next_action = pf.get_next_admin_action(raw_status)

    return {
        "id": request_id,
        "name": data.get("customerName", "-"),
        "option": data.get("option", "-"),
        "status": status_text,
        "rawStatus": raw_status,
        "statusClass": get_status_class(raw_status),
        "time": data.get("createdTime", data.get("createdAt", "-")),
        "createdAt": data.get("createdAt", "-"),
        "imageUrl": data.get("imageUrl", ""),
        "convertedImageUrl": data.get("convertedImageUrl", ""),
        "requestText": data.get("requestText", ""),
        "progress": clamp_progress(
            data.get("progress", get_default_progress_by_status(raw_status))
        ),
        "step": data.get("step", "-"),
        "nextAction": next_action,
        "currentCommandType": data.get("currentCommandType", ""),
        "currentCommandLabel": data.get("currentCommandLabel", ""),
        "lastCommandType": data.get("lastCommandType", ""),
        "lastCommandLabel": data.get("lastCommandLabel", ""),
        "nextReadyStatus": data.get("nextReadyStatus", ""),
    }


def get_pending_requests(config, limit=5):
    """
    승인 대기 또는 검토 중인 요청 목록 가져오기
    """

    requests = get_requests(config)

    pending_statuses = {
        pf.STATUS_SUBMITTED,
        pf.STATUS_REVIEWING,
    }

    pending = []

    for request_id, data in requests.items():
        item = normalize_request_item(request_id, data)

        if item["rawStatus"] in pending_statuses:
            pending.append(item)

    pending.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)

    return pending[:limit]


def get_all_request_items(config):
    """
    관리자 요청 목록 페이지에서 사용할 전체 요청 목록 반환
    """

    requests = get_requests(config)

    items = []

    for request_id, data in requests.items():
        item = normalize_request_item(request_id, data)
        items.append(item)

    items.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)

    return items


def get_admin_request_detail(config, request_id):
    """
    관리자 요청 상세 페이지에서 사용할 요청 1건 반환
    """

    request_data = get_request_by_id(config, request_id)

    if not request_data:
        return None

    raw_status = request_data.get("status", pf.STATUS_SUBMITTED)
    status_text = request_data.get("statusText") or get_status_text(raw_status)
    next_action = pf.get_next_admin_action(raw_status)

    return {
        "id": request_id,
        "customerName": request_data.get("customerName", "-"),
        "requestText": request_data.get("requestText", ""),
        "option": request_data.get("option", "-"),
        "status": raw_status,
        "statusClass": get_status_class(raw_status),
        "statusText": status_text,
        "imageUrl": request_data.get("imageUrl", ""),
        "convertedImageUrl": request_data.get("convertedImageUrl", ""),
        "originalFilename": request_data.get("originalFilename", "-"),
        "createdAt": request_data.get("createdAt", "-"),
        "createdDate": request_data.get("createdDate", "-"),
        "createdTime": request_data.get("createdTime", "-"),
        "updatedAt": request_data.get("updatedAt", "-"),
        "approvedAt": request_data.get("approvedAt", "-"),
        "adminMemo": request_data.get("adminMemo", ""),
        "errorMessage": request_data.get("errorMessage", ""),
        "progress": clamp_progress(
            request_data.get("progress", get_default_progress_by_status(raw_status))
        ),
        "step": request_data.get("step", "-"),
        "currentCommandType": request_data.get("currentCommandType", ""),
        "currentCommandLabel": request_data.get("currentCommandLabel", ""),
        "lastCommandType": request_data.get("lastCommandType", ""),
        "lastCommandLabel": request_data.get("lastCommandLabel", ""),
        "nextReadyStatus": request_data.get("nextReadyStatus", ""),
        "nextAction": next_action,
        "canApprove": raw_status in {pf.STATUS_SUBMITTED, pf.STATUS_REVIEWING},
        "canReject": raw_status in {
            pf.STATUS_SUBMITTED,
            pf.STATUS_REVIEWING,
            pf.STATUS_APPROVED,
            pf.STATUS_PAPER_READY,
            pf.STATUS_DRAWING_READY,
            pf.STATUS_GLUE_READY,
            pf.STATUS_ATTACH_READY,
        },
        "canStart": next_action is not None,
        "canRequestPaper": pf.can_request_command(raw_status, pf.COMMAND_TYPE_PAPER),
        "canRequestDrawing": pf.can_request_command(raw_status, pf.COMMAND_TYPE_DRAWING),
        "canRequestGlue": pf.can_request_command(raw_status, pf.COMMAND_TYPE_GLUE),
        "canRequestAttach": pf.can_request_command(raw_status, pf.COMMAND_TYPE_ATTACH),
        "isRunning": is_running_status(raw_status),
        "isReady": is_ready_status(raw_status),
        "isDoneButNotFinal": is_done_but_not_final_status(raw_status),
    }


def get_customer_request_status(config, request_id):
    """
    고객 접수번호 조회 페이지에서 사용할 요청 상태 정보 반환

    처리:
    1. requests/{request_id}에서 고객 요청 정보 조회
    2. current_job이 같은 jobId이면 진행률/단계/이미지 정보까지 반영
    3. 상태별 안내 문구와 화면 표시용 데이터를 함께 반환
    """

    if not request_id:
        return None

    clean_request_id = str(request_id).strip()

    if not clean_request_id:
        return None

    request_data = get_request_by_id(config, clean_request_id)

    if not request_data:
        return None

    raw_status = request_data.get("status", pf.STATUS_SUBMITTED)
    status_text = request_data.get("statusText") or get_status_text(raw_status)

    current_job_path = config["CURRENT_JOB_PATH"]
    current_job = safe_get(current_job_path, default={}) or {}

    if not isinstance(current_job, dict):
        current_job = {}

    is_current_job = current_job.get("jobId") == clean_request_id

    progress = clamp_progress(
        request_data.get("progress", get_default_progress_by_status(raw_status))
    )
    step = request_data.get("step", "-")

    image_url = request_data.get("imageUrl", "")
    converted_image_url = request_data.get("convertedImageUrl", "")

    if is_current_job:
        progress = clamp_progress(current_job.get("progress", progress))
        step = current_job.get("step", step)

        if current_job.get("imageUrl"):
            image_url = current_job.get("imageUrl", image_url)

        if current_job.get("convertedImageUrl"):
            converted_image_url = current_job.get(
                "convertedImageUrl",
                converted_image_url,
            )

    if raw_status == pf.STATUS_COMPLETED:
        progress = 100

    if raw_status in {pf.STATUS_REJECTED, pf.STATUS_ERROR} and not is_current_job:
        progress = 0

    guide = get_customer_status_guide(raw_status)

    return {
        "id": clean_request_id,
        "customerName": request_data.get("customerName", "-"),
        "requestText": request_data.get("requestText", ""),
        "option": request_data.get("option", "-"),
        "status": raw_status,
        "statusText": status_text,
        "statusClass": get_status_class(raw_status),
        "guideTitle": guide["title"],
        "guideDescription": guide["description"],
        "progress": progress,
        "step": step,
        "imageUrl": image_url,
        "convertedImageUrl": converted_image_url,
        "originalFilename": request_data.get("originalFilename", "-"),
        "createdAt": request_data.get("createdAt", "-"),
        "createdDate": request_data.get("createdDate", "-"),
        "createdTime": request_data.get("createdTime", "-"),
        "updatedAt": request_data.get("updatedAt", "-"),
        "adminMemo": request_data.get("adminMemo", ""),
        "errorMessage": request_data.get("errorMessage", ""),
        "isCurrentJob": is_current_job,
        "currentJobStatus": current_job.get("status", "") if is_current_job else "",
        "currentJobStatusText": current_job.get("statusText", "") if is_current_job else "",
        "currentCommandType": request_data.get("currentCommandType", ""),
        "currentCommandLabel": request_data.get("currentCommandLabel", ""),
        "lastCommandType": request_data.get("lastCommandType", ""),
        "lastCommandLabel": request_data.get("lastCommandLabel", ""),
        "nextReadyStatus": request_data.get("nextReadyStatus", ""),
    }


# =========================
# 요청 상태 변경 함수
# =========================

def update_request_status(config, request_id, status, status_text=None, extra_data=None):
    """
    요청 상태 변경
    """

    if not request_id:
        return False

    update_data = {
        "status": status,
        "statusText": status_text or get_status_text(status),
        "progress": get_default_progress_by_status(status),
        "updatedAt": now_text(),
    }

    if extra_data:
        update_data.update(extra_data)

    requests_path = config["REQUESTS_PATH"]

    return safe_update(f"{requests_path}/{request_id}", update_data)


def approve_request(config, request_id, admin_memo=""):
    """
    관리자 승인 처리

    상태:
    SUBMITTED 또는 REVIEWING → PAPER_READY

    이유:
    이제 전체 공정은 PAPER → DRAWING → GLUE → ATTACH 순서로 진행된다.
    승인 직후 바로 종이 세팅 시작 가능 상태로 둔다.
    """

    if not request_id:
        return False

    request_data = get_request_by_id(config, request_id)

    if not request_data:
        return False

    current_status = request_data.get("status")

    if current_status not in {pf.STATUS_SUBMITTED, pf.STATUS_REVIEWING}:
        return False

    current_time = now_text()

    update_data = {
        "status": pf.STATUS_PAPER_READY,
        "statusText": get_status_text(pf.STATUS_PAPER_READY),
        "progress": get_default_progress_by_status(pf.STATUS_PAPER_READY),
        "step": "1 / 4",
        "adminMemo": admin_memo,
        "approvedAt": current_time,
        "updatedAt": current_time,
        "currentCommandType": "",
        "currentCommandLabel": "",
        "nextReadyStatus": pf.STATUS_PAPER_READY,
    }

    requests_path = config["REQUESTS_PATH"]

    return safe_update(f"{requests_path}/{request_id}", update_data)


def reject_request(config, request_id, admin_memo=""):
    """
    관리자 거절 처리

    상태:
    작업 중이거나 완료된 건은 거절 처리하지 않는다.
    """

    if not request_id:
        return False

    request_data = get_request_by_id(config, request_id)

    if not request_data:
        return False

    current_status = request_data.get("status")

    rejectable_statuses = {
        pf.STATUS_SUBMITTED,
        pf.STATUS_REVIEWING,
        pf.STATUS_APPROVED,
        pf.STATUS_PAPER_READY,
        pf.STATUS_DRAWING_READY,
        pf.STATUS_GLUE_READY,
        pf.STATUS_ATTACH_READY,
    }

    if current_status not in rejectable_statuses:
        return False

    current_time = now_text()

    update_data = {
        "status": pf.STATUS_REJECTED,
        "statusText": get_status_text(pf.STATUS_REJECTED),
        "progress": 0,
        "adminMemo": admin_memo,
        "rejectedAt": current_time,
        "updatedAt": current_time,
        "currentCommandType": "",
        "currentCommandLabel": "",
        "nextReadyStatus": "",
    }

    requests_path = config["REQUESTS_PATH"]

    return safe_update(f"{requests_path}/{request_id}", update_data)


def mark_request_waiting(config, request_id):
    """
    기존 코드 호환용 함수.

    예전 구조:
    APPROVED → WAITING

    새 구조:
    이 함수는 직접 사용하지 않는 방향으로 가고,
    request_start_job(command_type=...)을 사용한다.
    """

    if not request_id:
        return False

    current_time = now_text()

    update_data = {
        "status": pf.STATUS_WAITING,
        "statusText": get_status_text(pf.STATUS_WAITING),
        "progress": get_default_progress_by_status(pf.STATUS_WAITING),
        "waitingAt": current_time,
        "updatedAt": current_time,
    }

    requests_path = config["REQUESTS_PATH"]

    return safe_update(f"{requests_path}/{request_id}", update_data)


# =========================
# 현재 작업 관련 함수
# =========================
def get_current_job(config):
    """
    Firebase에서 현재 작업 정보 읽기

    아직 current_job이 없으면 화면이 깨지지 않도록 기본값 반환.

    중요:
    - 대시보드 drawing canvas는 drawingPathJsonUrl을 필요로 한다.
    - Firebase current_job에 drawingPathJsonUrl이 있어도
      여기서 반환하지 않으면 /api/dashboard 응답에 포함되지 않는다.
    """

    current_job_path = config["CURRENT_JOB_PATH"]
    current_job = safe_get(current_job_path, default={}) or {}

    if not isinstance(current_job, dict):
        current_job = {}

    raw_status = current_job.get("status", pf.STATUS_NONE)
    status_text = current_job.get("statusText") or get_status_text(raw_status)

    return {
        "id": current_job.get("jobId", current_job.get("id", "-")),
        "name": current_job.get("customerName", current_job.get("name", "-")),
        "status": raw_status,
        "statusClass": get_status_class(raw_status),
        "statusText": status_text,
        "step": current_job.get("step", "0 / 4"),
        "start_time": current_job.get("startTime", "-"),
        "progress": clamp_progress(current_job.get("progress", 0)),

        "runnerStep": current_job.get("runnerStep", ""),
        "runnerProgress": current_job.get("runnerProgress", ""),
        "runnerCommand": current_job.get("runnerCommand", ""),
        "runnerPhase": current_job.get("runnerPhase", ""),

        "imageUrl": current_job.get("imageUrl", ""),
        "downloadedImagePath": current_job.get("downloadedImagePath", ""),
        "convertedImagePath": current_job.get("convertedImagePath", ""),
        "convertedImageUrl": current_job.get("convertedImageUrl", ""),

        # drawing canvas용 경로 데이터
        "previewJsonPath": current_job.get("previewJsonPath", ""),
        "drawingPathJsonPath": current_job.get("drawingPathJsonPath", ""),
        "drawingPathJsonUrl": current_job.get("drawingPathJsonUrl", ""),

        # 나중에 실제 point index 기반으로 진행률을 줄 때 사용할 수 있는 값
        "drawingPhase": current_job.get("drawingPhase", ""),
        "drawingProgress": current_job.get("drawingProgress", ""),
        "drawingProgressPercent": current_job.get("drawingProgressPercent", ""),
        "drawingPointIndex": current_job.get("drawingPointIndex", ""),
        "drawingTotalPoints": current_job.get("drawingTotalPoints", ""),

        "option": current_job.get("option", "-"),
        "requestText": current_job.get("requestText", ""),
        "commandType": current_job.get("commandType", ""),
        "commandLabel": current_job.get("commandLabel", ""),
        "processDescription": current_job.get("processDescription", ""),
        "nextReadyStatus": current_job.get("nextReadyStatus", ""),
        "listenerMode": current_job.get("listenerMode", ""),
        "adapterMode": current_job.get("adapterMode", ""),
        "updatedAt": current_job.get("updatedAt", "-"),
        "doneAt": current_job.get("doneAt", ""),
        "completedAt": current_job.get("completedAt", ""),
        "errorMessage": current_job.get("errorMessage", ""),
    }

def set_current_job_from_request(config, request_id, command_definition=None):
    """
    요청 정보를 current_job 경로에 저장
    """

    request_data = get_request_by_id(config, request_id)

    if not request_data:
        return False

    command_definition = command_definition or {}
    command_type = command_definition.get("commandType", "")
    command_label = command_definition.get("label", "작업 시작")
    process_description = command_definition.get("description", "")
    current_time = now_text()

    current_job_data = {
        "jobId": request_id,
        "customerName": request_data.get("customerName", "-"),
        "status": command_definition.get("runningStatus", pf.STATUS_WAITING),
        "statusText": command_definition.get(
            "runningStatusText",
            get_status_text(pf.STATUS_WAITING),
        ),
        "step": command_definition.get("step", "0 / 4"),
        "progress": command_definition.get(
            "startProgress",
            get_default_progress_by_status(pf.STATUS_WAITING),
        ),
        "startTime": current_time,
        "updatedAt": current_time,
        "imageUrl": request_data.get("imageUrl", ""),
        "downloadedImagePath": "",
        "convertedImagePath": request_data.get("convertedImagePath", ""),
        "convertedImageUrl": request_data.get("convertedImageUrl", ""),
        "option": request_data.get("option", "-"),
        "requestText": request_data.get("requestText", ""),
        "commandType": command_type,
        "commandLabel": command_label,
        "processDescription": process_description,
        "nextReadyStatus": command_definition.get("nextReadyStatus", ""),
        "createdAt": current_time,
    }

    current_job_path = config["CURRENT_JOB_PATH"]

    return safe_set(current_job_path, current_job_data)


# =========================
# 관리자 명령 관련 함수
# =========================

def request_start_job(
    config,
    job_id,
    requested_by="admin",
    command_type=pf.COMMAND_TYPE_PAPER,
):
    """
    관리자 페이지에서 공정 시작 버튼을 눌렀을 때 사용할 함수

    처리 내용:
    1. commandType 검증
    2. 현재 요청 상태에서 해당 공정 시작 가능한지 확인
    3. requests/{job_id} 상태를 해당 공정 진행 중 상태로 변경
    4. current_job에 현재 공정 정보 저장
    5. commands/start에 로봇 PC가 읽을 명령 저장

    command_type:
    - paper
    - drawing
    - glue
    - attach
    """

    if not job_id:
        return False

    command_definition = get_command_definition(command_type)

    if not command_definition:
        return False

    command_type = command_definition["commandType"]

    request_data = get_request_by_id(config, job_id)

    if not request_data:
        return False

    current_status = request_data.get("status")

    if not pf.can_request_command(current_status, command_type):
        return False

    requested_at = now_text()
    command_signature = make_command_signature(
        job_id=job_id,
        command_type=command_type,
        requested_at=requested_at,
    )

    # 1. 요청 상태를 해당 공정 진행 중으로 변경
    requests_path = config["REQUESTS_PATH"]

    request_update = {
        "status": command_definition["runningStatus"],
        "statusText": command_definition["runningStatusText"],
        "progress": command_definition["startProgress"],
        "step": command_definition["step"],
        "currentCommandType": command_type,
        "currentCommandLabel": command_definition["label"],
        "commandLabel": command_definition["label"],
        "commandRequestedAt": requested_at,
        "commandSignature": command_signature,
        "updatedAt": requested_at,
        "nextReadyStatus": command_definition["nextReadyStatus"],
        "errorMessage": "",
    }

    command_request_ok = safe_update(
        f"{requests_path}/{job_id}",
        request_update,
    )

    if not command_request_ok:
        return False

    # 2. current_job 업데이트
    current_job_ok = set_current_job_from_request(
        config,
        job_id,
        command_definition=command_definition,
    )

    if not current_job_ok:
        return False

    # 3. 로봇 PC가 읽을 작업 시작 명령 저장
    commands_path = config["COMMANDS_PATH"]

    command_data = {
        "jobId": job_id,
        "commandType": command_type,
        "commandLabel": command_definition["label"],
        "commandSignature": command_signature,
        "customerName": request_data.get("customerName", "-"),
        "imageUrl": request_data.get("imageUrl", ""),
        "convertedImageUrl": request_data.get("convertedImageUrl", ""),
        "option": request_data.get("option", "-"),
        "requestText": request_data.get("requestText", ""),
        "requestedBy": requested_by,
        "requestedAt": requested_at,
        "status": "REQUESTED",
        "statusText": f"{command_definition['label']} 요청",
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
    }

    return safe_set(f"{commands_path}/start", command_data)


# =========================
# 대시보드 요약 데이터
# =========================

def get_summary_cards(config):
    """
    오늘 접수 / 승인 대기 / 제작 중 / 제작 완료 카드 계산
    """

    requests = get_requests(config)

    total_today = 0
    pending_count = 0
    working_count = 0
    completed_count = 0

    today_text = datetime.now().strftime("%Y-%m-%d")

    working_statuses = {
        pf.STATUS_WAITING,
        pf.STATUS_PAPER_SETTING,
        pf.STATUS_DRAWING,
        pf.STATUS_GLUING,
        pf.STATUS_ATTACHING,
    }

    for _, data in requests.items():
        if not isinstance(data, dict):
            continue

        status = data.get("status", "")
        created_date = str(data.get("createdDate", ""))
        created_at = str(data.get("createdAt", ""))

        if created_date == today_text or today_text in created_at:
            total_today += 1

        if status in {pf.STATUS_SUBMITTED, pf.STATUS_REVIEWING}:
            pending_count += 1

        if status in working_statuses:
            working_count += 1

        if status == pf.STATUS_COMPLETED:
            completed_count += 1

    return [
        {
            "label": "오늘 접수",
            "value": f"{total_today}건",
            "sub": "오늘 등록된 요청",
        },
        {
            "label": "승인 대기",
            "value": f"{pending_count}건",
            "sub": "관리자 검수 필요",
        },
        {
            "label": "공정 진행",
            "value": f"{working_count}건",
            "sub": "로봇 제작 공정 진행",
        },
        {
            "label": "제작 완료",
            "value": f"{completed_count}건",
            "sub": "전체 공정 완료",
        },
    ]


def get_dashboard_data(config):
    """
    관리자 대시보드에 필요한 전체 데이터 묶음
    """

    robot_status = get_robot_status(config)
    current_job = get_current_job(config)
    pending_requests = get_pending_requests(config)
    summary_cards = get_summary_cards(config)

    return {
        "summary_cards": summary_cards,
        "robot_status": robot_status,
        "current_job": current_job,
        "pending_requests": pending_requests,
        "refresh_interval_ms": config["DASHBOARD_REFRESH_INTERVAL_MS"],
    }