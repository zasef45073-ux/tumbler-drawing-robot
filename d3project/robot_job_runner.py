import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen

from config import Config
from robot_activity.robot_algorithm_adapter import run_doosan_drawing_job


# =========================
# 기본 경로 설정
# =========================

# 로봇 PC에서 다운로드한 원본 이미지를 저장할 폴더
DOWNLOAD_DIR = Path("downloaded_jobs")

# 로컬 변환 결과 임시 폴더
LOCAL_CONVERTED_DIR = Path("converted_jobs")

# 테스트용 단계 대기 시간
DEMO_STEP_DELAY_SEC = 3


# =========================
# commandType 설정
# =========================

COMMAND_TYPE_PAPER = "paper"
COMMAND_TYPE_DRAWING = "drawing"
COMMAND_TYPE_GLUE = "glue"
COMMAND_TYPE_ATTACH = "attach"

VALID_COMMAND_TYPES = {
    COMMAND_TYPE_PAPER,
    COMMAND_TYPE_DRAWING,
    COMMAND_TYPE_GLUE,
    COMMAND_TYPE_ATTACH,
}

NON_DRAWING_COMMAND_TYPES = {
    COMMAND_TYPE_PAPER,
    COMMAND_TYPE_GLUE,
    COMMAND_TYPE_ATTACH,
}


# =========================
# 공통 유틸 함수
# =========================

def now_text():
    """
    화면/Firebase 로그에 사용할 현재 시간 문자열
    """

    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_mkdir(path):
    """
    폴더가 없으면 생성
    """

    Path(path).mkdir(parents=True, exist_ok=True)


def sanitize_filename_text(value):
    """
    파일명에 안전하게 사용할 수 있도록 문자열 정리
    """

    clean_value = str(value or "").strip()

    if not clean_value:
        return "unknown"

    return re.sub(r"[^A-Za-z0-9_.-]", "_", clean_value)


def normalize_command_type(value):
    """
    Firebase commands/start.commandType 값을 정리한다.

    지원값:
    - paper
    - drawing
    - glue
    - attach

    주의:
    - None, 빈 문자열, 미지원 값이면 "" 반환
    """

    clean_value = str(value or "").strip().lower()

    if clean_value in VALID_COMMAND_TYPES:
        return clean_value

    return ""


def get_command_type_from_command(command):
    """
    command dict에서 commandType을 읽는다.

    우선순위:
    1. commandType
    2. command_type
    3. 없으면 drawing으로 간주

    3번을 drawing으로 두는 이유:
    - 기존 단순 드로잉 성공 구조와의 호환성 유지
    - 예전 commands/start에 commandType이 없던 경우도 기존처럼 드로잉으로 동작하게 함
    """

    raw_command_type = (
        command.get("commandType")
        or command.get("command_type")
        or COMMAND_TYPE_DRAWING
    )

    return normalize_command_type(raw_command_type)


def get_file_extension_from_url(image_url, default_extension="png"):
    """
    imageUrl에서 파일 확장자 추출

    예:
    http://192.168.0.9:5000/static/uploads/original/TMB-xxx.png
    → png
    """

    parsed_url = urlparse(image_url)
    clean_path = unquote(parsed_url.path or "")
    filename = Path(clean_path).name

    if "." not in filename:
        return default_extension

    extension = filename.rsplit(".", 1)[1].lower().strip()

    if not extension or len(extension) > 5:
        return default_extension

    return extension


def get_file_extension_from_path(file_path, default_extension="png"):
    """
    로컬 파일 경로에서 확장자 추출
    """

    suffix = Path(file_path).suffix.lower().replace(".", "").strip()

    if not suffix or len(suffix) > 5:
        return default_extension

    return suffix


def normalize_image_url(image_url):
    """
    imageUrl 보정 함수

    필요한 이유:
    - 예전 요청에는 http://localhost:5000/static/... 이 들어가 있을 수 있음.
    - 로봇 PC에서 localhost는 웹서버 PC가 아니라 로봇 PC 자기 자신을 뜻함.
    - 따라서 localhost / 127.0.0.1 주소는 Config.PUBLIC_BASE_URL 기준으로 보정함.
    - /static/... 같은 상대경로도 Config.PUBLIC_BASE_URL을 붙여 전체 URL로 변환함.
    """

    if not image_url:
        raise ValueError("imageUrl이 비어 있습니다.")

    clean_url = str(image_url).strip()

    if not clean_url:
        raise ValueError("imageUrl이 비어 있습니다.")

    public_base_url = Config.PUBLIC_BASE_URL.rstrip("/")

    if clean_url.startswith("/"):
        return public_base_url + clean_url

    parsed = urlparse(clean_url)

    if parsed.scheme in {"http", "https"} and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
    }:
        path = parsed.path or ""
        query = f"?{parsed.query}" if parsed.query else ""
        return public_base_url + path + query

    return clean_url


def make_converted_public_url(filename):
    """
    변환 이미지 파일명을 웹 접근 URL로 변환

    예:
    filename = TMB-xxx_converted.png

    결과:
    http://192.168.0.9:5000/static/uploads/converted/TMB-xxx_converted.png
    """

    public_base_url = Config.PUBLIC_BASE_URL.rstrip("/")
    converted_prefix = Config.CONVERTED_UPLOAD_URL_PREFIX.strip("/")

    return f"{public_base_url}/{converted_prefix}/{filename}"


def copy_image_to_converted_static(
    job_id,
    source_image_path,
    suffix="converted",
):
    """
    로컬 이미지 파일을 Flask static/uploads/converted 폴더로 복사하고
    웹에서 접근 가능한 URL을 생성함.

    이 함수는 두 경우에 사용됨.

    1. demo 모드
       - 원본 이미지를 변환 이미지처럼 복사해서 화면 표시 테스트

    2. real 모드
       - 실제 알고리즘이 만든 변환 이미지 파일을 웹 표시용 폴더에 복사

    반환:
    {
        "converted_image_path": "...",
        "converted_image_url": "...",
        "converted_filename": "..."
    }
    """

    if not job_id:
        raise ValueError("job_id가 없습니다.")

    if not source_image_path:
        raise ValueError("source_image_path가 없습니다.")

    source_path = Path(source_image_path)

    if not source_path.exists():
        raise FileNotFoundError(
            f"변환 이미지 원본 파일을 찾을 수 없습니다: {source_path}"
        )

    extension = get_file_extension_from_path(source_path)
    safe_job_id = sanitize_filename_text(job_id)
    safe_suffix = sanitize_filename_text(suffix)

    converted_filename = f"{safe_job_id}_{safe_suffix}.{extension}"

    converted_folder = Path(Config.CONVERTED_UPLOAD_FOLDER)
    safe_mkdir(converted_folder)

    destination_path = converted_folder / converted_filename

    # 원본과 목적지가 같은 파일이면 복사 생략
    if source_path.resolve() != destination_path.resolve():
        shutil.copyfile(source_path, destination_path)

    converted_image_url = make_converted_public_url(converted_filename)

    print("[Runner][Converted] 변환 이미지 웹 표시용 저장 완료")
    print(f"[Runner][Converted] source: {source_path}")
    print(f"[Runner][Converted] saved: {destination_path}")
    print(f"[Runner][Converted] url: {converted_image_url}")

    return {
        "converted_image_path": str(destination_path),
        "converted_image_url": converted_image_url,
        "converted_filename": converted_filename,
    }


def ensure_converted_image_url(
    job_id,
    converted_image_path="",
    converted_image_url="",
):
    """
    실제 알고리즘 결과에 converted_image_path만 있고 converted_image_url이 없을 때,
    static/uploads/converted에 복사하고 URL을 자동 생성함.

    이미 converted_image_url이 있으면 그대로 사용.
    """

    if converted_image_url:
        return {
            "converted_image_path": converted_image_path,
            "converted_image_url": converted_image_url,
        }

    if not converted_image_path:
        return {
            "converted_image_path": "",
            "converted_image_url": "",
        }

    result = copy_image_to_converted_static(
        job_id=job_id,
        source_image_path=converted_image_path,
        suffix="converted",
    )

    return {
        "converted_image_path": result["converted_image_path"],
        "converted_image_url": result["converted_image_url"],
    }


def download_image(image_url, job_id):
    """
    imageUrl에서 이미지를 다운로드하고 로컬 경로 반환
    """

    if not job_id:
        raise ValueError("job_id가 없습니다.")

    normalized_url = normalize_image_url(image_url)
    extension = get_file_extension_from_url(normalized_url)

    safe_mkdir(DOWNLOAD_DIR)

    save_path = DOWNLOAD_DIR / f"{job_id}.{extension}"

    print(f"[Runner][Download] imageUrl: {normalized_url}")
    print(f"[Runner][Download] save_path: {save_path}")

    request = Request(
        normalized_url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    with urlopen(request, timeout=15) as response:
        with open(save_path, "wb") as output_file:
            shutil.copyfileobj(response, output_file)

    print("[Runner][Download] 이미지 다운로드 완료")

    return {
        "image_url": normalized_url,
        "downloaded_path": str(save_path),
        "extension": extension,
    }


def make_result(
    success,
    job_id,
    message,
    downloaded_image_path="",
    normalized_image_url="",
    converted_image_path="",
    converted_image_url="",
    error_message="",
    extra=None,
):
    """
    로봇 작업 결과 표준 반환 형식
    """

    return {
        "success": success,
        "jobId": job_id,
        "message": message,
        "downloadedImagePath": downloaded_image_path,
        "normalizedImageUrl": normalized_image_url,
        "convertedImagePath": converted_image_path,
        "convertedImageUrl": converted_image_url,
        "errorMessage": error_message,
        "finishedAt": now_text(),
        "extra": extra or {},
    }


def make_blocked_non_drawing_result(
    job_id,
    command_type,
    mode,
    customer_name="-",
    option="-",
    request_text="",
):
    """
    drawing이 아닌 commandType이 runner로 들어왔을 때 반환할 방어 결과.

    중요한 이유:
    - robot_job_runner.py는 현재 drawing 전용 실행 흐름을 가진다.
    - paper / glue / attach는 여기서 처리하면 안 된다.
    - 여기서 success=True를 반환하면 listener가 COMPLETED로 처리할 수 있으므로
      의도적으로 success=False를 반환한다.
    """

    command_type_label_map = {
        COMMAND_TYPE_PAPER: "종이 세팅",
        COMMAND_TYPE_GLUE: "풀 도포",
        COMMAND_TYPE_ATTACH: "부착",
    }

    command_label = command_type_label_map.get(command_type, command_type)

    error_message = (
        f"commandType={command_type}({command_label}) 명령이 "
        "drawing 전용 robot_job_runner.py로 들어왔습니다. "
        "실제 드로잉 실행을 막았습니다. "
        "paper/glue/attach 공정은 listener 또는 별도 adapter에서 처리해야 합니다."
    )

    print("=" * 70)
    print("[Runner][BLOCKED] 비드로잉 공정 실행 차단")
    print(f"[Runner][BLOCKED] job_id       : {job_id}")
    print(f"[Runner][BLOCKED] command_type : {command_type}")
    print(f"[Runner][BLOCKED] mode         : {mode}")
    print(f"[Runner][BLOCKED] customer     : {customer_name}")
    print(f"[Runner][BLOCKED] option       : {option}")
    print(f"[Runner][BLOCKED] request_text : {request_text}")
    print(f"[Runner][BLOCKED] reason       : {error_message}")
    print("=" * 70)

    return make_result(
        success=False,
        job_id=job_id,
        message="비드로잉 공정 실행 차단",
        error_message=error_message,
        extra={
            "mode": mode,
            "commandType": command_type,
            "customerName": customer_name,
            "option": option,
            "requestText": request_text,
            "blocked": True,
            "blockReason": "NON_DRAWING_COMMAND_ENTERED_DRAWING_RUNNER",
        },
    )


def make_invalid_command_type_result(
    job_id,
    raw_command_type,
    mode,
    customer_name="-",
    option="-",
):
    """
    지원하지 않는 commandType이 들어왔을 때 반환할 결과.
    """

    error_message = (
        f"지원하지 않는 commandType입니다: {raw_command_type}. "
        f"허용값: {sorted(VALID_COMMAND_TYPES)}"
    )

    print("=" * 70)
    print("[Runner][ERROR] 지원하지 않는 commandType")
    print(f"[Runner][ERROR] job_id          : {job_id}")
    print(f"[Runner][ERROR] raw_command_type: {raw_command_type}")
    print(f"[Runner][ERROR] mode            : {mode}")
    print("=" * 70)

    return make_result(
        success=False,
        job_id=job_id,
        message="지원하지 않는 commandType",
        error_message=error_message,
        extra={
            "mode": mode,
            "commandType": raw_command_type,
            "customerName": customer_name,
            "option": option,
            "blocked": True,
            "blockReason": "INVALID_COMMAND_TYPE",
        },
    )


def call_progress(
    progress_callback,
    job_id,
    status,
    status_text,
    step,
    progress,
    extra_data=None,
):
    """
    진행률 콜백 호출
    """

    print(
        f"[Runner][Progress] {job_id} | "
        f"{status_text} | step={step} | progress={progress}%"
    )

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


def normalize_algorithm_result(result):
    """
    로봇 알고리즘 반환값을 runner가 사용하기 쉬운 dict로 정리
    """

    if result is None:
        result = {}

    if not isinstance(result, dict):
        result = {
            "success": True,
            "message": str(result),
        }

    return {
        "success": result.get("success", True),
        "message": result.get("message", "작업 완료"),
        "converted_image_path": result.get("converted_image_path", ""),
        "converted_image_url": result.get("converted_image_url", ""),
        "extra": result.get("extra", {}),
    }


# =========================
# 테스트용 가짜 로봇 작업
# =========================

def run_demo_robot_algorithm(
    job_id,
    image_path,
    option=None,
    request_text=None,
    progress_callback=None,
):
    """
    테스트용 가짜 로봇 작업

    실제 로봇은 움직이지 않음.
    대신 원본 이미지를 static/uploads/converted에 복사해서
    변환 이미지 표시 흐름을 테스트할 수 있게 함.
    """

    print("=" * 70)
    print("[Runner][DEMO] 가짜 로봇 작업 시작")
    print(f"[Runner][DEMO] job_id: {job_id}")
    print(f"[Runner][DEMO] image_path: {image_path}")
    print(f"[Runner][DEMO] option: {option}")
    print(f"[Runner][DEMO] request_text: {request_text}")
    print("=" * 70)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status="DRAWING",
        status_text="이미지 변환 준비 중",
        step="3 / 6",
        progress=45,
    )
    time.sleep(DEMO_STEP_DELAY_SEC)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status="DRAWING",
        status_text="이미지 변환 중",
        step="4 / 6",
        progress=60,
    )
    time.sleep(DEMO_STEP_DELAY_SEC)

    # demo 변환 이미지 생성
    # 현재는 실제 변환 알고리즘이 없으므로 원본 이미지를 변환 이미지 위치로 복사함.
    converted_result = copy_image_to_converted_static(
        job_id=job_id,
        source_image_path=image_path,
        suffix="demo_converted",
    )

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status="DRAWING",
        status_text="변환 이미지 생성 완료",
        step="4 / 6",
        progress=65,
        extra_data={
            "convertedImagePath": converted_result["converted_image_path"],
            "convertedImageUrl": converted_result["converted_image_url"],
        },
    )
    time.sleep(DEMO_STEP_DELAY_SEC)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status="DRAWING",
        status_text="로봇 경로 생성 중",
        step="5 / 6",
        progress=75,
    )
    time.sleep(DEMO_STEP_DELAY_SEC)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status="DRAWING",
        status_text="로봇 드로잉 중",
        step="6 / 6",
        progress=90,
    )
    time.sleep(DEMO_STEP_DELAY_SEC)

    print("[Runner][DEMO] 가짜 로봇 작업 완료")

    return {
        "success": True,
        "converted_image_path": converted_result["converted_image_path"],
        "converted_image_url": converted_result["converted_image_url"],
        "message": "테스트 로봇 작업 완료",
    }


# =========================
# 실제 로봇 알고리즘 연결
# =========================

def run_real_robot_algorithm(
    job_id,
    image_path,
    option=None,
    request_text=None,
    progress_callback=None,
):
    """
    실제 두산 M0609 로봇 알고리즘 연결 함수

    실제 로봇팀 코드는 robot_algorithm_adapter.py의
    run_doosan_drawing_job() 안에 연결함.
    """

    print("=" * 70)
    print("[Runner][REAL] 실제 로봇 알고리즘 호출")
    print(f"[Runner][REAL] job_id: {job_id}")
    print(f"[Runner][REAL] image_path: {image_path}")
    print(f"[Runner][REAL] option: {option}")
    print(f"[Runner][REAL] request_text: {request_text}")
    print("=" * 70)

    call_progress(
        progress_callback=progress_callback,
        job_id=job_id,
        status="DRAWING",
        status_text="실제 로봇 알고리즘 호출 준비",
        step="3 / 6",
        progress=45,
    )

    algorithm_result = run_doosan_drawing_job(
        job_id=job_id,
        image_path=image_path,
        option=option,
        request_text=request_text,
        progress_callback=progress_callback,
    )

    normalized_result = normalize_algorithm_result(algorithm_result)

    if not normalized_result["success"]:
        raise RuntimeError(
            normalized_result["message"] or "실제 로봇 알고리즘 실행 실패"
        )

    return normalized_result


# =========================
# 외부에서 호출할 메인 작업 함수
# =========================

def run_robot_job(
    command,
    mode="demo",
    progress_callback=None,
):
    """
    listener에서 호출할 메인 함수

    mode:
    - demo: 실제 로봇 없이 가짜 작업 실행
    - real: robot_algorithm_adapter.py에 연결된 실제 로봇 알고리즘 실행

    commandType:
    - drawing만 이 runner에서 실제 처리함.
    - paper / glue / attach는 여기서 실제 드로잉 실행을 차단함.
    """

    if not isinstance(command, dict):
        raise ValueError("command는 dict 형태여야 합니다.")

    mode = str(mode or "demo").strip().lower()

    job_id = command.get("jobId")
    customer_name = command.get("customerName", "-")
    image_url = command.get("imageUrl", "")
    option = command.get("option", "-")
    request_text = command.get("requestText", "")

    raw_command_type = (
        command.get("commandType")
        or command.get("command_type")
        or COMMAND_TYPE_DRAWING
    )
    command_type = get_command_type_from_command(command)

    if not job_id:
        raise ValueError("command에 jobId가 없습니다.")

    # commandType 검증은 imageUrl 검증보다 먼저 한다.
    # 이유:
    # - paper/glue/attach는 원칙적으로 이미지 다운로드/드로잉 runner를 타면 안 됨.
    # - imageUrl 누락 에러보다 commandType 방어가 먼저 보여야 원인 파악이 쉬움.
    if not command_type:
        return make_invalid_command_type_result(
            job_id=job_id,
            raw_command_type=raw_command_type,
            mode=mode,
            customer_name=customer_name,
            option=option,
        )

    if command_type in NON_DRAWING_COMMAND_TYPES:
        return make_blocked_non_drawing_result(
            job_id=job_id,
            command_type=command_type,
            mode=mode,
            customer_name=customer_name,
            option=option,
            request_text=request_text,
        )

    if command_type != COMMAND_TYPE_DRAWING:
        return make_invalid_command_type_result(
            job_id=job_id,
            raw_command_type=raw_command_type,
            mode=mode,
            customer_name=customer_name,
            option=option,
        )

    if not image_url:
        raise ValueError("command에 imageUrl이 없습니다.")

    print("=" * 70)
    print("[Runner] 로봇 작업 실행 준비")
    print(f"[Runner] mode: {mode}")
    print(f"[Runner] command_type: {command_type}")
    print(f"[Runner] job_id: {job_id}")
    print(f"[Runner] customer_name: {customer_name}")
    print(f"[Runner] image_url: {image_url}")
    print(f"[Runner] option: {option}")
    print(f"[Runner] request_text: {request_text}")
    print("=" * 70)

    downloaded_image_path = ""
    normalized_image_url = ""
    converted_image_path = ""
    converted_image_url = ""

    try:
        # 1. 이미지 다운로드 시작
        call_progress(
            progress_callback=progress_callback,
            job_id=job_id,
            status="DRAWING",
            status_text="이미지 다운로드 준비 중",
            step="1 / 6",
            progress=10,
            extra_data={
                "commandType": command_type,
            },
        )

        download_result = download_image(
            image_url=image_url,
            job_id=job_id,
        )

        downloaded_image_path = download_result["downloaded_path"]
        normalized_image_url = download_result["image_url"]

        call_progress(
            progress_callback=progress_callback,
            job_id=job_id,
            status="DRAWING",
            status_text="이미지 다운로드 완료",
            step="2 / 6",
            progress=30,
            extra_data={
                "downloadedImagePath": downloaded_image_path,
                "imageUrl": normalized_image_url,
                "commandType": command_type,
            },
        )

        # 2. 실제 작업 실행
        if mode == "demo":
            algorithm_result = run_demo_robot_algorithm(
                job_id=job_id,
                image_path=downloaded_image_path,
                option=option,
                request_text=request_text,
                progress_callback=progress_callback,
            )

        elif mode == "real":
            algorithm_result = run_real_robot_algorithm(
                job_id=job_id,
                image_path=downloaded_image_path,
                option=option,
                request_text=request_text,
                progress_callback=progress_callback,
            )

        else:
            raise ValueError(f"지원하지 않는 mode입니다: {mode}")

        normalized_result = normalize_algorithm_result(algorithm_result)

        converted_image_path = normalized_result.get("converted_image_path", "")
        converted_image_url = normalized_result.get("converted_image_url", "")

        # 실제 알고리즘이 converted_image_path만 반환하고 URL은 안 준 경우 자동 URL 생성
        converted_result = ensure_converted_image_url(
            job_id=job_id,
            converted_image_path=converted_image_path,
            converted_image_url=converted_image_url,
        )

        converted_image_path = converted_result["converted_image_path"]
        converted_image_url = converted_result["converted_image_url"]

        return make_result(
            success=True,
            job_id=job_id,
            message=normalized_result.get("message", "작업 완료"),
            downloaded_image_path=downloaded_image_path,
            normalized_image_url=normalized_image_url,
            converted_image_path=converted_image_path,
            converted_image_url=converted_image_url,
            extra={
                "mode": mode,
                "commandType": command_type,
                "customerName": customer_name,
                "option": option,
                "algorithmExtra": normalized_result.get("extra", {}),
            },
        )

    except Exception as e:
        error_message = str(e)

        print(f"[Runner][Error] {error_message}")

        return make_result(
            success=False,
            job_id=job_id,
            message="작업 실패",
            downloaded_image_path=downloaded_image_path,
            normalized_image_url=normalized_image_url,
            converted_image_path=converted_image_path,
            converted_image_url=converted_image_url,
            error_message=error_message,
            extra={
                "mode": mode,
                "commandType": command_type,
                "customerName": customer_name,
                "option": option,
            },
        )


# =========================
# 단독 실행 방지
# =========================

if __name__ == "__main__":
    print(
        "robot_job_runner.py는 단독 실행용 파일이 아닙니다.\n"
        "robot_command_listener.py 또는 robot_command_listener_test.py에서 "
        "import해서 사용합니다."
    )