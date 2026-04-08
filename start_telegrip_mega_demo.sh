#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set +u
source /opt/ros/humble/setup.bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate teleop
set -u

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ -n "${STACK_PID:-}" ]] && kill -0 "${STACK_PID}" >/dev/null 2>&1; then
    kill "${STACK_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${MEGA_PID:-}" ]] && kill -0 "${MEGA_PID}" >/dev/null 2>&1; then
    kill "${MEGA_PID}" >/dev/null 2>&1 || true
  fi
  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

echo "[telegrip-mega-demo] starting base VR ROS2 stack (without RViz)"
bash "${SCRIPT_DIR}/start_telegrip_ros2_stack.sh" --no-rviz &
STACK_PID=$!

sleep 4

echo "[telegrip-mega-demo] starting Mega MoveIt + RViz stack"
bash "${SCRIPT_DIR}/start_mega_moveit_teleop.sh" &
MEGA_PID=$!

echo
echo "[telegrip-mega-demo] startup complete"
echo "[telegrip-mega-demo] press Ctrl+C to stop both stacks"
echo "[telegrip-mega-demo] run calibration when ready:"
echo "  source /opt/ros/humble/setup.bash"
echo "  source /home/andy/teleOp/telegrip/install/setup.bash"
echo "  ros2 service call /telegrip_heading_calibrator/calibrate std_srvs/srv/Trigger \"{}\""
echo

wait
