#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

set +u
source /opt/ros/humble/setup.bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate teleop
set -u

echo "[mega-moveit] starting MoveIt RViz stack"
ros2 launch mega_robot_1st_moveit_config teleop_dual_arm.launch.py
