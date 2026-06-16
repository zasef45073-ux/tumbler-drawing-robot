import os
# =========================
# Listener 기본 설정
# 환경변수에서 읽어 상수로 노출한다. 미설정 시 아래 기본값을 사용한다.
# =========================
# commands/start 폴링 주기 (초). 기본 2초.
# 환경변수: ROBOT_LISTENER_POLL_INTERVAL_SEC
POLL_INTERVAL_SEC: float = float(
    os.getenv(
        "ROBOT_LISTENER_POLL_INTERVAL_SEC",
        "2",
    )
)

# commands/control 폴링 주기 (초). stop/pause/resume 응답성에 영향. 기본 0.5초.
# 환경변수: ROBOT_CONTROL_POLL_INTERVAL_SEC
CONTROL_POLL_INTERVAL_SEC: float = float(
    os.getenv(
        "ROBOT_CONTROL_POLL_INTERVAL_SEC",
        "0.5",
    )
)

# 기본 실행 모드: "demo" (로봇 미구동) / "real" (실제 로봇 구동). 기본 "real".
# 환경변수: ROBOT_JOB_MODE
DEFAULT_JOB_MODE: str = os.getenv(
    "ROBOT_JOB_MODE",
    "real",
).lower()

# Doosan 로봇 네임스페이스 ID. ROS2 service 경로(/dsr01/motion/...)에 사용됨. 기본 "dsr01".
# 환경변수: DOOSAN_ROBOT_ID
ROBOT_ID: str = os.getenv(
    "DOOSAN_ROBOT_ID",
    "dsr01",
)
