"""
Bridge VR teleop poses into MoveIt IK requests and publish resulting joint states.

This node is intended for the RViz validation phase:
- subscribes to /teleop/<hand>/command_pose
- maps controller poses into robot base_link targets
- calls MoveIt's /compute_ik service per arm
- publishes the resulting full-body joint state for robot_state_publisher/RViz
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Optional, Tuple

ROS2_IMPORT_ERROR: Optional[Exception] = None

try:
    import rclpy
    from builtin_interfaces.msg import Duration
    from geometry_msgs.msg import PoseStamped
    from moveit_msgs.msg import MoveItErrorCodes, RobotState
    from moveit_msgs.srv import GetPositionIK
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Bool
except Exception as exc:  # pragma: no cover - depends on local ROS 2 install
    rclpy = None
    Duration = None
    PoseStamped = None
    MoveItErrorCodes = None
    RobotState = None
    GetPositionIK = None
    Node = object
    JointState = None
    Bool = None
    ROS2_IMPORT_ERROR = exc


Vector3 = Tuple[float, float, float]
Quaternion = Tuple[float, float, float, float]


@dataclass
class HandConfig:
    hand: str
    enabled: bool
    input_pose_topic: str
    input_enable_topic: str
    output_pose_topic: str
    ik_group_name: str
    ik_link_name: str
    translation_xyz: Vector3
    rotation_rpy_deg: Vector3
    position_axis_mapping: tuple[str, str, str]
    scale_xyz: Vector3
    workspace_min_xyz: Vector3
    workspace_max_xyz: Vector3
    neutral_quaternion_xyzw: Quaternion
    track_orientation: bool
    orientation_tracking_gain: float
    arm_joint_names: list[str]

    @property
    def rotation_quaternion(self) -> Quaternion:
        return quaternion_from_rpy_deg(*self.rotation_rpy_deg)


@dataclass
class HandRuntimeState:
    grip_enabled: bool = False
    reset_reference_on_next_pose: bool = True
    reference_input_position: Optional[Vector3] = None
    reference_input_orientation: Optional[Quaternion] = None
    anchor_target_position: Optional[Vector3] = None
    anchor_target_orientation: Optional[Quaternion] = None


class VRToMoveItBridge(Node):
    def __init__(self):
        super().__init__(
            "vr_to_moveit_bridge",
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )

        self.planning_frame = self.get_parameter("planning_frame").value or "base_link"
        self.publish_rate_hz = float(self.get_parameter("publish_rate_hz").value or 15.0)
        self.ik_service_name = self.get_parameter("ik_service_name").value or "/compute_ik"
        self.ik_timeout_sec = float(self.get_parameter("ik_timeout_sec").value or 0.05)
        self.ik_seed_towards_initial_ratio = max(
            0.0,
            min(1.0, float(self.get_parameter("ik_seed_towards_initial_ratio").value or 0.0)),
        )
        self.avoid_collisions = bool(self.get_parameter("avoid_collisions").value)
        self.world_frame = self.get_parameter("world_frame").value or "vr_world"
        self.robot_base_translation_xyz = tuple(
            float(v) for v in (self.get_parameter("robot_base_translation_xyz").value or [0.75, 0.0, 0.0])
        )
        self.robot_base_rpy_deg = tuple(
            float(v) for v in (self.get_parameter("robot_base_rpy_deg").value or [0.0, 0.0, 0.0])
        )
        self.robot_base_quaternion = quaternion_from_rpy_deg(*self.robot_base_rpy_deg)

        self.joint_names = [str(name) for name in self.get_parameter("joint_names").value]
        if not self.joint_names:
            raise RuntimeError("`joint_names` parameter must not be empty.")

        initial_positions_params = self.get_parameters_by_prefix("initial_positions")
        self.initial_joint_positions: Dict[str, float] = {
            name: float(initial_positions_params.get(name).value) if name in initial_positions_params else 0.0
            for name in self.joint_names
        }
        self.current_joint_positions: Dict[str, float] = dict(self.initial_joint_positions)

        self.hand_configs: Dict[str, HandConfig] = {}
        self.hand_runtime: Dict[str, HandRuntimeState] = {
            "left": HandRuntimeState(),
            "right": HandRuntimeState(),
        }
        self.latest_input_poses: Dict[str, Optional[PoseStamped]] = {"left": None, "right": None}
        self.latest_target_poses: Dict[str, Optional[PoseStamped]] = {"left": None, "right": None}
        self.pending_requests: Dict[str, object] = {"left": None, "right": None}

        self.joint_state_publisher = self.create_publisher(JointState, "/joint_states", 10)
        self.target_pose_publishers: Dict[str, object] = {}

        self.ik_client = self.create_client(GetPositionIK, self.ik_service_name)

        self._load_hand_config("left")
        self._load_hand_config("right")

        period = 1.0 / self.publish_rate_hz if self.publish_rate_hz > 0.0 else 1.0 / 15.0
        self.create_timer(period, self._on_timer)

        self.get_logger().info(
            f"VR to MoveIt bridge started: planning_frame={self.planning_frame}, "
            f"ik_service={self.ik_service_name}, "
            f"avoid_collisions={self.avoid_collisions}, "
            f"seed_towards_initial={self.ik_seed_towards_initial_ratio:.2f}"
        )

    def _load_hand_config(self, hand: str):
        params = self.get_parameters_by_prefix(hand)
        enabled = bool(params.get("enabled").value) if "enabled" in params else True
        input_pose_topic = str(params.get("input_pose_topic").value)
        input_enable_topic = str(params.get("input_enable_topic").value)
        output_pose_topic = str(params.get("output_pose_topic").value)
        config = HandConfig(
            hand=hand,
            enabled=enabled,
            input_pose_topic=input_pose_topic,
            input_enable_topic=input_enable_topic,
            output_pose_topic=output_pose_topic,
            ik_group_name=str(params.get("ik_group_name").value),
            ik_link_name=str(params.get("ik_link_name").value),
            translation_xyz=tuple(float(v) for v in params.get("translation_xyz").value),
            rotation_rpy_deg=tuple(float(v) for v in params.get("rotation_rpy_deg").value),
            position_axis_mapping=parse_axis_mapping(
                params.get("position_axis_mapping").value if "position_axis_mapping" in params else ["-z", "-x", "+y"]
            ),
            scale_xyz=tuple(float(v) for v in params.get("scale_xyz").value),
            workspace_min_xyz=tuple(float(v) for v in params.get("workspace_min_xyz").value),
            workspace_max_xyz=tuple(float(v) for v in params.get("workspace_max_xyz").value),
            neutral_quaternion_xyzw=tuple(float(v) for v in params.get("neutral_quaternion_xyzw").value),
            track_orientation=bool(params.get("track_orientation").value),
            orientation_tracking_gain=max(
                0.0,
                min(1.0, float(params.get("orientation_tracking_gain").value))
            ) if "orientation_tracking_gain" in params else 1.0,
            arm_joint_names=[str(name) for name in params.get("arm_joint_names").value],
        )
        self.hand_configs[hand] = config
        self.create_subscription(PoseStamped, input_pose_topic, lambda msg, h=hand: self._on_pose(h, msg), 10)
        self.create_subscription(Bool, input_enable_topic, lambda msg, h=hand: self._on_enable(h, msg), 10)
        self.target_pose_publishers[hand] = self.create_publisher(PoseStamped, output_pose_topic, 10)

    def _on_enable(self, hand: str, msg: Bool):
        runtime = self.hand_runtime[hand]
        enabled = bool(msg.data)
        if enabled and not runtime.grip_enabled:
            runtime.reset_reference_on_next_pose = True
        runtime.grip_enabled = enabled

    def _on_pose(self, hand: str, msg: PoseStamped):
        self.latest_input_poses[hand] = msg
        target_pose = self._map_pose_to_robot(hand, msg)
        self.latest_target_poses[hand] = target_pose
        self.target_pose_publishers[hand].publish(target_pose)

    def _map_pose_to_robot(self, hand: str, msg: PoseStamped) -> PoseStamped:
        config = self.hand_configs[hand]
        runtime = self.hand_runtime[hand]
        input_position = (
            float(msg.pose.position.x),
            float(msg.pose.position.y),
            float(msg.pose.position.z),
        )
        input_orientation = normalize_quaternion(
            (
                float(msg.pose.orientation.x),
                float(msg.pose.orientation.y),
                float(msg.pose.orientation.z),
                float(msg.pose.orientation.w),
            )
        )

        if msg.header.frame_id and msg.header.frame_id != self.world_frame:
            self.get_logger().warn(
                f"Expected teleop poses in `{self.world_frame}`, but got "
                f"`{msg.header.frame_id}`. Mapping still uses numeric coordinates.",
                throttle_duration_sec=5.0,
            )

        if runtime.reset_reference_on_next_pose or runtime.reference_input_position is None:
            runtime.reference_input_position = input_position
            runtime.reference_input_orientation = input_orientation
            if self.latest_target_poses[hand] is not None:
                current_target = self.latest_target_poses[hand]
                runtime.anchor_target_position = (
                    float(current_target.pose.position.x),
                    float(current_target.pose.position.y),
                    float(current_target.pose.position.z),
                )
                runtime.anchor_target_orientation = (
                    float(current_target.pose.orientation.x),
                    float(current_target.pose.orientation.y),
                    float(current_target.pose.orientation.z),
                    float(current_target.pose.orientation.w),
                )
            else:
                runtime.anchor_target_position = config.translation_xyz
                runtime.anchor_target_orientation = config.neutral_quaternion_xyzw
            runtime.reset_reference_on_next_pose = False

        delta_vr = subtract_vectors(input_position, runtime.reference_input_position)
        robot_delta = vr_delta_to_robot(delta_vr, config.scale_xyz, config.position_axis_mapping)
        position_rotation = quaternion_multiply(self.robot_base_quaternion, config.rotation_quaternion)
        rotated_position = rotate_vector(position_rotation, robot_delta)
        unclamped_position = add_vectors(runtime.anchor_target_position, rotated_position)
        final_position = clamp_vector(unclamped_position, config.workspace_min_xyz, config.workspace_max_xyz)

        target_orientation = runtime.anchor_target_orientation
        if config.track_orientation and runtime.reference_input_orientation is not None:
            relative_orientation = quaternion_multiply(
                input_orientation,
                quaternion_inverse(runtime.reference_input_orientation),
            )
            softened_relative_orientation = scale_quaternion_rotation(
                relative_orientation,
                config.orientation_tracking_gain,
            )
            orientation_rotation = quaternion_multiply(self.robot_base_quaternion, config.rotation_quaternion)
            target_orientation = normalize_quaternion(
                quaternion_multiply(
                    orientation_rotation,
                    quaternion_multiply(softened_relative_orientation, runtime.anchor_target_orientation),
                )
            )

        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = self.planning_frame
        pose.pose.position.x = final_position[0]
        pose.pose.position.y = final_position[1]
        pose.pose.position.z = final_position[2]
        pose.pose.orientation.x = target_orientation[0]
        pose.pose.orientation.y = target_orientation[1]
        pose.pose.orientation.z = target_orientation[2]
        pose.pose.orientation.w = target_orientation[3]
        return pose

    def _on_timer(self):
        self._publish_joint_state()

        if not self.ik_client.service_is_ready():
            self.get_logger().warn(
                f"Waiting for MoveIt IK service `{self.ik_service_name}`...",
                throttle_duration_sec=5.0,
            )
            return

        for hand in ("left", "right"):
            if self.pending_requests[hand] is not None:
                continue
            config = self.hand_configs[hand]
            runtime = self.hand_runtime[hand]
            target_pose = self.latest_target_poses.get(hand)
            if not config.enabled or target_pose is None or not runtime.grip_enabled:
                continue
            future = self.ik_client.call_async(self._build_ik_request(config, target_pose))
            future.add_done_callback(lambda future, h=hand: self._handle_ik_response(h, future))
            self.pending_requests[hand] = future

    def _build_ik_request(self, config: HandConfig, target_pose: PoseStamped) -> GetPositionIK.Request:
        request = GetPositionIK.Request()
        request.ik_request.group_name = config.ik_group_name
        request.ik_request.ik_link_name = config.ik_link_name
        request.ik_request.pose_stamped = target_pose
        request.ik_request.avoid_collisions = self.avoid_collisions
        request.ik_request.timeout = duration_from_seconds(self.ik_timeout_sec)
        request.ik_request.robot_state = self._build_robot_state(config)
        return request

    def _build_robot_state(self, active_config: Optional[HandConfig] = None) -> RobotState:
        state = RobotState()
        state.joint_state.name = list(self.joint_names)
        positions = [float(self.current_joint_positions[name]) for name in self.joint_names]

        if active_config is not None and self.ik_seed_towards_initial_ratio > 0.0:
            blend_ratio = self.ik_seed_towards_initial_ratio
            arm_joint_names = set(active_config.arm_joint_names)
            for index, joint_name in enumerate(state.joint_state.name):
                if joint_name not in arm_joint_names:
                    continue
                current_position = float(self.current_joint_positions[joint_name])
                initial_position = float(self.initial_joint_positions.get(joint_name, current_position))
                positions[index] = ((1.0 - blend_ratio) * current_position) + (blend_ratio * initial_position)

        state.joint_state.position = positions
        state.joint_state.velocity = []
        state.joint_state.effort = []
        return state

    def _handle_ik_response(self, hand: str, future):
        self.pending_requests[hand] = None
        try:
            response = future.result()
        except Exception as exc:  # pragma: no cover - transport failure
            self.get_logger().warn(f"IK request failed for {hand} arm: {exc}")
            return

        if response.error_code.val != MoveItErrorCodes.SUCCESS:
            self.get_logger().warn(
                f"IK for {hand} arm did not converge (error={response.error_code.val})",
                throttle_duration_sec=2.0,
            )
            return

        config = self.hand_configs[hand]
        solution = dict(zip(response.solution.joint_state.name, response.solution.joint_state.position))
        for joint_name in config.arm_joint_names:
            if joint_name in solution:
                self.current_joint_positions[joint_name] = float(solution[joint_name])

    def _publish_joint_state(self):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(self.joint_names)
        msg.position = [float(self.current_joint_positions[name]) for name in self.joint_names]
        self.joint_state_publisher.publish(msg)


def duration_from_seconds(seconds: float) -> Duration:
    whole = int(max(0.0, seconds))
    nanoseconds = int(max(0.0, seconds - whole) * 1e9)
    return Duration(sec=whole, nanosec=nanoseconds)


def add_vectors(lhs: Vector3, rhs: Vector3) -> Vector3:
    return (lhs[0] + rhs[0], lhs[1] + rhs[1], lhs[2] + rhs[2])


def subtract_vectors(lhs: Vector3, rhs: Vector3) -> Vector3:
    return (lhs[0] - rhs[0], lhs[1] - rhs[1], lhs[2] - rhs[2])


def quaternion_from_rpy_deg(roll_deg: float, pitch_deg: float, yaw_deg: float) -> Quaternion:
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)

    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    return normalize_quaternion(
        (
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy,
        )
    )


def quaternion_multiply(lhs: Quaternion, rhs: Quaternion) -> Quaternion:
    lx, ly, lz, lw = lhs
    rx, ry, rz, rw = rhs
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def quaternion_inverse(quaternion: Quaternion) -> Quaternion:
    x, y, z, w = quaternion
    norm_sq = x * x + y * y + z * z + w * w
    if norm_sq <= 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (-x / norm_sq, -y / norm_sq, -z / norm_sq, w / norm_sq)


def normalize_quaternion(quaternion: Quaternion) -> Quaternion:
    x, y, z, w = quaternion
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / norm, y / norm, z / norm, w / norm)


def scale_quaternion_rotation(quaternion: Quaternion, scale: float) -> Quaternion:
    if scale <= 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    if scale >= 1.0:
        return normalize_quaternion(quaternion)

    x, y, z, w = normalize_quaternion(quaternion)
    w = max(-1.0, min(1.0, w))
    half_angle = math.acos(w)
    sin_half_angle = math.sin(half_angle)

    if sin_half_angle <= 1e-8:
        return (0.0, 0.0, 0.0, 1.0)

    axis = (x / sin_half_angle, y / sin_half_angle, z / sin_half_angle)
    scaled_half_angle = half_angle * scale
    scaled_sin = math.sin(scaled_half_angle)
    scaled_quaternion = (
        axis[0] * scaled_sin,
        axis[1] * scaled_sin,
        axis[2] * scaled_sin,
        math.cos(scaled_half_angle),
    )
    return normalize_quaternion(scaled_quaternion)


def rotate_vector(quaternion: Quaternion, vector: Vector3) -> Vector3:
    q = normalize_quaternion(quaternion)
    x, y, z = vector
    vector_quaternion = (x, y, z, 0.0)
    rotated = quaternion_multiply(quaternion_multiply(q, vector_quaternion), quaternion_inverse(q))
    return (rotated[0], rotated[1], rotated[2])


def parse_axis_mapping(raw_mapping) -> tuple[str, str, str]:
    mapping = tuple(str(entry).strip().lower() for entry in raw_mapping)
    if len(mapping) != 3:
        raise ValueError(
            "`position_axis_mapping` must provide exactly three entries, "
            f"got {mapping!r}."
        )

    for entry in mapping:
        if not entry:
            raise ValueError("Axis mapping entries must not be empty.")
        axis = entry[-1]
        if axis not in {"x", "y", "z"}:
            raise ValueError(
                "`position_axis_mapping` entries must end with x, y, or z, "
                f"got {entry!r}."
            )
        if len(entry) > 1 and entry[0] not in {"+", "-"}:
            raise ValueError(
                "`position_axis_mapping` entries must look like x, -x, +y, etc., "
                f"got {entry!r}."
            )

    return mapping


def vr_delta_to_robot(
    delta_vr: Vector3,
    scale_xyz: Vector3,
    axis_mapping: tuple[str, str, str],
) -> Vector3:
    """Map VR delta axes into robot xyz using a configurable axis convention."""
    axis_values = {
        "x": float(delta_vr[0]),
        "y": float(delta_vr[1]),
        "z": float(delta_vr[2]),
    }

    robot_components = []
    for axis_spec, scale in zip(axis_mapping, scale_xyz):
        sign = -1.0 if axis_spec.startswith("-") else 1.0
        axis_name = axis_spec[-1]
        robot_components.append(sign * axis_values[axis_name] * scale)

    return (
        robot_components[0],
        robot_components[1],
        robot_components[2],
    )


def clamp_vector(value: Vector3, lower: Vector3, upper: Vector3) -> Vector3:
    return (
        min(max(value[0], lower[0]), upper[0]),
        min(max(value[1], lower[1]), upper[1]),
        min(max(value[2], lower[2]), upper[2]),
    )


def main():
    if ROS2_IMPORT_ERROR is not None:
        raise RuntimeError(
            "ROS 2 / MoveIt Python dependencies are unavailable. "
            "Please source your ROS 2 workspace before running this bridge."
        ) from ROS2_IMPORT_ERROR

    rclpy.init(args=None)
    node = VRToMoveItBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
