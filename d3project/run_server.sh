#!/bin/bash

set -e

# ============================================================
# run_server.sh
#
# Doosan M0609 Flask 웹서버 실행 스크립트
#
# 역할:
# 1. 현재 서버 PC의 IP를 자동 감지
# 2. PUBLIC_BASE_URL을 http://현재IP:5000 으로 자동 설정
# 3. venv 활성화
# 4. python app.py 실행
#
# 사용:
#   ./run_server.sh
#
# 수동 IP 지정:
#   SERVER_IP=192.168.10.36 ./run_server.sh
#
# 수동 PUBLIC_BASE_URL 지정:
#   PUBLIC_BASE_URL=http://192.168.10.36:5000 ./run_server.sh
# ============================================================


# 현재 스크립트가 있는 폴더를 프로젝트 루트로 사용
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"


# ------------------------------------------------------------
# 1. 가상환경 활성화
# ------------------------------------------------------------

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "[WARN] venv 폴더를 찾지 못했습니다."
    echo "[WARN] 가상환경 없이 python app.py를 실행합니다."
fi


# ------------------------------------------------------------
# 2. 서버 IP 자동 감지 함수
# ------------------------------------------------------------

detect_server_ip() {
    # 사용자가 직접 SERVER_IP를 지정한 경우 최우선 사용
    if [ -n "${SERVER_IP:-}" ]; then
        echo "$SERVER_IP"
        return
    fi

    # hostname -I 결과 가져오기
    # 예:
    # 192.168.10.36 172.17.0.1
    IP_LIST="$(hostname -I 2>/dev/null || true)"

    # 1순위: 일반 공유기/와이파이에서 가장 흔한 192.168.x.x
    for ip in $IP_LIST; do
        if [[ "$ip" == 192.168.* ]]; then
            echo "$ip"
            return
        fi
    done

    # 2순위: 10.x.x.x 대역
    for ip in $IP_LIST; do
        if [[ "$ip" == 10.* ]]; then
            echo "$ip"
            return
        fi
    done

    # 3순위: 172.x.x.x 대역
    # 단, Docker 기본 브릿지인 172.17.x.x는 제외
    for ip in $IP_LIST; do
        if [[ "$ip" == 172.* ]] && [[ "$ip" != 172.17.* ]]; then
            echo "$ip"
            return
        fi
    done

    # 마지막 fallback: Python socket으로 기본 네트워크 IP 추정
    python3 - <<'PY'
import socket

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

try:
    # 실제로 데이터를 보내지는 않고, OS가 선택하는 기본 네트워크 IP만 확인
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except Exception:
    print("127.0.0.1")
finally:
    s.close()
PY
}


# ------------------------------------------------------------
# 3. PUBLIC_BASE_URL 자동 설정
# ------------------------------------------------------------

SERVER_PORT="${SERVER_PORT:-5000}"

if [ -z "${PUBLIC_BASE_URL:-}" ]; then
    DETECTED_IP="$(detect_server_ip)"
    export PUBLIC_BASE_URL="http://${DETECTED_IP}:${SERVER_PORT}"
else
    DETECTED_IP="사용자 지정"
fi


# ------------------------------------------------------------
# 4. 실행 정보 출력
# ------------------------------------------------------------

echo "============================================================"
echo "[Doosan M0609 Flask Server]"
echo "PROJECT_DIR      : $PROJECT_DIR"
echo "DETECTED_IP      : $DETECTED_IP"
echo "SERVER_PORT      : $SERVER_PORT"
echo "PUBLIC_BASE_URL  : $PUBLIC_BASE_URL"
echo "============================================================"
echo
echo "[접속 주소]"
echo "내 PC에서 접속:"
echo "  http://127.0.0.1:5000"
echo
echo "다른 PC / 로봇 PC에서 접속:"
echo "  $PUBLIC_BASE_URL"
echo
echo "상태 확인:"
echo "  $PUBLIC_BASE_URL/health"
echo "============================================================"
echo


# ------------------------------------------------------------
# 5. Flask 서버 실행
# ------------------------------------------------------------

python3 app.py