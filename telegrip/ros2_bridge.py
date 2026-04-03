"""
ROS 2 publishing helpers for exposing controller data to RViz2 and other nodes.

This module is intentionally optional: the original telegrip entrypoint does not
import it, so existing behavior remains unchanged unless the ROS 2 launcher is
used.
"""

from __future__ import annotations

from collections import deque
import logging
import math
import threading
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

ROS2_IMPORT_ERROR: Optional[Exception] = None

try:
    import rclpy
    from geometry_msgs.msg import PoseStamped, TransformStamped
    from std_msgs.msg import Bool, Float32
    from tf2_ros import TransformBroadcaster
except Exception as exc:  # pragma: no cover - depends on local ROS 2 install
    rclpy = None
    PoseStamped = None
    TransformStamped = None
    Bool = None
    Float32 = None
    TransformBroadcaster = None
    ROS2_IMPORT_ERROR = exc


class TelegripROS2Bridge:
    """Publish controller poses and controller state into ROS 2."""

    def __init__(self, frame_id: str = "vr_world", node_name: str = "telegrip_bridge"):
        self.frame_id = frame_id
        self.node_name = node_name

        self._lock = threading.Lock()
        self._started = False
        self._owns_rclpy_context = False
        self._packet_timestamps = deque(maxlen=512)

        self.node = None
        self.tf_broadcaster = None
        self.pose_publishers: Dict[str, object] = {}
        self.enable_publishers: Dict[str, object] = {}
        self.trigger_publishers: Dict[str, object] = {}

    def start(self):
        """Initialize ROS 2 resources."""
        if ROS2_IMPORT_ERROR is not None:
            raise RuntimeError(
                "ROS 2 Python dependencies are unavailable. "
                "Please source your ROS 2 environment and install `rclpy`, "
                "`geometry_msgs`, `std_msgs`, and `tf2_ros`."
            ) from ROS2_IMPORT_ERROR

        with self._lock:
            if self._started:
                return

            if not rclpy.ok():
                rclpy.init(args=None)
                self._owns_rclpy_context = True

            self.node = rclpy.create_node(self.node_name)
            self.tf_broadcaster = TransformBroadcaster(self.node)

            self.pose_publishers = {
                "left": self.node.create_publisher(PoseStamped, "/telegrip/left/pose", 10),
                "right": self.node.create_publisher(PoseStamped, "/telegrip/right/pose", 10),
            }
            self.enable_publishers = {
                "left": self.node.create_publisher(Bool, "/telegrip/left/enable", 10),
                "right": self.node.create_publisher(Bool, "/telegrip/right/enable", 10),
            }
            self.trigger_publishers = {
                "left": self.node.create_publisher(Float32, "/telegrip/left/gripper_input", 10),
                "right": self.node.create_publisher(Float32, "/telegrip/right/gripper_input", 10),
            }

            self._started = True
            logger.info("ROS 2 bridge started with frame_id=%s", self.frame_id)

    def stop(self):
        """Release ROS 2 resources."""
        with self._lock:
            if not self._started:
                return

            try:
                if self.node is not None:
                    self.node.destroy_node()
            finally:
                self.node = None
                self.tf_broadcaster = None
                self.pose_publishers = {}
                self.enable_publishers = {}
                self.trigger_publishers = {}
                self._started = False

                if self._owns_rclpy_context and rclpy is not None and rclpy.ok():
                    rclpy.shutdown()
                self._owns_rclpy_context = False

            logger.info("ROS 2 bridge stopped")

    def publish_packet(self, data: Dict):
        """Publish controller data from either the dual- or single-controller packet."""
        with self._lock:
            if not self._started or self.node is None:
                return

            self._record_packet_timestamp()

            if "leftController" in data and "rightController" in data:
                self._publish_hand("left", data.get("leftController") or {})
                self._publish_hand("right", data.get("rightController") or {})
                return

            hand = data.get("hand")
            if hand in ("left", "right"):
                self._publish_hand(hand, data)

    def _publish_hand(self, hand: str, data: Dict):
        stamp = self.node.get_clock().now().to_msg()

        enable_msg = Bool()
        enable_msg.data = bool(data.get("gripActive", False))
        self.enable_publishers[hand].publish(enable_msg)

        trigger_msg = Float32()
        trigger_msg.data = float(data.get("trigger", 0.0))
        self.trigger_publishers[hand].publish(trigger_msg)

        position = data.get("position")
        if not position:
            return

        qx, qy, qz, qw = self._extract_quaternion(
            data.get("quaternion"),
            data.get("rotation"),
        )

        pose_msg = PoseStamped()
        pose_msg.header.stamp = stamp
        pose_msg.header.frame_id = self.frame_id
        pose_msg.pose.position.x = float(position.get("x", 0.0))
        pose_msg.pose.position.y = float(position.get("y", 0.0))
        pose_msg.pose.position.z = float(position.get("z", 0.0))
        pose_msg.pose.orientation.x = qx
        pose_msg.pose.orientation.y = qy
        pose_msg.pose.orientation.z = qz
        pose_msg.pose.orientation.w = qw
        self.pose_publishers[hand].publish(pose_msg)

        tf_msg = TransformStamped()
        tf_msg.header.stamp = stamp
        tf_msg.header.frame_id = self.frame_id
        tf_msg.child_frame_id = f"{hand}_controller"
        tf_msg.transform.translation.x = pose_msg.pose.position.x
        tf_msg.transform.translation.y = pose_msg.pose.position.y
        tf_msg.transform.translation.z = pose_msg.pose.position.z
        tf_msg.transform.rotation.x = qx
        tf_msg.transform.rotation.y = qy
        tf_msg.transform.rotation.z = qz
        tf_msg.transform.rotation.w = qw
        self.tf_broadcaster.sendTransform(tf_msg)

    def _extract_quaternion(
        self,
        quaternion: Optional[Dict],
        rotation_deg: Optional[Dict],
    ) -> Tuple[float, float, float, float]:
        if quaternion and all(k in quaternion for k in ("x", "y", "z", "w")):
            return (
                float(quaternion["x"]),
                float(quaternion["y"]),
                float(quaternion["z"]),
                float(quaternion["w"]),
            )

        if rotation_deg and all(k in rotation_deg for k in ("x", "y", "z")):
            return self._euler_deg_to_quaternion(
                float(rotation_deg["x"]),
                float(rotation_deg["y"]),
                float(rotation_deg["z"]),
            )

        return (0.0, 0.0, 0.0, 1.0)

    @staticmethod
    def _euler_deg_to_quaternion(x_deg: float, y_deg: float, z_deg: float) -> Tuple[float, float, float, float]:
        """Convert XYZ Euler angles in degrees to a quaternion."""
        roll = math.radians(x_deg)
        pitch = math.radians(y_deg)
        yaw = math.radians(z_deg)

        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)

        qw = cr * cp * cy + sr * sp * sy
        qx = sr * cp * cy - cr * sp * sy
        qy = cr * sp * cy + sr * cp * sy
        qz = cr * cp * sy - sr * sp * cy
        return (qx, qy, qz, qw)

    def _record_packet_timestamp(self):
        self._packet_timestamps.append(time.monotonic())

    def get_input_rate_hz(self, window_seconds: float = 2.0) -> float:
        """Estimate incoming VR packet rate over a recent time window."""
        with self._lock:
            now = time.monotonic()
            timestamps = [ts for ts in self._packet_timestamps if now - ts <= window_seconds]

        if len(timestamps) < 2:
            return 0.0

        elapsed = timestamps[-1] - timestamps[0]
        if elapsed <= 0.0:
            return 0.0

        return (len(timestamps) - 1) / elapsed

    def get_topic_names(self) -> Dict[str, list[str]]:
        """Return the ROS 2 topics and TF frames published by the bridge."""
        return {
            "topics": [
                "/telegrip/left/pose",
                "/telegrip/right/pose",
                "/telegrip/left/enable",
                "/telegrip/right/enable",
                "/telegrip/left/gripper_input",
                "/telegrip/right/gripper_input",
            ],
            "tf_frames": [
                f"{self.frame_id} -> left_controller",
                f"{self.frame_id} -> right_controller",
            ],
        }
