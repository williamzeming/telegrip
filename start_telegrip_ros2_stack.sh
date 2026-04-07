#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

MIRROR_FLAG=""
START_RVIZ=1
CALIBRATOR_ONLY=0
EXTRA_MAIN_ARGS=()

usage() {
  cat <<'EOF'
Usage: bash start_telegrip_ros2_stack.sh [options] [-- <extra args for telegrip.main_ros2>]

Options:
  --mirror-left-right   Start the heading calibrator with left/right mirroring enabled
  --no-rviz             Do not launch RViz2
  --calibrator-only     Only launch the heading calibrator and leave other nodes untouched
  -h, --help            Show this help message

Examples:
  bash start_telegrip_ros2_stack.sh
  bash start_telegrip_ros2_stack.sh --mirror-left-right
  bash start_telegrip_ros2_stack.sh --no-rviz -- --host 0.0.0.0
EOF
}

while (($#)); do
  case "$1" in
    --mirror-left-right)
      MIRROR_FLAG="--mirror-left-right"
      shift
      ;;
    --no-rviz)
      START_RVIZ=0
      shift
      ;;
    --calibrator-only)
      CALIBRATOR_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_MAIN_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

set +u
source /opt/ros/humble/setup.bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate teleop
set -u

declare -a PIDS=()

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
  wait || true
  exit "${exit_code}"
}

trap cleanup EXIT INT TERM

start_process() {
  local name="$1"
  shift
  local log_file="${LOG_DIR}/${name}.log"
  echo "[telegrip-stack] starting ${name}"
  (
    cd "${SCRIPT_DIR}"
    exec "$@"
  ) >"${log_file}" 2>&1 &
  local pid=$!
  PIDS+=("${pid}")
  echo "[telegrip-stack] ${name} pid=${pid} log=${log_file}"
}

if [[ "${CALIBRATOR_ONLY}" -eq 0 ]]; then
  start_process main_ros2 python3 -m telegrip.main_ros2 --no-robot --no-sim --log-level info "${EXTRA_MAIN_ARGS[@]}"
  sleep 2
fi

if [[ -n "${MIRROR_FLAG}" ]]; then
  start_process heading_calibrator python3 -m telegrip.ros2_heading_calibrator "${MIRROR_FLAG}"
else
  start_process heading_calibrator python3 -m telegrip.ros2_heading_calibrator
fi

if [[ "${CALIBRATOR_ONLY}" -eq 0 ]]; then
  sleep 1
  start_process ros2_input_adapter python3 -m telegrip.ros2_input_adapter --input-prefix /telegrip_calibrated
  start_process ros2_path_tracker python3 -m telegrip.ros2_path_tracker
  if [[ "${START_RVIZ}" -eq 1 ]]; then
    start_process rviz2 bash "${SCRIPT_DIR}/start_rviz2_telegrip.sh"
  fi
fi

echo
echo "[telegrip-stack] startup complete"
echo "[telegrip-stack] logs directory: ${LOG_DIR}"
echo "[telegrip-stack] press Ctrl+C to stop all started processes"
echo "[telegrip-stack] run calibration when ready:"
echo "  source /opt/ros/humble/setup.bash"
echo "  ros2 service call /telegrip_heading_calibrator/calibrate std_srvs/srv/Trigger \"{}\""
echo

wait
