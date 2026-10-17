#!/usr/bin/env bash
# One terminal owns the receiver, sensors and exactly one action entry.
set -eo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

usage() {
    cat <<'EOF'
用法：bash scripts/start_common_live.sh [选项]
启动左臂 A、D435 彩色流、Daimon 腕部 ROI 相机、双指触觉和 wrench，
等待实际反馈，再选择一个动作入口。Ctrl+C 先等待动作保存，再关闭设备。

  --dry-run              仅打印命令，不加载 ROS、不连接设备、不创建目录
  --build                启动前校验 SDK 并构建机器人接收端
  --action MODE          跳过菜单：gamepad / collect / bc / rl-new / rl-resume
  --gamepad PATH         手柄路径（独立操作默认 js1，其他入口默认 js0）
  --bc-run DIR           BC 评估目录 / 新 RL 的 BC 来源目录
  --run DIR              新 RL 目标目录 / 续跑 RL 目录
  --output DIR           人工示范输出目录（默认带时间戳的新目录）
  --no-gripper           禁用手柄、采集、RL 的 A/B 夹爪控制
  --ready-timeout SEC    每个反馈话题的等待秒数，默认 60
  -h, --help             显示帮助

默认 ROS_DOMAIN_ID=13，网络发现 SUBNET；可在运行前设置 ROS_DOMAIN_ID。
机器人 192.168.14.190；夹爪 192.168.14.11:55551；工具参数沿用教程。
夹爪由动作入口连接，不执行归零；现有固定 BC 入口不支持 A/B 夹爪。
启动即连接机器人并切换控制模式，运行前请完成教程中的现场准备。
EOF
}
die() { printf '错误：%s\n' "$*" >&2; exit 1; }
show() { printf '  '; printf '%q ' "$@"; printf '\n'; }
need_value() { [[ $# -ge 2 && -n "$2" ]] || die "$1 需要参数"; }

dry_run=0 build=0 action=menu no_gripper=0 ready_timeout=60
gamepad='' run_dir='' output=''
bc_run=local/bc_episodes/demo_new_20261007_213643_eval_01
resume_default=local/rl_training/bc12045_newdata_30s_20261011_01
stamp="$(date +%Y%m%d_%H%M%S)_$$"
while (($#)); do
    case "$1" in
        --dry-run) dry_run=1; shift ;;
        --build) build=1; shift ;;
        --no-gripper) no_gripper=1; shift ;;
        --action) need_value "$@"; action="$2"; shift 2 ;;
        --gamepad) need_value "$@"; gamepad="$2"; shift 2 ;;
        --bc-run) need_value "$@"; bc_run="$2"; shift 2 ;;
        --run) need_value "$@"; run_dir="$2"; shift 2 ;;
        --output) need_value "$@"; output="$2"; shift 2 ;;
        --ready-timeout) need_value "$@"; ready_timeout="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知选项：$1（参见 --help）" ;;
    esac
done
case "$action" in menu|gamepad|collect|bc|rl-new|rl-resume) ;; *) die "未知动作：$action" ;; esac
[[ "$ready_timeout" =~ ^[1-9][0-9]*$ ]] || die '--ready-timeout 必须为正整数'
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-13}"
export ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_DISTRO="${OMI_ROS_DISTRO:-${ROS_DISTRO:-jazzy}}"
export OMI_ROS_DISTRO="$ROS_DISTRO"
# Match start_daimon_live.sh's network transport across every process.
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
export ARM_SDK_DIR="$root/local/vendor/optical_module_pu/source/OpticalModule_PU/Arm_control"
ros_setup="/opt/ros/$ROS_DISTRO/setup.bash"
receiver_setup="$root/local/ros2/robot_controller_ws/install/local_setup.bash"

robot_cmd=(ros2 launch arm_delta_cmd delta_ctrl.launch.py
    robot_ip:=192.168.14.190 arm:=A connect_on_start:=true motion_authorized:=true
    manual_delta_topic:=/omi/controller_test/decision delta_frame:=base
    ctrl_rate:=200.0 delta_splits:=20 start_mode:=3 calib_mode:=measure
    'tool_xyzabc:=[5.0,0.0,200.0,-180.0,-90.0,0.0]'
    'tool_dynamic_params:=[1.3,0.0,0.0,70.0,0.0,0.0,0.0,0.0,0.0,0.0]'
    publish_root_tf:=none)
camera_cmd=(ros2 launch realsense2_camera rs_launch.py
    camera_namespace:=camera camera_name:=camera enable_color:=true)
wrist_cmd=(bash scripts/start_daimon_live.sh camera --image-mode roi --transport network)
tactile_cmd=(bash scripts/start_daimon_live.sh tactile --transport network --tactile-wrench)

make_action() {
    prepare_cmd=()
    local pad="${gamepad:-/dev/input/js0}"
    local gripper_args=()
    ((no_gripper == 0)) || gripper_args=(--no-gripper)
    case "$action" in
        gamepad)
            action_cmd=("$root/.venv/bin/python" scripts/gamepad_test.py --execute
                --device "${gamepad:-/dev/input/js1}" --rate 10 --home-button-code 314
                --scale 1 --output-convention sdk-x-forward-z-left "${gripper_args[@]}") ;;
        collect)
            action_cmd=(bash scripts/collect_rl_episodes.sh
                --output "${output:-local/rl_episodes/demo_new_$stamp}"
                --episode-seconds 20 --episodes 10 --control-mode periodic --execute
                --gamepad "$pad" "${gripper_args[@]}") ;;
        bc)
            action_cmd=(bash scripts/run_bc_episodes.sh --output "$bc_run"
                --resume --control-mode periodic --episodes 1 --execute --gamepad "$pad") ;;
        rl-new|rl-resume)
            if [[ "$action" == rl-new ]]; then
                selected_run="${run_dir:-local/rl_training/new_run_$stamp}"
                prepare_cmd=(bash scripts/prepare_bc_rl.sh --bc-run "$bc_run"
                    --run "$selected_run" --weights-only --episode-seconds 45
                    --replay-backend cached --cache-target-gib 16 --cache-limit-gib 20
                    --critic-warmup-updates 1000)
            else
                selected_run="${run_dir:-$resume_default}"
            fi
            action_cmd=(bash scripts/run_async_rl.sh --run "$selected_run"
                --actor-device cuda --learner-device cuda --batch-size 64 --publish-every 50
                --reload-every-episodes 10 --min-online 100 --min-demo 100
                --max-updates-per-transition 1 --arbitration-mode after-inference
                --exploration-noise-std 0.05 --exploration-noise-clip 0.15
                --execute --enable-policy --gamepad "$pad" "${gripper_args[@]}"
                --tag-follow-calibration "$root/ros2/marker_detect/handeye_result.json") ;;
    esac
}

if ((dry_run)); then
    printf '预览：不会连接硬件或创建训练任务。工作目录：%s\n' "$root"
    show source "$ros_setup"
    show source "$receiver_setup"
    show export "ARM_SDK_DIR=$ARM_SDK_DIR" "ROS_DOMAIN_ID=$ROS_DOMAIN_ID" \
        ROS_LOCALHOST_ONLY=0 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
    show unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
    if ((build)); then
        show python3 scripts/import_optical_module.py verify
        show bash scripts/robot_controller.sh build
    fi
    show ping -c 3 192.168.14.190
    show "${robot_cmd[@]}"
    show "${camera_cmd[@]}"
    show "${wrist_cmd[@]}"
    show "${tactile_cmd[@]}"
    choices=("$action")
    [[ "$action" != menu ]] || choices=(gamepad collect bc rl-new rl-resume)
    for action in "${choices[@]}"; do
        printf '\n动作入口（实际运行时只选择一种）：%s\n' "$action"
        make_action
        if ((${#prepare_cmd[@]})); then show "${prepare_cmd[@]}"; fi
        show "${action_cmd[@]}"
    done
    printf '\n夹爪由手柄/采集/RL 连接；固定 BC 入口目前无夹爪控制。\n'
    exit 0
fi

[[ -t 0 ]] || die '需要交互终端；仅查看命令请用 --dry-run'
for program in setsid flock timeout ping /usr/bin/python3; do
    command -v "$program" >/dev/null || die "缺少程序：$program"
done
[[ -f "$ros_setup" ]] || die "缺少 ROS 环境：$ros_setup"
[[ -x "$root/.venv/bin/python" ]] || die '缺少 .venv/bin/python'
[[ -x "${OMI_SENSOR_PYTHON:-$root/local/venvs/daimon312/bin/python}" ]] || die '缺少 Daimon Python 环境'
mkdir -p local/common_live
exec 9>local/common_live/launcher.lock
flock -n 9 || die '本项目的一键启动脚本已经在运行'
log_dir="$root/local/common_live/$stamp"
mkdir -p "$log_dir"
printf '设备日志：%s\n' "$log_dir"
service_pids=() service_names=() action_pid='' probe_pid=''

# Background jobs inherit ignored SIGINT from bash. Reset it before exec so
# Ctrl+C forwarding also works for Python actors and their shell wrappers.
spawn=(setsid /usr/bin/python3 -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])')

stop_group() {
    local pid="$1" deadline
    kill -INT -- "-$pid" 2>/dev/null || true
    deadline=$((SECONDS + 10))
    while kill -0 -- "-$pid" 2>/dev/null && ((SECONDS < deadline)); do sleep 0.2; done
    if kill -0 -- "-$pid" 2>/dev/null; then
        kill -TERM -- "-$pid" 2>/dev/null || true
        sleep 1
        kill -KILL -- "-$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}
cleanup() {
    local status=$? i
    trap - EXIT
    trap '' INT TERM HUP
    if [[ -n "$probe_pid" ]]; then stop_group "$probe_pid"; fi
    if [[ -n "$action_pid" ]]; then
        printf '\n正在停止动作入口，等待审计/写盘完成，请保留终端……\n'
        # Signal the actor only: it owns learner shutdown and checkpoint saving.
        kill -INT "$action_pid" 2>/dev/null || true
        wait "$action_pid" 2>/dev/null || true
        stop_group "$action_pid"
    fi
    for ((i=${#service_pids[@]}-1; i>=0; i--)); do
        printf '停止 %s\n' "${service_names[i]}"
        stop_group "${service_pids[i]}"
    done
    printf '本次启动的进程已退出；日志：%s\n' "$log_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if ((build)); then
    python3 scripts/import_optical_module.py verify
    bash scripts/robot_controller.sh build
fi
[[ -f "$receiver_setup" ]] || die '机器人接收端尚未构建，请加 --build 或先运行 robot_controller.sh build'
source "$ros_setup"
source "$receiver_setup"
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
ros2 pkg prefix realsense2_camera >/dev/null || die '缺少 realsense2_camera ROS 包'
ping -c 3 -W 2 192.168.14.190 >"$log_dir/ping.log" 2>&1 || die "机器人网络不可达，查看 $log_dir/ping.log"

start_service() {
    local name="$1"; shift
    printf '启动 %s\n' "$name"
    show "$@"
    "${spawn[@]}" "$@" >"$log_dir/$name.log" 2>&1 9>&- &
    service_pids+=("$!") service_names+=("$name")
}
check_services() {
    local i
    for i in "${!service_pids[@]}"; do
        kill -0 "${service_pids[i]}" 2>/dev/null ||
            die "${service_names[i]} 已退出，查看 $log_dir/${service_names[i]}.log"
    done
}
wait_topic() {
    local topic="$1" message_type=sensor_msgs/msg/Image
    case "$topic" in
        /tj/info/eef_left) message_type=geometry_msgs/msg/PoseStamped ;;
        */wrench) message_type=geometry_msgs/msg/WrenchStamped ;;
    esac
    printf '等待数据：%s\n' "$topic"
    "${spawn[@]}" timeout --signal=INT --kill-after=3 "$ready_timeout" \
        ros2 topic echo "$topic" "$message_type" --once --no-arr --qos-reliability best_effort \
        >>"$log_dir/readiness.log" 2>&1 9>&- &
    probe_pid=$!
    while kill -0 "$probe_pid" 2>/dev/null; do check_services; sleep 0.2; done
    if wait "$probe_pid"; then
        probe_pid=''
    else
        stop_group "$probe_pid"
        probe_pid=''
        die "未收到 $topic 数据，查看 $log_dir/readiness.log 及设备日志"
    fi
}
start_service robot "${robot_cmd[@]}"
start_service d435 "${camera_cmd[@]}"
start_service wrist "${wrist_cmd[@]}"
start_service tactile "${tactile_cmd[@]}"
for topic in /tj/info/eef_left /camera/camera/color/image_raw /omi/wrist/color/image_roi \
    /omi/tactile_grid24x16/{a,b}/{deformation,shear,depth,wrench}; do
    wait_topic "$topic"
done
check_services
printf '\n机器人反馈和三路传感器已有数据。\n'

read_value() {
    local prompt="$1" default="$2" reply
    check_services
    IFS= read -r -e -p "$prompt [$default]：" reply || die '终端输入已关闭'
    check_services
    REPLY="${reply:-$default}"
}
if [[ "$action" == menu ]]; then
    printf '%s\n' '1) 独立手柄 + 夹爪' '2) 人工示范采集 + 夹爪' \
        '3) 固定 BC 评估（现有入口不控制夹爪）' '4) 从 BC 新建在线 RL + 夹爪' \
        '5) 继续已有在线 RL + 夹爪' '0) 关闭设备并退出'
    while [[ "$action" == menu ]]; do
        read_value '选择动作入口' 0
        case "$REPLY" in
            1) action=gamepad ;; 2) action=collect ;; 3) action=bc ;;
            4) action=rl-new ;; 5) action=rl-resume ;; 0) exit 0 ;;
            *) printf '请输入 0–5。\n' ;;
        esac
    done
    if [[ -z "$gamepad" ]]; then
        pad_default=/dev/input/js0
        [[ "$action" != gamepad ]] || pad_default=/dev/input/js1
        read_value '手柄设备' "$pad_default"; gamepad="$REPLY"
    fi
    case "$action" in
        bc|rl-new) read_value 'BC 目录' "$bc_run"; bc_run="$REPLY" ;;
    esac
    case "$action" in
        rl-new) read_value '新 RL 目录' "${run_dir:-local/rl_training/new_run_$stamp}"; run_dir="$REPLY" ;;
        rl-resume) read_value '续跑 RL 目录' "${run_dir:-$resume_default}"; run_dir="$REPLY" ;;
        collect) read_value '采集输出目录' "${output:-local/rl_episodes/demo_new_$stamp}"; output="$REPLY" ;;
    esac
fi
make_action
pad="${gamepad:-/dev/input/js0}"
[[ "$action" != gamepad ]] || pad="${gamepad:-/dev/input/js1}"
[[ -r "$pad" ]] || die "手柄不可读：$pad；用 --gamepad 指定实际设备"
case "$action" in
    bc|rl-new|rl-resume)
        [[ -x local/cuda-env/bin/python ]] || die '缺少 local/cuda-env/bin/python' ;;
esac
case "$action" in
    bc|rl-new)
        [[ -f "$bc_run/actor.pt" && -f "$bc_run/config.json" ]] || die "BC 目录缺少 actor.pt/config.json：$bc_run" ;;
esac
if [[ "$action" == rl-resume ]]; then
    for file in config.json async_session.json actor.pt; do
        [[ -f "$selected_run/$file" ]] || die "续跑任务缺少 $selected_run/$file"
    done
fi
if [[ "$action" == rl-new ]]; then
    [[ ! -e "$selected_run" ]] || die "新 RL 目录已存在：$selected_run；续跑请选择 rl-resume"
fi

run_owned_command() {
    local finished='' status=0
    check_services
    show "$@"
    # Explicit stdin inheritance keeps gamepad_test.py's Enter prompt usable.
    "${spawn[@]}" "$@" <&0 9>&- &
    action_pid=$!
    wait -n -p finished "$action_pid" "${service_pids[@]}" || status=$?
    if [[ "$finished" != "$action_pid" ]]; then
        die '设备进程在运行中退出；正在停止动作入口，请检查设备日志'
    fi
    stop_group "$action_pid"
    action_pid=''
    return "$status"
}
if ((${#prepare_cmd[@]})); then
    printf '初始化新 RL 目录：%s\n' "$selected_run"
    run_owned_command "${prepare_cmd[@]}"
fi
printf '\n启动动作入口：%s（Ctrl+C 结束本次整套会话）\n' "$action"
if [[ "$action" == bc ]]; then
    printf '固定 BC 入口未实现夹爪控制；不要同时另开手柄动作发布端。\n'
elif ((no_gripper)); then
    printf 'A/B 夹爪已禁用。\n'
else
    printf '由动作入口连接 Daimon 夹爪：A 闭合 / B 张开。\n'
fi
run_owned_command "${action_cmd[@]}"
