"""
Local ROS 2 adapter that turns controller input streams into latched teleop commands.

Input topics per hand:
- /telegrip/<hand>/pose
- /telegrip/<hand>/enable
- /telegrip/<hand>/gripper_input

Output topics per hand:
- /teleop/<hand>/command_pose
- /teleop/<hand>/gripper_cmd

Behavior:
- pose updates only change command_pose while enable is pressed
- when enable is released, the last command pose is held and republished
- gripper input only updates gripper_cmd while enable is pressed
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

ROS2_IMPORT_ERROR: Optional[Exception] = None

try:
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from rclpy.node import Node
    from std_msgs.msg import Bool, Float32
except Exception as exc:  # pragma: no cover - depends on local ROS 2 install
    rclpy = None
    PoseStamped = None
    Node = object
    Bool = None
    Float32 = None
    ROS2_IMPORT_ERROR = exc


@dataclass
class PoseState:
    """Immutable pose snapshot for latching command output."""

    frame_id: str
    position: Tuple[float, float, float]
    orientation: Tuple[float, float, float, float]


@dataclass
class HandState:
    """Per-hand input and command state."""

    hand: str
    enabled: bool = False
    last_input_pose: Optional[PoseState] = None
    latched_pose: Optional[PoseState] = None
    grip_reference_pose: Optional[PoseState] = None
    grip_anchor_pose: Optional[PoseState] = None
    latched_gripper: float = 0.0


class TeleopInputAdapter(Node):
    """Convert raw controller streams into held command streams."""

    def __init__(
        self,
        input_prefix: str = "/telegrip",
        output_prefix: str = "/teleop",
        publish_rate_hz: float = 30.0,
        output_frame_id: str = "",
    ):
        super().__init__("teleop_input_adapter")

        self.input_prefix = input_prefix.rstrip("/")
        self.output_prefix = output_prefix.rstrip("/")
        self.output_frame_id = output_frame_id.strip()

        self.hand_states: Dict[str, HandState] = {
            "left": HandState(hand="left"),
            "right": HandState(hand="right"),
        }

        self.command_pose_publishers = {}
        self.gripper_cmd_publishers = {}

        for hand in ("left", "right"):
            self.create_subscription(
                PoseStamped,
                f"{self.input_prefix}/{hand}/pose",
                lambda msg, hand=hand: self._on_pose(hand, msg),
                10,
            )
            self.create_subscription(
                Bool,
                f"{self.input_prefix}/{hand}/enable",
                lambda msg, hand=hand: self._on_enable(hand, msg),
                10,
            )
            self.create_subscription(
                Float32,
                f"{self.input_prefix}/{hand}/gripper_input",
                lambda msg, hand=hand: self._on_gripper_input(hand, msg),
                10,
            )

            self.command_pose_publishers[hand] = self.create_publisher(
                PoseStamped,
                f"{self.output_prefix}/{hand}/command_pose",
                10,
            )
            self.gripper_cmd_publishers[hand] = self.create_publisher(
                Float32,
                f"{self.output_prefix}/{hand}/gripper_cmd",
                10,
            )

        period = 1.0 / publish_rate_hz if publish_rate_hz > 0.0 else 1.0 / 30.0
        self.create_timer(period, self._republish_latched_commands)
        self.get_logger().info(
            f"Teleop input adapter started: {self.input_prefix} -> "
            f"{self.output_prefix} at {publish_rate_hz:.1f} Hz"
        )

    def _on_pose(self, hand: str, msg: PoseStamped):
        state = self.hand_states[hand]
        pose_state = self._pose_state_from_msg(msg)
        state.last_input_pose = pose_state

        if state.enabled and state.grip_reference_pose is not None and state.grip_anchor_pose is not None:
            state.latched_pose = self._compose_relative_pose(
                anchor_pose=state.grip_anchor_pose,
                reference_pose=state.grip_reference_pose,
                current_pose=pose_state,
            )
            self._publish_command_pose(hand)

    def _on_enable(self, hand: str, msg: Bool):
        state = self.hand_states[hand]
        was_enabled = state.enabled
        state.enabled = bool(msg.data)

        if state.enabled and not was_enabled and state.last_input_pose is not None:
            if state.latched_pose is None:
                state.latched_pose = state.last_input_pose
                self._publish_command_pose(hand)

            state.grip_reference_pose = state.last_input_pose
            state.grip_anchor_pose = state.latched_pose
        elif not state.enabled and was_enabled:
            state.grip_reference_pose = None
            state.grip_anchor_pose = None

    def _on_gripper_input(self, hand: str, msg: Float32):
        state = self.hand_states[hand]

        if state.enabled:
            state.latched_gripper = self._clamp(msg.data, 0.0, 1.0)
            self._publish_gripper_cmd(hand)

    def _republish_latched_commands(self):
        for hand in ("left", "right"):
            state = self.hand_states[hand]

            if state.latched_pose is not None:
                self._publish_command_pose(hand)

            self._publish_gripper_cmd(hand)

    def _publish_command_pose(self, hand: str):
        state = self.hand_states[hand]
        if state.latched_pose is None:
            return

        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.output_frame_id or state.latched_pose.frame_id
        msg.pose.position.x = state.latched_pose.position[0]
        msg.pose.position.y = state.latched_pose.position[1]
        msg.pose.position.z = state.latched_pose.position[2]
        msg.pose.orientation.x = state.latched_pose.orientation[0]
        msg.pose.orientation.y = state.latched_pose.orientation[1]
        msg.pose.orientation.z = state.latched_pose.orientation[2]
        msg.pose.orientation.w = state.latched_pose.orientation[3]
        self.command_pose_publishers[hand].publish(msg)

    def _publish_gripper_cmd(self, hand: str):
        state = self.hand_states[hand]
        msg = Float32()
        msg.data = float(state.latched_gripper)
        self.gripper_cmd_publishers[hand].publish(msg)

    @staticmethod
    def _compose_relative_pose(
        anchor_pose: PoseState,
        reference_pose: PoseState,
        current_pose: PoseState,
    ) -> PoseState:
        delta_position = (
            current_pose.position[0] - reference_pose.position[0],
            current_pose.position[1] - reference_pose.position[1],
            current_pose.position[2] - reference_pose.position[2],
        )
        composed_position = (
            anchor_pose.position[0] + delta_position[0],
            anchor_pose.position[1] + delta_position[1],
            anchor_pose.position[2] + delta_position[2],
        )

        relative_orientation = TeleopInputAdapter._quaternion_multiply(
            current_pose.orientation,
            TeleopInputAdapter._quaternion_inverse(reference_pose.orientation),
        )
        composed_orientation = TeleopInputAdapter._quaternion_multiply(
            relative_orientation,
            anchor_pose.orientation,
        )

        return PoseState(
            frame_id=anchor_pose.frame_id,
            position=composed_position,
            orientation=TeleopInputAdapter._normalize_quaternion(composed_orientation),
        )

    @staticmethod
    def _pose_state_from_msg(msg: PoseStamped) -> PoseState:
        return PoseState(
            frame_id=msg.header.frame_id,
            position=(
                float(msg.pose.position.x),
                float(msg.pose.position.y),
                float(msg.pose.position.z),
            ),
            orientation=(
                float(msg.pose.orientation.x),
                float(msg.pose.orientation.y),
                float(msg.pose.orientation.z),
                float(msg.pose.orientation.w),
            ),
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))

    @staticmethod
    def _quaternion_multiply(
        lhs: Tuple[float, float, float, float],
        rhs: Tuple[float, float, float, float],
    ) -> Tuple[float, float, float, float]:
        lx, ly, lz, lw = lhs
        rx, ry, rz, rw = rhs
        return (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        )

    @staticmethod
    def _quaternion_inverse(quaternion: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        x, y, z, w = quaternion
        norm_sq = x * x + y * y + z * z + w * w
        if norm_sq <= 1e-12:
            return (0.0, 0.0, 0.0, 1.0)
        return (-x / norm_sq, -y / norm_sq, -z / norm_sq, w / norm_sq)

    @staticmethod
    def _normalize_quaternion(quaternion: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        x, y, z, w = quaternion
        norm = (x * x + y * y + z * z + w * w) ** 0.5
        if norm <= 1e-12:
            return (0.0, 0.0, 0.0, 1.0)
        return (x / norm, y / norm, z / norm, w / norm)


def parse_args():
    parser = argparse.ArgumentParser(description="Latched ROS 2 teleop command adapter")
    parser.add_argument("--input-prefix", default="/telegrip", help="Input topic prefix")
    parser.add_argument("--output-prefix", default="/teleop", help="Output topic prefix")
    parser.add_argument(
        "--publish-rate",
        type=float,
        default=30.0,
        help="Command republish rate in Hz",
    )
    parser.add_argument(
        "--output-frame-id",
        default="",
        help="Override frame_id for command poses (default: keep input frame)",
    )
    return parser.parse_args()


def main():
    if ROS2_IMPORT_ERROR is not None:
        raise RuntimeError(
            "ROS 2 Python dependencies are unavailable. "
            "Please source your ROS 2 environment before running this adapter."
        ) from ROS2_IMPORT_ERROR

    args = parse_args()
    rclpy.init(args=None)
    node = TeleopInputAdapter(
        input_prefix=args.input_prefix,
        output_prefix=args.output_prefix,
        publish_rate_hz=args.publish_rate,
        output_frame_id=args.output_frame_id,
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
