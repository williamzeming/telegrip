#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set +u
source /opt/ros/humble/setup.bash
set -u
exec rviz2 -d "${SCRIPT_DIR}/telegrip_ros2.rviz"
