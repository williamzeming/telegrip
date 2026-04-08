import math
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


def load_yaml(path: str):
    import yaml

    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def quaternion_from_rpy_deg(roll_deg: float, pitch_deg: float, yaw_deg: float):
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)

    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def quaternion_inverse(quaternion):
    x, y, z, w = quaternion
    norm_sq = x * x + y * y + z * z + w * w
    if norm_sq <= 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (-x / norm_sq, -y / norm_sq, -z / norm_sq, w / norm_sq)


def quaternion_multiply(lhs, rhs):
    lx, ly, lz, lw = lhs
    rx, ry, rz, rw = rhs
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def rotate_vector(quaternion, vector):
    x, y, z = vector
    vector_quaternion = (x, y, z, 0.0)
    rotated = quaternion_multiply(
        quaternion_multiply(quaternion, vector_quaternion),
        quaternion_inverse(quaternion),
    )
    return (rotated[0], rotated[1], rotated[2])


def generate_launch_description():
    package_share = get_package_share_directory("mega_robot_1st_moveit_config")
    robot_description_share = get_package_share_directory("mega_robot_1st_urdf")

    urdf_path = os.path.join(robot_description_share, "urdf", "whole_robot_moveit.urdf")
    srdf_path = os.path.join(package_share, "srdf", "mega_robot_1st.srdf")
    rviz_path = os.path.join(package_share, "rviz", "mega_robot_dual_arm.rviz")
    bridge_config_path = os.path.join(package_share, "config", "vr_to_moveit_bridge.yaml")

    robot_description = {"robot_description": load_text(urdf_path)}
    robot_description_semantic = {"robot_description_semantic": load_text(srdf_path)}
    robot_description_kinematics = {"robot_description_kinematics": load_yaml(os.path.join(package_share, "config", "kinematics.yaml"))}
    robot_description_planning = {"robot_description_planning": load_yaml(os.path.join(package_share, "config", "joint_limits.yaml"))}
    bridge_config = load_yaml(bridge_config_path)["vr_to_moveit_bridge"]["ros__parameters"]

    robot_base_translation = tuple(float(v) for v in bridge_config.get("robot_base_translation_xyz", [0.0, 0.0, 0.0]))
    robot_base_rpy_deg = tuple(float(v) for v in bridge_config.get("robot_base_rpy_deg", [0.0, 0.0, 0.0]))
    robot_base_quaternion = quaternion_from_rpy_deg(*robot_base_rpy_deg)
    world_to_vr_rotation = quaternion_inverse(robot_base_quaternion)
    world_to_vr_translation = rotate_vector(
        world_to_vr_rotation,
        tuple(-value for value in robot_base_translation),
    )
    ompl_planning_pipeline_config = {
        "planning_plugin": "ompl_interface/OMPLPlanner",
        "request_adapters": (
            "default_planner_request_adapters/AddTimeOptimalParameterization "
            "default_planner_request_adapters/FixWorkspaceBounds "
            "default_planner_request_adapters/FixStartStateBounds "
            "default_planner_request_adapters/FixStartStateCollision "
            "default_planner_request_adapters/FixStartStatePathConstraints"
        ),
        "start_state_max_bounds_error": 0.1,
        "ompl": load_yaml(os.path.join(package_share, "config", "ompl_planning.yaml")),
    }
    moveit_controllers = load_yaml(os.path.join(package_share, "config", "moveit_controllers.yaml"))
    trajectory_execution = {
        "moveit_manage_controllers": False,
        "trajectory_execution.allowed_execution_duration_scaling": 1.2,
        "trajectory_execution.allowed_goal_duration_margin": 0.5,
        "trajectory_execution.allowed_start_tolerance": 0.01,
    }
    planning_scene_monitor_parameters = {
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
    }

    rsp = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description],
    )

    static_world = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="world_to_base_link",
        arguments=["0", "0", "0", "0", "0", "0", "world", "base_link"],
        output="screen",
    )

    static_world_to_vr = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="world_to_vr_world",
        arguments=[
            str(world_to_vr_translation[0]),
            str(world_to_vr_translation[1]),
            str(world_to_vr_translation[2]),
            str(world_to_vr_rotation[0]),
            str(world_to_vr_rotation[1]),
            str(world_to_vr_rotation[2]),
            str(world_to_vr_rotation[3]),
            "world",
            str(bridge_config.get("world_frame", "vr_world")),
        ],
        output="screen",
    )

    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[
            robot_description,
            robot_description_semantic,
            robot_description_kinematics,
            robot_description_planning,
            ompl_planning_pipeline_config,
            trajectory_execution,
            moveit_controllers,
            planning_scene_monitor_parameters,
        ],
    )

    rviz = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="screen",
        arguments=["-d", rviz_path],
        parameters=[
            robot_description,
            robot_description_semantic,
            robot_description_kinematics,
            robot_description_planning,
            ompl_planning_pipeline_config,
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            static_world,
            static_world_to_vr,
            rsp,
            move_group,
            rviz,
        ]
    )
