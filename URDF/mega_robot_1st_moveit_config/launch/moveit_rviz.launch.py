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


def generate_launch_description():
    package_share = get_package_share_directory("mega_robot_1st_moveit_config")
    robot_description_share = get_package_share_directory("mega_robot_1st_urdf")

    urdf_path = os.path.join(robot_description_share, "urdf", "whole_robot_moveit.urdf")
    srdf_path = os.path.join(package_share, "srdf", "mega_robot_1st.srdf")
    rviz_path = os.path.join(package_share, "rviz", "mega_robot_dual_arm.rviz")

    robot_description = {"robot_description": load_text(urdf_path)}
    robot_description_semantic = {"robot_description_semantic": load_text(srdf_path)}
    robot_description_kinematics = {"robot_description_kinematics": load_yaml(os.path.join(package_share, "config", "kinematics.yaml"))}
    robot_description_planning = {"robot_description_planning": load_yaml(os.path.join(package_share, "config", "joint_limits.yaml"))}
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
            rsp,
            move_group,
            rviz,
        ]
    )
