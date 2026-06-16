import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    """
    Flask 관리자/고객 페이지 전체 설정 파일

    주의:
    - Firebase serviceAccountKey.json 파일 내용은 절대 코드에 직접 넣지 말 것
    - serviceAccountKey.json은 GitHub에 올리지 말 것
    """

    # =========================
    # Flask 기본 설정
    # =========================

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

    # 업로드 파일 최대 크기
    # 10MB
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    # =========================
    # 웹 서버 외부 접속 주소 설정
    # =========================
    #
    # 로봇 PC가 고객 업로드 이미지를 다운로드하려면
    # imageUrl이 /static/uploads/... 같은 상대경로가 아니라
    # http://서버PC_IP:5000/static/uploads/... 형태여야 함.
    #
    # 같은 PC에서만 테스트할 때는 http://localhost:5000 으로도 됨.
    # 다른 PC 또는 로봇 PC에서 접근해야 하면 아래 값을 서버 PC IP로 바꿔야 함.
    #
    # 예:
    # PUBLIC_BASE_URL = "http://192.168.0.25:5000"
    #
    # 현재 기본값은 localhost.
    PUBLIC_BASE_URL = os.getenv(
        "PUBLIC_BASE_URL",
        "http://192.168.10.36:5000"
    )

    # =========================
    # Firebase 설정
    # =========================

    FIREBASE_DATABASE_URL = os.getenv(
        "FIREBASE_DATABASE_URL",
        "https://rokey-d-3-default-rtdb.asia-southeast1.firebasedatabase.app"
    )

    # Firebase Admin SDK 서비스 계정 JSON 파일 경로
    # 추천 위치:
    # D3PROJECT/firebase_keys/serviceAccountKey.json
    FIREBASE_SERVICE_ACCOUNT_KEY = "/home/lee/cobot_ws/src/d3project/rokey-d-3-firebase-adminsdk-fbsvc-295356f0b7.json"

    # =========================
    # Firebase DB 경로
    # =========================

    # 로봇 PC가 현재 좌표값을 올리는 경로
    ROBOT_STATUS_PATH = os.getenv("ROBOT_STATUS_PATH", "robot_status")

    # 고객 요청 목록 저장 경로
    REQUESTS_PATH = os.getenv("REQUESTS_PATH", "requests")

    # 현재 로봇 작업 상태 저장 경로
    CURRENT_JOB_PATH = os.getenv("CURRENT_JOB_PATH", "current_job")

    # 관리자 명령 저장 경로
    COMMANDS_PATH = os.getenv("COMMANDS_PATH", "commands")

    # =========================
    # 로봇 연결 상태 판단 기준
    # =========================

    ROBOT_ONLINE_THRESHOLD_SEC = float(
        os.getenv("ROBOT_ONLINE_THRESHOLD_SEC", "3")
    )

    ROBOT_DELAYED_THRESHOLD_SEC = float(
        os.getenv("ROBOT_DELAYED_THRESHOLD_SEC", "10")
    )

    DASHBOARD_REFRESH_INTERVAL_MS = int(
        os.getenv("DASHBOARD_REFRESH_INTERVAL_MS", "1000")
    )

    # =========================
    # 고객 이미지 업로드 설정
    # =========================

    # 원본 이미지 저장 폴더
    CUSTOMER_UPLOAD_FOLDER = os.getenv(
        "CUSTOMER_UPLOAD_FOLDER",
        str(BASE_DIR / "static" / "uploads" / "original")
    )

    # 나중에 이미지 변환 결과 저장할 폴더
    CONVERTED_UPLOAD_FOLDER = os.getenv(
        "CONVERTED_UPLOAD_FOLDER",
        str(BASE_DIR / "static" / "uploads" / "converted")
    )

    # 브라우저에서 접근할 URL 경로
    CUSTOMER_UPLOAD_URL_PREFIX = "/static/uploads/original"
    CONVERTED_UPLOAD_URL_PREFIX = "/static/uploads/converted"

    # 허용할 이미지 확장자
    ALLOWED_IMAGE_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "webp",
        "gif"
    }