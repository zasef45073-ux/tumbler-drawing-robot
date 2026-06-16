# 🎨 텀블러 드로잉 & 부착 로봇 시스템

Doosan M0609 협동로봇을 활용해 이미지를 종이에 그린 뒤,
그 종이를 텀블러에 풀칠하여 부착하는 전체 자동화 공정 시스템입니다.
Flask 웹서버 + Firebase + ROS2로 고객 요청부터 로봇 실행까지 전체 파이프라인을 구성했습니다.

## 👤 담당 역할

이 프로젝트는 6인 팀 프로젝트이며, 그중 드로잉(이미지 → 로봇 그리기) 파트는
저를 포함한 2명이 함께 작업했습니다. 제가 주로 담당한 부분은 다음과 같습니다.

- **이미지 전처리** — 엣지 검출, 더블 엣지 아티팩트 보정 (adaptive thresholding + morphological closing)
- **색칠(Fill) 로직** — 윤곽선 내부 영역 채색 처리
- **역기구학(IK) 및 좌표 변환** — 픽셀 좌표 → 로봇 좌표 변환, 캔버스 센터링/축 반전/회전 로직

같은 드로잉 파트의 Bézier 곡선 피팅, 경로 최적화는 함께 작업한 팀원이 담당했고,
그리퍼 픽업·풀칠·부착 동작, Flask/Firebase 서버, 관리자 UI 등은 나머지 팀원들이 담당했습니다.

---

## 📋 목차

1. [통합 플로우 차트](#-통합-플로우-차트)
2. [시스템 아키텍처](#-시스템-아키텍처)
3. [운영체제 환경](#-운영체제-환경)
4. [사용한 장비 목록](#-사용한-장비-목록)
5. [의존성](#-의존성-requirementstxt)
6. [실행 방법](#-실행-방법)

---

## 🔄 통합 플로우 차트

```mermaid
flowchart TB

  subgraph NORMAL["정상 플로우"]
    N1(["고객이 이미지 업로드"])
    N2["서버 PC에 이미지 저장<br/>Firebase에 이미지 URL 업로드"]
    N3["로봇PC 리스너 실행"]
    N4["텀블러 집기"]
    N5["로봇 PC에 이미지 다운로드"]
    N6["경로 계획"]
    N7["UI에 좌표 변환 이미지 출력"]
    N8["펜 집기"]
    N9["윤곽선 그리기"]
    N10["새로운 펜으로 교체"]
    N11["색깔 칠하기"]
    N12["텀블러 위에 풀칠하기"]
    N13["텀블러 위에 종이 올리기"]
    N14["롤링"]
    N15["홈으로 돌아가기"]
    N16(["완료"])

    N1 --> N2
    N2 --> N3
    N3 --> N4
    N4 --> N5
    N5 --> N6
    N6 --> N7
    N7 --> N8
    N8 --> N9
    N9 --> N10
    N10 --> N11
    N11 --> N12
    N12 --> N13
    N13 --> N14
    N14 --> N15
    N15 --> N16
  end

  subgraph EMERGENCY["비상시 플로우"]

    subgraph RED["빨간불"]
      R1{"비상 정지 / 원점<br/>E-Stop / Home 버튼 눌렀을 시"}
      R2["정지"]
      R3["관리자 UI에 신호 보내기"]
      R4{"관리자 UI에서<br/>버튼을 다시 눌렀는가?"}
      R5["대기"]
      R6["이전의 했던 동작을 다시 수행"]

      R1 --> R2
      R2 --> R3
      R3 --> R4
      R4 -- "Yes" --> R6
      R4 -- "No" --> R5
      R5 --> R6
    end

    subgraph YELLOW["노란불"]
      Y1{"노란불 감지"}
      Y2["정지"]
      Y3["관리자 UI에 신호를 보내기"]
      Y4["다시 홈으로 돌아가기"]

      Y1 --> Y2
      Y2 --> Y3
      Y3 --> Y4
    end

  end
```

---

## 🏗️ 시스템 아키텍처

```mermaid
flowchart LR

  subgraph CUSTOMER["고객 UI"]
    C1["이미지 업로드"]
    C2["요청사항 입력"]
    C3["접수번호 확인"]
    C4["제작 상태 조회"]
  end

  subgraph ADMIN["관리자 UI"]
    A1["요청 검수 및 승인"]
    A2["전체 공정 실행"]
    A3["일시정지 / 재개 / 작업 중지"]
    A4["현재 공정 및 진행률 확인"]
    A5["로봇 좌표 확인"]
  end

  FS["Flask 서버"]

  subgraph FB["Firebase Realtime Database"]

    subgraph REQ["requests<br/>고객 요청 및 제작 상태 저장"]
      RQ1["고객 요청 정보"]
      RQ2["이미지 URL"]
      RQ3["제작 상태"]
      RQ4["진행률"]
    end

    subgraph START["commands/start<br/>로봇 공정 시작 명령 저장"]
      ST1["공정 시작 명령"]
      ST2["실행할 공정"]
      ST3["전체 자동 실행 여부"]
      ST4["자동 실행 공정 순서"]
    end

    subgraph CTRL["commands/control<br/>일시정지·재개·작업중지 제어 명령 저장"]
      CT1["pause"]
      CT2["resume"]
      CT3["stop"]
    end

    subgraph JOB["current_job<br/>현재 진행 중인 작업 상태 저장"]
      CJ1["현재 작업 상태"]
      CJ2["현재 공정"]
      CJ3["진행률"]
      CJ4["작업 로그"]
    end

    subgraph STATUS["robot_status<br/>로봇 좌표 및 동작 상태 저장"]
      RS1["J1~J6"]
      RS2["TCP 위치"]
      RS3["로봇 상태"]
    end

  end

  subgraph ROBOTPC["Ubuntu 22.04 로봇 PC"]

    subgraph WATCHER["Firebase 명령 감시"]
      W1["commands/start 확인"]
      W2["commands/control 확인"]
    end

    subgraph MANAGER["공정 실행 관리자"]
      M1["commandType 확인"]
      M2["공정별 파일 실행"]
      M3["완료 후 상태 업데이트"]
      M4["autoRunAll이면 다음 공정 명령 생성"]
    end

    subgraph FILES["공정별 실행 파일"]
      F1["텀블러 놓기<br/>(pick_tumbler.py)"]
      F2["펜 잡기<br/>(grip_pen.py)"]
      F3["드로잉<br/>(draw.py)"]
      F4["펜 놓기<br/>(pen_release.py)"]
      F5["종이 붙이기<br/>(grip_paper.py)"]
      F6["풀 바르기<br/>(pick_glue.py)"]
      F7["롤링 후 원위치<br/>(rolling.py)"]
    end

    subgraph UPDATE["상태 업데이트"]
      U1["공정 상태"]
      U2["진행률"]
      U3["로봇 좌표"]
    end

  end

  subgraph ROBOT["Doosan M0609 로봇팔"]

    R1["로봇 이동 수행"]
    R2["그리퍼 제어"]
    R3["드로잉 수행"]
    R4["Joint 상태 제공"]
    R5["TCP 위치 제공"]

    subgraph CONTROL_LAYER["ROS2 / Doosan 제어 계층"]
      D1["Python 로봇 제어 API"]
      D2["topic / service"]
      D3["dsr_controller2 ROS2 제어 노드"]
      D4["DRFL"]
      D5["Real Robot / Emulator"]
    end

    subgraph ACTUATOR["액추에이터"]
      AC1["move_joint<br/>subscriber: /dsr01/motion/move_joint"]
      AC2["joint_state<br/>publish: /dsr01/joint_states"]
      AC3["move_tcp<br/>subscriber: /dsr01/aux_control/get_current_posx"]
      AC4["tcp_state<br/>publish: /dsr01/aux_control/get_current_posx"]
    end

    subgraph GRIPPER["OnRobot RG2 gripper"]
      G1["gripper_open<br/>publish: /dsr01/io/set_tool_digital_output"]
      G2["gripper_torque<br/>subscribe: /dsr01/force/get_tool_force"]
    end

  end

  C1 --> FS
  C2 --> FS
  C3 --> FS
  C4 --> FS

  A1 --> FS
  A2 --> FS
  A3 --> FS
  A4 --> FS
  A5 --> FS

  FS --> REQ
  FS --> START
  FS --> CTRL

  START --> W1
  CTRL --> W2

  W1 --> M1
  W2 --> M1
  M1 --> M2
  M2 --> FILES
  M3 --> JOB
  M4 --> START

  F1 --> R1
  F2 --> R2
  F3 --> R3
  F4 --> R2
  F5 --> R2
  F6 --> R2
  F7 --> R1

  D1 --> D2
  D2 --> D3
  D3 --> D4
  D4 --> D5

  D5 --> AC1
  D5 --> AC3
  D5 --> G2

  AC2 --> STATUS
  AC4 --> STATUS
  G1 --> STATUS

  ROBOTPC --> UPDATE
  UPDATE --> STATUS
  UPDATE --> JOB

  STATUS --> A5
  JOB --> A4
  REQ --> C4
```

---

## ⚙️ 운영체제 환경

### 서버 PC
- OS: Ubuntu 22.04
- Python: 3.10.12
- Flask: 웹 서버 실행

### 로봇 PC
- OS: Ubuntu 22.04
- ROS2: Humble
- Python: 3.10.12
- 로봇: Doosan M0609

### 공통
- Firebase Realtime Database (asia-southeast1)
- opencv-contrib-python

---

## 🤖 사용한 장비 목록

### 로봇
- Doosan M0609 협동로봇
- 그리퍼: GripperDA_v1

### 컴퓨터
- 서버 PC: Flask 웹 서버 실행용
- 로봇 PC: ROS2 + 로봇 제어용

### 네트워크
- Firebase Realtime Database (Google Cloud, asia-southeast1)

### 기타
- 펜 (black, red)
- 텀블러
- 종이
- 롤러
- 레고
- 목공풀

---

## 📦 의존성 (requirements.txt)

### 서버 PC

firebase-admin

flask

werkzeug

### 로봇 PC

firebase-admin

opencv-contrib-python

numpy

rclpy              # ROS2 (pip 아닌 ROS2 설치로 사용)

cv-bridge          # ROS2 (pip 아닌 ROS2 설치로 사용)

### 공통 설치 명령
```bash
pip install firebase-admin flask werkzeug opencv-contrib-python numpy
```

---

## 🚀 실행 방법

### 1. 서버 PC

```bash
# Firebase 키 경로 설정 확인
# config.py → FIREBASE_SERVICE_ACCOUNT_KEY

# Flask 서버 실행
cd ~/cobot_ws/src/d3project
python3 ./run_server.sh
```

### 2. 로봇 PC

```bash
# ROS2 환경 설정
source /opt/ros/humble/setup.bash
source ~/cobot_ws/install/setup.bash

# 로봇 드라이버 실행 (별도 터미널)
ros2 launch dsr_launcher2 dsr_bringup2.launch.py \
    model:=m0609 mode:=real host:=192.168.137.100

# 로봇 상태 Firebase 업로드 (별도 터미널)
python3 write_to_firebasev2.py

# 리스너 실행 (별도 터미널)
cd ~/cobot_ws/src/d3project
python3 robot_command_listener_pause_resume_auto.py
```

### 3. 실행 순서 요약

1. 서버 PC - Flask 서버 실행
2. 로봇 PC - ROS2 드라이버 실행
3. 로봇 PC - write_to_firebasev2.py 실행
4. 로봇 PC - robot_command_listener 실행
5. 브라우저 - http://서버PC_IP:5000 접속
6. 브라우저 - http://서버PC_IP:5000/admin/dashboard 관리자 접속
