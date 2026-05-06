"""ROS 2 node that stabilizes telegrip controller poses using headset heading."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

ROS2_IMPORT_ERROR: Optional[Exception] = None

try:
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from rclpy.node import Node
    from std_msgs.msg import Bool, Float32
    from std_srvs.srv import Trigger
except Exception as exc:  # pragma: no cover - depends on local ROS 2 install
    rclpy = None
    PoseStamped = None
    Node = object
    Bool = None
    Float32 = None
    Trigger = None
    ROS2_IMPORT_ERROR = exc


DEFAULT_CALIBRATION_FILE = Path("~/.cache/telegrip/heading_calibration.json").expanduser()


@dataclass
class PoseState:
    frame_id: str
    position: Tuple[float, float, float]
    orientation: Tuple[float, float, float, float]


class HeadingCalibrator(Node):
    """Rotate raw VR poses into a heading-stable frame."""

    def __init__(
        self,
        input_prefix: str = "/telegrip",
        output_prefix: str = "/telegrip_calibrated",
        calibration_file: Path = DEFAULT_CALIBRATION_FILE,
        mirror_left_right: Optional[bool] = None,
        output_frame_id: str = "vr_world",
    ):
        super().__init__("telegrip_heading_calibrator")

        self.input_prefix = input_prefix.rstrip("/")
        self.output_prefix = output_prefix.rstrip("/")
        self.calibration_file = calibration_file
        self.output_frame_id = output_frame_id.strip() or "vr_world"

        self.headset_pose: Optional[PoseState] = None
        self.yaw_offset_rad: float = 0.0
        self.mirror_left_right: bool = False

        loaded = self._load_calibration()
        if mirror_left_right is not None:
            self.mirror_left_right = bool(mirror_left_right)
            if loaded:
                self.get_logger().info(f"Mirror mode overridden from CLI: {self.mirror_left_right}")

        self.pose_publishers: Dict[str, object] = {
            "left": self.create_publisher(PoseStamped, f"{self.output_prefix}/left/pose", 10),
            "right": self.create_publisher(PoseStamped, f"{self.output_prefix}/right/pose", 10),
            "headset": self.create_publisher(PoseStamped, f"{self.output_prefix}/headset/pose", 10),
        }
        self.enable_publishers = {
            "left": self.create_publisher(Bool, f"{self.output_prefix}/left/enable", 10),
            "right": self.create_publisher(Bool, f"{self.output_prefix}/right/enable", 10),
        }
        self.gripper_publishers = {
            "left": self.create_publisher(Float32, f"{self.output_prefix}/left/gripper_input", 10),
            "right": self.create_publisher(Float32, f"{self.output_prefix}/right/gripper_input", 10),
        }

        self.create_subscription(PoseStamped, f"{self.input_prefix}/headset/pose", self._on_headset_pose, 10)
        for hand in ("left", "right"):
            self.create_subscription(
                PoseStamped,
                f"{self.input_prefix}/{hand}/pose",
                lambda msg, hand=hand: self._on_hand_pose(hand, msg),
                10,
            )
            self.create_subscription(
                Bool,
                f"{self.input_prefix}/{hand}/enable",
                lambda msg, hand=hand: self.enable_publishers[hand].publish(msg),
                10,
            )
            self.create_subscription(
                Float32,
                f"{self.input_prefix}/{hand}/gripper_input",
                lambda msg, hand=hand: self.gripper_publishers[hand].publish(msg),
                10,
            )

        self.create_service(Trigger, "~/calibrate", self._handle_calibrate)
        self.get_logger().info(
            "Heading calibrator started: %s -> %s | yaw_offset=%.1f deg | mirror=%s",
            self.input_prefix,
            self.output_prefix,
            math.degrees(self.yaw_offset_rad),
            self.mirror_left_right,
        )

    def _handle_calibrate(self, _request, response):
        if self.headset_pose is None:
            response.success = False
            response.message = "No headset pose received yet."
            return response

        try:
            self.yaw_offset_rad = self._compute_heading_alignment(self.headset_pose.orientation)
            self._save_calibration()
            response.success = True
            response.message = (
                f"Saved heading calibration: yaw_offset={math.degrees(self.yaw_offset_rad):.1f} deg, "
                f"mirror={self.mirror_left_right}"
            )
            self.get_logger().info(response.message)
        except ValueError as exc:
            response.success = False
            response.message = str(exc)
        return response

    def _on_headset_pose(self, msg: PoseStamped):
        self.headset_pose = self._pose_state_from_msg(msg)
        self.pose_publishers["headset"].publish(self._transform_pose_msg(msg))

    def _on_hand_pose(self, hand: str, msg: PoseStamped):
        self.pose_publishers[hand].publish(self._transform_pose_msg(msg))

    def _transform_pose_msg(self, msg: PoseStamped) -> PoseStamped:
        pose = self._pose_state_from_msg(msg)
        transformed = self._transform_pose_state(pose)

        out = PoseStamped()
        out.header.stamp = msg.header.stamp
        out.header.frame_id = self.output_frame_id
        out.pose.position.x = transformed.position[0]
        out.pose.position.y = transformed.position[1]
        out.pose.position.z = transformed.position[2]
        out.pose.orientation.x = transformed.orientation[0]
        out.pose.orientation.y = transformed.orientation[1]
        out.pose.orientation.z = transformed.orientation[2]
        out.pose.orientation.w = transformed.orientation[3]
        return out

    def _transform_pose_state(self, pose: PoseState) -> PoseState:
        rotation = self._yaw_rotation_matrix(self.yaw_offset_rad)
        mirror = self._mirror_matrix() if self.mirror_left_right else self._identity_matrix()

        rotated_position = self._matrix_vector_multiply(rotation, pose.position)
        transformed_position = self._matrix_vector_multiply(mirror, rotated_position)

        rotation_matrix = self._quaternion_to_matrix(pose.orientation)
        rotated_orientation = self._matrix_multiply(rotation, rotation_matrix)
        transformed_orientation = self._matrix_to_quaternion(
            self._matrix_multiply(
                self._matrix_multiply(mirror, rotated_orientation),
                mirror,
            )
        )

        return PoseState(
            frame_id=self.output_frame_id,
            position=transformed_position,
            orientation=transformed_orientation,
        )

    def _load_calibration(self) -> bool:
        if not self.calibration_file.exists():
            return False

        try:
            data = json.loads(self.calibration_file.read_text())
            self.yaw_offset_rad = float(data.get("yaw_offset_rad", 0.0))
            self.mirror_left_right = bool(data.get("mirror_left_right", False))
            self.get_logger().info("Loaded heading calibration from %s", self.calibration_file)
            return True
        except Exception as exc:
            self.get_logger().warning("Failed to load calibration file %s: %s", self.calibration_file, exc)
            return False

    def _save_calibration(self):
        self.calibration_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "yaw_offset_rad": self.yaw_offset_rad,
            "mirror_left_right": self.mirror_left_right,
        }
        self.calibration_file.write_text(json.dumps(payload, indent=2))

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

    @classmethod
    def _compute_heading_alignment(cls, quaternion: Tuple[float, float, float, float]) -> float:
        forward = cls._rotate_vector_by_quaternion((0.0, 0.0, -1.0), quaternion)
        horizontal_norm = math.hypot(forward[0], forward[2])
        if horizontal_norm < 1e-6:
            raise ValueError("Headset heading is too close to vertical to calibrate.")
        return math.atan2(forward[0], -forward[2])

    @staticmethod
    def _yaw_rotation_matrix(yaw_rad: float):
        cos_yaw = math.cos(yaw_rad)
        sin_yaw = math.sin(yaw_rad)
        return (
            (cos_yaw, 0.0, sin_yaw),
            (0.0, 1.0, 0.0),
            (-sin_yaw, 0.0, cos_yaw),
        )

    @staticmethod
    def _mirror_matrix():
        return (
            (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        )

    @staticmethod
    def _identity_matrix():
        return (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        )

    @staticmethod
    def _matrix_vector_multiply(matrix, vector):
        return (
            matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
            matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
            matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
        )

    @staticmethod
    def _matrix_multiply(lhs, rhs):
        return (
            (
                lhs[0][0] * rhs[0][0] + lhs[0][1] * rhs[1][0] + lhs[0][2] * rhs[2][0],
                lhs[0][0] * rhs[0][1] + lhs[0][1] * rhs[1][1] + lhs[0][2] * rhs[2][1],
                lhs[0][0] * rhs[0][2] + lhs[0][1] * rhs[1][2] + lhs[0][2] * rhs[2][2],
            ),
            (
                lhs[1][0] * rhs[0][0] + lhs[1][1] * rhs[1][0] + lhs[1][2] * rhs[2][0],
                lhs[1][0] * rhs[0][1] + lhs[1][1] * rhs[1][1] + lhs[1][2] * rhs[2][1],
                lhs[1][0] * rhs[0][2] + lhs[1][1] * rhs[1][2] + lhs[1][2] * rhs[2][2],
            ),
            (
                lhs[2][0] * rhs[0][0] + lhs[2][1] * rhs[1][0] + lhs[2][2] * rhs[2][0],
                lhs[2][0] * rhs[0][1] + lhs[2][1] * rhs[1][1] + lhs[2][2] * rhs[2][1],
                lhs[2][0] * rhs[0][2] + lhs[2][1] * rhs[1][2] + lhs[2][2] * rhs[2][2],
            ),
        )

    @staticmethod
    def _quaternion_to_matrix(quaternion: Tuple[float, float, float, float]):
        x, y, z, w = HeadingCalibrator._normalize_quaternion(quaternion)
        xx = x * x
        yy = y * y
        zz = z * z
        xy = x * y
        xz = x * z
        yz = y * z
        wx = w * x
        wy = w * y
        wz = w * z

        return (
            (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
            (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
            (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
        )

    @staticmethod
    def _matrix_to_quaternion(matrix) -> Tuple[float, float, float, float]:
        trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
        if trace > 0.0:
            s = math.sqrt(trace + 1.0) * 2.0
            w = 0.25 * s
            x = (matrix[2][1] - matrix[1][2]) / s
            y = (matrix[0][2] - matrix[2][0]) / s
            z = (matrix[1][0] - matrix[0][1]) / s
        elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
            s = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2.0
            w = (matrix[2][1] - matrix[1][2]) / s
            x = 0.25 * s
            y = (matrix[0][1] + matrix[1][0]) / s
            z = (matrix[0][2] + matrix[2][0]) / s
        elif matrix[1][1] > matrix[2][2]:
            s = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2.0
            w = (matrix[0][2] - matrix[2][0]) / s
            x = (matrix[0][1] + matrix[1][0]) / s
            y = 0.25 * s
            z = (matrix[1][2] + matrix[2][1]) / s
        else:
            s = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2.0
            w = (matrix[1][0] - matrix[0][1]) / s
            x = (matrix[0][2] + matrix[2][0]) / s
            y = (matrix[1][2] + matrix[2][1]) / s
            z = 0.25 * s

        return HeadingCalibrator._normalize_quaternion((x, y, z, w))

    @staticmethod
    def _rotate_vector_by_quaternion(vector, quaternion):
        matrix = HeadingCalibrator._quaternion_to_matrix(quaternion)
        return HeadingCalibrator._matrix_vector_multiply(matrix, vector)

    @staticmethod
    def _normalize_quaternion(quaternion: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        x, y, z, w = quaternion
        norm = math.sqrt(x * x + y * y + z * z + w * w)
        if norm <= 1e-12:
            return (0.0, 0.0, 0.0, 1.0)
        return (x / norm, y / norm, z / norm, w / norm)


def parse_args():
    parser = argparse.ArgumentParser(description="Stabilize telegrip poses using headset heading calibration")
    parser.add_argument("--input-prefix", default="/telegrip", help="Input topic prefix")
    parser.add_argument("--output-prefix", default="/telegrip_calibrated", help="Output topic prefix")
    parser.add_argument("--output-frame-id", default="vr_world", help="frame_id for calibrated poses")
    parser.add_argument(
        "--calibration-file",
        default=str(DEFAULT_CALIBRATION_FILE),
        help="Path to persisted heading calibration JSON file",
    )
    mirror_group = parser.add_mutually_exclusive_group()
    mirror_group.add_argument(
        "--mirror-left-right",
        dest="mirror_left_right",
        action="store_true",
        help="Mirror left/right motion after heading alignment",
    )
    mirror_group.add_argument(
        "--no-mirror-left-right",
        dest="mirror_left_right",
        action="store_false",
        help="Disable left/right mirroring even if saved calibration enabled it",
    )
    parser.set_defaults(mirror_left_right=None)
    return parser.parse_args()


def main():
    if ROS2_IMPORT_ERROR is not None:
        raise RuntimeError(
            "ROS 2 Python dependencies are unavailable. "
            "Please source your ROS 2 environment before running this node."
        ) from ROS2_IMPORT_ERROR

    args = parse_args()
    rclpy.init(args=None)
    node = HeadingCalibrator(
        input_prefix=args.input_prefix,
        output_prefix=args.output_prefix,
        calibration_file=Path(args.calibration_file).expanduser(),
        mirror_left_right=args.mirror_left_right,
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
