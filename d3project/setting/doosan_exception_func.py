
from command_type_and_status_const import (
    CONTROL_ACTION_PAUSE,
    CONTROL_ACTION_RESUME,
)
from common_util_func import normalize_control_action
from listener_path_const import ROBOT_ID

# =========================
# Doosan motion pause / resume service
# ROS2 dsr_msgs2 서비스를 직접 호출해 로봇의 동작을 일시정지/재개한다.
# pause 시 subprocess를 죽이지 않아야 이후 resume이 가능하다.
# =========================
def call_robot_motion_service(action: str) -> dict:
    """
    Doosan ROS2 motion pause/resume service를 호출한다.

    pausee.py에서 검증한 방식과 동일하게, listener가 웹 control 명령을
    받으면 /dsr01/motion/move_pause 또는 /dsr01/motion/move_resume을
    직접 호출한다.

    input:  action="pause" | "resume"
    output: {"success": True, "action": "pause", "serviceName": "/dsr01/motion/move_pause"}
    raises: ValueError — pause/resume 이외의 action
            RuntimeError — service 연결 실패 또는 success=False 응답

    주의:
    - pause/resume 때 subprocess를 죽이면 이어서 재개할 수 없다.
    - 실제 로봇 공정 파일은 amovej/amovel/amovec + check_motion() 대기
      패턴으로 작성되어 있어야 중간 pause/resume 후 계속 진행된다.
    """

    # "pause"/"resume" 문자열을 정규화 (대소문자·공백 처리)
    clean_action = normalize_control_action(action)

    if clean_action == CONTROL_ACTION_PAUSE:
        try:
            # dsr_msgs2는 ROS2 워크스페이스를 source한 환경에서만 임포트 가능
            from dsr_msgs2.srv import MovePause as ServiceType  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "dsr_msgs2 패키지를 찾을 수 없습니다. "
                "ROS2 워크스페이스가 source 되었는지 확인하세요: "
                "source ~/ros2_ws/install/setup.bash"
            )
        service_name = f"/{ROBOT_ID}/motion/move_pause"
        node_name = "listener_move_pause_client"

    elif clean_action == CONTROL_ACTION_RESUME:
        try:
            # dsr_msgs2는 ROS2 워크스페이스를 source한 환경에서만 임포트 가능
            from dsr_msgs2.srv import MoveResume as ServiceType  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "dsr_msgs2 패키지를 찾을 수 없습니다. "
                "ROS2 워크스페이스가 source 되었는지 확인하세요: "
                "source ~/ros2_ws/install/setup.bash"
            )
        service_name = f"/{ROBOT_ID}/motion/move_resume"
        node_name = "listener_move_resume_client"

    else:
        # pause/resume 이외의 action은 이 함수로 처리하지 않는다
        raise ValueError(f"motion service로 처리할 수 없는 action입니다: {action}")

    # rclpy는 ROS2 환경에서만 사용 가능하므로 지연 임포트
    import rclpy

    print("=" * 70)
    print("[Listener][MotionService] Doosan motion service 호출")
    print(f"[Listener][MotionService] action : {clean_action}")
    print(f"[Listener][MotionService] service: {service_name}")
    print("=" * 70)

    # ROS2 컨텍스트 초기화 및 일회용 클라이언트 노드 생성
    rclpy.init(args=None)
    node = rclpy.create_node(node_name, namespace=ROBOT_ID)

    try:
        client = node.create_client(ServiceType, service_name)

        # 서비스가 올라올 때까지 최대 3초 대기
        if not client.wait_for_service(timeout_sec=3.0):
            raise RuntimeError(f"서비스를 찾을 수 없습니다: {service_name}")

        request = ServiceType.Request()
        future = client.call_async(request)
        # future가 완료될 때까지 이벤트 루프를 블로킹으로 spin
        rclpy.spin_until_future_complete(node, future)

        response = future.result()

        # spin 도중 예외가 발생하면 result()가 None을 반환할 수 있다
        if response is None:
            raise RuntimeError(f"{clean_action} service 응답이 없습니다.")

        # response.success 필드가 없는 서비스 타입도 안전하게 처리
        success = bool(getattr(response, "success", False))

        print("=" * 70)
        print("[Listener][MotionService] 응답 수신")
        print(f"[Listener][MotionService] action : {clean_action}")
        print(f"[Listener][MotionService] success: {success}")
        print("=" * 70)

        if not success:
            raise RuntimeError(f"{clean_action} service success=False")

        return {
            "success": success,
            "action": clean_action,
            "serviceName": service_name,
        }

    finally:
        # 호출 후 반드시 노드·컨텍스트를 정리해 rclpy 재초기화를 허용한다
        node.destroy_node()
        rclpy.shutdown()


def call_robot_pause() -> dict:
    # move_pause service를 호출한다.
    # input:  없음
    # output: {"success": True, "action": "pause", "serviceName": "/dsr01/motion/move_pause"}
    return call_robot_motion_service(CONTROL_ACTION_PAUSE)


def call_robot_resume() -> dict:
    # move_resume service를 호출한다.
    # input:  없음
    # output: {"success": True, "action": "resume", "serviceName": "/dsr01/motion/move_resume"}
    return call_robot_motion_service(CONTROL_ACTION_RESUME)
