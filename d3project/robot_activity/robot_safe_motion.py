#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
robot_safe_motion.py

robot_activity 전용 Safe Motion 공통 모듈.

역할:
- Doosan M0609 로봇 공정 파일에서 공통으로 사용할 안전 모션 래퍼
- amovej / amovel / amovec + check_motion() 대기 구조 유지
- 대기 중 get_robot_state()로 Safe Stop(노란불, state=5) 감지
- Safe Stop 감지 시:
    1) Firebase current_job / robot_status / requests/{jobId}에 안전정지 표시
    2) countdown_sec초 카운트다운
    3) drl_script_stop(DR_QSTOP_STO)
    4) SetRobotControl(2)로 Safe Stop Reset
    5) STATE_STANDBY(1) 복구 확인
    6) 끊긴 motion target 재전송
- Emergency Stop(빨간불, state=6)은 자동 복구하지 않고 예외 발생

중요:
- 이 파일은 d3project/robot_activity/ 안에 둔다.
- pick_tumbler.py, pen_grip.py, pen_release.py, paper_grip.py, rolling.py에서
  from robot_safe_motion import SafeMotionContext
  형태로 import하는 것을 기준으로 한다.
- robot_activity 폴더 안에서 직접 실행되는 구조를 기준으로 한다.
- config.py는 d3project 루트에 있으므로 parent path를 sys.path에 추가한다.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional


# ============================================================
# robot_activity 전용 경로 설정
# ============================================================

ROBOT_ACTIVITY_DIR = Path(__file__).resolve().parent
D3PROJECT_DIR = ROBOT_ACTIVITY_DIR.parent

# robot_activity 안에서 실행해도 d3project/config.py를 import할 수 있게 한다.
if str(D3PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(D3PROJECT_DIR))


# ============================================================
# 기본 설정
# ============================================================

DEFAULT_ROBOT_ID = os.getenv("ROBOT_ID", "dsr01")

STATE_INITIALIZING = 0
STATE_STANDBY = 1
STATE_MOVING = 2
STATE_SAFE_OFF = 3
STATE_TEACHING = 4
STATE_SAFE_STOP = 5
STATE_EMERGENCY_STOP = 6
STATE_HOMING = 7
STATE_RECOVERY = 8
STATE_SAFE_STOP2 = 9
STATE_SAFE_OFF2 = 10
STATE_NOT_READY = 15

CONTROL_RESET_SAFE_STOP = 2
CONTROL_RESET_SAFE_OFF = 3

DEFAULT_SAFE_STOP_COUNTDOWN_SEC = int(
    os.getenv("ROBOT_SAFE_STOP_COUNTDOWN_SEC", "5")
)

DEFAULT_MAX_RECOVERY_PER_MOTION = int(
    os.getenv("ROBOT_SAFE_STOP_MAX_RECOVERY_PER_MOTION", "2")
)

DEFAULT_WAIT_INTERVAL_SEC = float(
    os.getenv("ROBOT_MOTION_WAIT_INTERVAL_SEC", "0.05")
)

DEFAULT_FIRST_WAIT_SEC = float(
    os.getenv("ROBOT_MOTION_FIRST_WAIT_SEC", "0.10")
)

DEFAULT_SET_CONTROL_TIMEOUT_SEC = float(
    os.getenv("ROBOT_SAFE_STOP_SET_CONTROL_TIMEOUT_SEC", "5.0")
)

DEFAULT_STANDBY_WAIT_TIMEOUT_SEC = float(
    os.getenv("ROBOT_SAFE_STOP_STANDBY_TIMEOUT_SEC", "10.0")
)


ROBOT_STATE_TEXT = {
    STATE_INITIALIZING: "STATE_INITIALIZING",
    STATE_STANDBY: "STATE_STANDBY",
    STATE_MOVING: "STATE_MOVING",
    STATE_SAFE_OFF: "STATE_SAFE_OFF",
    STATE_TEACHING: "STATE_TEACHING",
    STATE_SAFE_STOP: "STATE_SAFE_STOP",
    STATE_EMERGENCY_STOP: "STATE_EMERGENCY_STOP",
    STATE_HOMING: "STATE_HOMING",
    STATE_RECOVERY: "STATE_RECOVERY",
    STATE_SAFE_STOP2: "STATE_SAFE_STOP2",
    STATE_SAFE_OFF2: "STATE_SAFE_OFF2",
    STATE_NOT_READY: "STATE_NOT_READY",
}


# ============================================================
# Firebase optional updater
# ============================================================

class FirebaseSafetyUpdater:
    """
    Firebase 안전정지 표시용 updater.

    공정 파일이 Firebase 초기화를 따로 하지 않아도,
    가능한 경우 여기서 Firebase Admin SDK를 초기화해서
    current_job / robot_status / requests/{jobId}에 안전정지 상태를 올린다.

    Firebase 초기화 실패 시:
    - 로봇 복구 기능은 계속 동작
    - DB 업데이트만 skip
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self._ready = False
        self._db = None
        self._config = None
        self._init_attempted = False

    def _init(self) -> bool:
        if not self.enabled:
            return False

        if self._ready:
            return True

        if self._init_attempted:
            return False

        self._init_attempted = True

        try:
            import firebase_admin
            from firebase_admin import credentials
            from firebase_admin import db

            from config import Config

            if not firebase_admin._apps:
                cred = credentials.Certificate(Config.FIREBASE_SERVICE_ACCOUNT_KEY)
                firebase_admin.initialize_app(
                    cred,
                    {
                        "databaseURL": Config.FIREBASE_DATABASE_URL,
                    },
                )

            self._db = db
            self._config = Config
            self._ready = True

            print("[SafeMotion][Firebase] 초기화 완료")
            return True

        except Exception as e:
            print(f"[SafeMotion][Firebase][WARN] 초기화 실패, DB 업데이트 생략: {e}")
            self._ready = False
            return False

    def update_current_job(self, data: dict[str, Any]) -> None:
        if not self._init():
            return

        try:
            self._db.reference(self._config.CURRENT_JOB_PATH).update(data)
        except Exception as e:
            print(f"[SafeMotion][Firebase][WARN] current_job 업데이트 실패: {e}")

    def update_robot_status(self, data: dict[str, Any]) -> None:
        if not self._init():
            return

        try:
            self._db.reference(self._config.ROBOT_STATUS_PATH).update(data)
        except Exception as e:
            print(f"[SafeMotion][Firebase][WARN] robot_status 업데이트 실패: {e}")

    def update_request(self, job_id: str, data: dict[str, Any]) -> None:
        if not job_id:
            return

        if not self._init():
            return

        try:
            path = f"{self._config.REQUESTS_PATH}/{job_id}"
            self._db.reference(path).update(data)
        except Exception as e:
            print(f"[SafeMotion][Firebase][WARN] request 업데이트 실패: {e}")


# ============================================================
# Safe Stop recovery context
# ============================================================

class SafeMotionContext:
    """
    Safe Stop 자동 복구가 포함된 motion 실행 context.

    공정 파일 사용 예:

        safe = SafeMotionContext(
            robot_id="dsr01",
            job_id=os.getenv("ROBOT_JOB_ID", ""),
            command_type="tumbler_place",
            command_label="텀블러 놓기",
        )

        safe.safe_amovej("j_01", j_01, vel=30, acc=50)
        safe.safe_amovel("p_01", p_01, vel=100, acc=200)
    """

    def __init__(
        self,
        robot_id: str = DEFAULT_ROBOT_ID,
        job_id: str = "",
        command_type: str = "",
        command_label: str = "",
        countdown_sec: int = DEFAULT_SAFE_STOP_COUNTDOWN_SEC,
        max_recovery_per_motion: int = DEFAULT_MAX_RECOVERY_PER_MOTION,
        firebase_enabled: bool = True,
    ) -> None:
        self.robot_id = str(robot_id or DEFAULT_ROBOT_ID).strip()
        self.job_id = str(job_id or "").strip()
        self.command_type = str(command_type or "").strip()
        self.command_label = str(command_label or "").strip()

        self.countdown_sec = int(countdown_sec)
        self.max_recovery_per_motion = int(max_recovery_per_motion)

        self.firebase = FirebaseSafetyUpdater(enabled=firebase_enabled)

    # --------------------------------------------------------
    # Basic state helpers
    # --------------------------------------------------------

    def get_robot_state(self) -> int:
        from DSR_ROBOT2 import get_robot_state

        try:
            state = get_robot_state()
            return int(state)
        except Exception as e:
            print(f"[SafeMotion][WARN] get_robot_state 실패: {e}")
            return -1

    def get_robot_state_text(self, state_code: int) -> str:
        try:
            clean_code = int(state_code)
        except Exception:
            return f"UNKNOWN_STATE_{state_code}"

        return ROBOT_STATE_TEXT.get(clean_code, f"UNKNOWN_STATE_{clean_code}")

    def _now_ts(self) -> float:
        return time.time()

    def _now_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # --------------------------------------------------------
    # Firebase status helpers
    # --------------------------------------------------------

    def publish_safety_status(
        self,
        *,
        status: str,
        status_text: str,
        message: str,
        state_code: int,
        countdown: Optional[int] = None,
        motion_label: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        now = self._now_text()
        state_text = self.get_robot_state_text(state_code)

        base_data: dict[str, Any] = {
            "status": status,
            "statusText": status_text,
            "safetyMessage": message,
            "safetyState": status,
            "safetyCountdown": countdown,
            "robotStateCode": state_code,
            "robotStateText": state_text,
            "safeStopMotionLabel": motion_label,
            "safeStopUpdatedAt": now,
            "updatedAt": now,
            "commandType": self.command_type,
            "commandLabel": self.command_label,
        }

        if self.job_id:
            base_data["jobId"] = self.job_id

        if extra:
            base_data.update(extra)

        robot_status_data = {
            "state": status,
            "stateText": status_text,
            "safetyMessage": message,
            "safetyState": status,
            "safetyCountdown": countdown,
            "robotStateCode": state_code,
            "robotStateText": state_text,
            "safeStopMotionLabel": motion_label,
            "safeStopUpdatedAt": now,
            "last_update_timestamp": self._now_ts(),
            "currentJobId": self.job_id,
            "currentCommandType": self.command_type,
        }

        self.firebase.update_current_job(base_data)
        self.firebase.update_robot_status(robot_status_data)

        if self.job_id:
            request_data = {
                "status": status,
                "statusText": status_text,
                "safetyMessage": message,
                "safetyState": status,
                "safetyCountdown": countdown,
                "robotStateCode": state_code,
                "robotStateText": state_text,
                "safeStopMotionLabel": motion_label,
                "updatedAt": now,
                "currentCommandType": self.command_type,
                "currentCommandLabel": self.command_label,
            }

            self.firebase.update_request(self.job_id, request_data)

    # --------------------------------------------------------
    # SetRobotControl service
    # --------------------------------------------------------

    def call_set_robot_control(
        self,
        control_value: int,
        timeout_sec: float = DEFAULT_SET_CONTROL_TIMEOUT_SEC,
    ) -> bool:
        """
        /dsr01/system/set_robot_control 호출.

        control_value:
        - 2: Safe Stop Reset
        - 3: Safe Off -> Servo On

        중요:
        - 클래스 내부에서 DR_init.__dsr__node를 직접 읽지 않는다.
        - 반드시 getattr(DR_init, "__dsr__node", None)을 사용한다.
        """

        import rclpy
        import DR_init
        from dsr_msgs2.srv import SetRobotControl

        node = getattr(DR_init, "__dsr__node", None)

        if node is None:
            print("[SafeMotion][ERROR] DR_init.__dsr__node가 없습니다.")
            return False

        srv_name = f"/{self.robot_id}/system/set_robot_control"
        client = node.create_client(SetRobotControl, srv_name)

        if not client.wait_for_service(timeout_sec=1.0):
            print(f"[SafeMotion][ERROR] 서비스를 찾을 수 없습니다: {srv_name}")
            return False

        request = SetRobotControl.Request()
        request.robot_control = int(control_value)

        print(
            f"[SafeMotion][SetRobotControl] service={srv_name}, "
            f"robot_control={control_value}"
        )

        future = client.call_async(request)
        start_time = time.time()

        while not future.done():
            rclpy.spin_once(node, timeout_sec=0.01)

            if time.time() - start_time > float(timeout_sec):
                print("[SafeMotion][ERROR] SetRobotControl 호출 시간 초과")
                return False

        try:
            response = future.result()
            return bool(response.success)

        except Exception as e:
            print(f"[SafeMotion][ERROR] SetRobotControl 호출 실패: {e}")
            return False

    # --------------------------------------------------------
    # Safe Stop recovery
    # --------------------------------------------------------

    def recover_safe_stop(self, motion_label: str = "") -> bool:
        """
        노란불 Safe Stop(state=5) 복구.

        흐름:
        1. Firebase/터미널에 안전정지 감지 표시
        2. countdown_sec초 카운트다운
        3. drl_script_stop(DR_QSTOP_STO)
        4. SetRobotControl(2)
        5. STATE_STANDBY(1) 복구 확인
        """

        print("\n" + "!" * 70)
        print("[SafeMotion][SAFE_STOP] 노란불 안전정지 감지")
        print(f"[SafeMotion][SAFE_STOP] motion_label: {motion_label}")
        print("!" * 70)

        self.publish_safety_status(
            status="SAFE_STOP_RECOVERING",
            status_text="안전 정지 감지",
            message=f"안전 정지가 감지되었습니다. {self.countdown_sec}초 후 복구를 시도합니다.",
            state_code=STATE_SAFE_STOP,
            countdown=self.countdown_sec,
            motion_label=motion_label,
        )

        for remaining in range(self.countdown_sec, 0, -1):
            print(f"[SafeMotion][SAFE_STOP] {remaining}초 후 복구 시도")

            self.publish_safety_status(
                status="SAFE_STOP_RECOVERING",
                status_text="안전 정지 감지",
                message=f"안전 정지가 감지되었습니다. {remaining}초 후 복구를 시도합니다.",
                state_code=STATE_SAFE_STOP,
                countdown=remaining,
                motion_label=motion_label,
            )

            time.sleep(1.0)

        self.publish_safety_status(
            status="SAFE_STOP_RECOVERING",
            status_text="안전 정지 복구 중",
            message="안전 정지 복구 명령을 전송합니다.",
            state_code=STATE_SAFE_STOP,
            countdown=0,
            motion_label=motion_label,
        )

        try:
            from DSR_ROBOT2 import drl_script_stop, DR_QSTOP_STO

            print("[SafeMotion][SAFE_STOP] drl_script_stop(DR_QSTOP_STO)")
            drl_script_stop(DR_QSTOP_STO)

        except Exception as e:
            print(f"[SafeMotion][SAFE_STOP][WARN] drl_script_stop 실패 또는 생략: {e}")

        time.sleep(0.5)

        ok = self.call_set_robot_control(CONTROL_RESET_SAFE_STOP)

        if not ok:
            self.publish_safety_status(
                status="SAFE_STOP_RECOVERY_FAILED",
                status_text="안전 정지 복구 실패",
                message="SetRobotControl(2) 호출에 실패했습니다.",
                state_code=self.get_robot_state(),
                countdown=0,
                motion_label=motion_label,
            )
            return False

        print("[SafeMotion][SAFE_STOP] SetRobotControl(2) 전송 완료")
        print("[SafeMotion][SAFE_STOP] STANDBY 복구 확인 중")

        recovered = self.wait_until_standby(
            timeout_sec=DEFAULT_STANDBY_WAIT_TIMEOUT_SEC,
            motion_label=motion_label,
        )

        if not recovered:
            self.publish_safety_status(
                status="SAFE_STOP_RECOVERY_FAILED",
                status_text="안전 정지 복구 실패",
                message="SetRobotControl(2) 후 STATE_STANDBY 복구 확인에 실패했습니다.",
                state_code=self.get_robot_state(),
                countdown=0,
                motion_label=motion_label,
            )
            return False

        self.publish_safety_status(
            status="SAFE_STOP_RECOVERED",
            status_text="안전 정지 복구 완료",
            message="안전 정지가 해제되어 작업을 이어서 진행합니다.",
            state_code=STATE_STANDBY,
            countdown=0,
            motion_label=motion_label,
        )

        print("[SafeMotion][SAFE_STOP] 복구 완료: STATE_STANDBY")
        return True

    def wait_until_standby(
        self,
        timeout_sec: float = DEFAULT_STANDBY_WAIT_TIMEOUT_SEC,
        motion_label: str = "",
    ) -> bool:
        deadline = time.time() + float(timeout_sec)

        while time.time() <= deadline:
            state = self.get_robot_state()
            state_text = self.get_robot_state_text(state)

            if state == STATE_STANDBY:
                return True

            print(f"[SafeMotion][SAFE_STOP] STANDBY 대기 중: {state} {state_text}")

            self.publish_safety_status(
                status="SAFE_STOP_RECOVERING",
                status_text="안전 정지 복구 확인 중",
                message=f"로봇 대기 상태 복구 확인 중입니다. 현재 상태: {state} {state_text}",
                state_code=state,
                countdown=0,
                motion_label=motion_label,
            )

            time.sleep(0.5)

        return False

    # --------------------------------------------------------
    # Motion wait / execute
    # --------------------------------------------------------

    def wait_motion_done(self, label: str = "motion") -> str:
        """
        amovej/amovel/amovec 이후 해당 motion이 끝날 때까지 대기한다.

        반환:
        - "done": 정상 완료
        - "safe_stop": STATE_SAFE_STOP 감지
        - "emergency_stop": STATE_EMERGENCY_STOP 감지
        """

        from DSR_ROBOT2 import check_motion, wait

        print(f"[SafeMotion][WAIT] {label} 완료 대기 시작")

        wait(DEFAULT_FIRST_WAIT_SEC)

        while True:
            state = self.get_robot_state()

            if state == STATE_SAFE_STOP:
                print(f"[SafeMotion][WAIT] {label} 중 Safe Stop 감지")
                return "safe_stop"

            if state == STATE_EMERGENCY_STOP:
                print(f"[SafeMotion][WAIT] {label} 중 Emergency Stop 감지")
                return "emergency_stop"

            motion_state = check_motion()

            if motion_state == 0:
                print(f"[SafeMotion][WAIT] {label} 완료 확인")
                return "done"

            wait(DEFAULT_WAIT_INTERVAL_SEC)

    def _execute_motion_with_recovery(
        self,
        *,
        label: str,
        motion_type: str,
        send_motion: Callable[[], None],
    ) -> None:
        recovery_count = 0

        while True:
            print(f"[SafeMotion][{motion_type}] {label} start")
            send_motion()

            wait_result = self.wait_motion_done(label)

            if wait_result == "done":
                print(f"[SafeMotion][{motion_type}] {label} done")
                return

            if wait_result == "emergency_stop":
                message = (
                    f"{label} 이동 중 Emergency Stop이 감지되었습니다. "
                    "빨간불은 자동 복구하지 않습니다."
                )

                self.publish_safety_status(
                    status="EMERGENCY_STOP_DETECTED",
                    status_text="비상정지 감지",
                    message=message,
                    state_code=STATE_EMERGENCY_STOP,
                    countdown=None,
                    motion_label=label,
                )

                raise RuntimeError(message)

            if wait_result == "safe_stop":
                recovery_count += 1

                if recovery_count > self.max_recovery_per_motion:
                    message = (
                        f"{label} 이동 중 Safe Stop 복구 횟수 초과 "
                        f"({self.max_recovery_per_motion}회)"
                    )

                    self.publish_safety_status(
                        status="SAFE_STOP_RECOVERY_FAILED",
                        status_text="안전 정지 복구 실패",
                        message=message,
                        state_code=STATE_SAFE_STOP,
                        countdown=0,
                        motion_label=label,
                    )

                    raise RuntimeError(message)

                ok = self.recover_safe_stop(motion_label=label)

                if not ok:
                    message = f"{label} 이동 중 Safe Stop 복구 실패"

                    self.publish_safety_status(
                        status="SAFE_STOP_RECOVERY_FAILED",
                        status_text="안전 정지 복구 실패",
                        message=message,
                        state_code=self.get_robot_state(),
                        countdown=0,
                        motion_label=label,
                    )

                    raise RuntimeError(message)

                print(
                    f"[SafeMotion][{motion_type}] {label} "
                    f"복구 완료, 같은 target 재전송"
                )
                continue

            raise RuntimeError(f"{label} 알 수 없는 wait_result: {wait_result}")

    # --------------------------------------------------------
    # Public safe motion wrappers
    # --------------------------------------------------------

    def safe_amovej(
        self,
        label: str,
        target,
        vel: float,
        acc: float,
    ) -> None:
        from DSR_ROBOT2 import amovej

        def send_motion() -> None:
            amovej(target, vel=vel, acc=acc)

        self._execute_motion_with_recovery(
            label=label,
            motion_type="AMOVEJ",
            send_motion=send_motion,
        )

    def safe_amovel(
        self,
        label: str,
        target,
        vel: float,
        acc: float,
        ref=None,
    ) -> None:
        from DSR_ROBOT2 import amovel, DR_BASE

        if ref is None:
            ref = DR_BASE

        def send_motion() -> None:
            amovel(target, vel=vel, acc=acc, ref=ref)

        self._execute_motion_with_recovery(
            label=label,
            motion_type="AMOVEL",
            send_motion=send_motion,
        )

    def safe_amovec(
        self,
        label: str,
        via,
        target,
        vel: float,
        acc: float,
        ref=None,
    ) -> None:
        from DSR_ROBOT2 import amovec, DR_BASE

        if ref is None:
            ref = DR_BASE

        def send_motion() -> None:
            amovec(via, target, vel=vel, acc=acc, ref=ref)

        self._execute_motion_with_recovery(
            label=label,
            motion_type="AMOVEC",
            send_motion=send_motion,
        )