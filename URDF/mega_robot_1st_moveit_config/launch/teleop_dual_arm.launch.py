import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    moveit_share = get_package_share_directory("mega_robot_1st_moveit_config")

    moveit_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(moveit_share, "launch", "moveit_rviz.launch.py"))
    )

    telegrip_bridge = ExecuteProcess(
        cmd=[
            "python3",
            "-m",
            "telegrip.ros2_moveit_bridge",
            "--ros-args",
            "--params-file",
            os.path.join(moveit_share, "config", "vr_to_moveit_bridge.yaml"),
        ],
        output="screen",
    )

    return LaunchDescription(
        [
            moveit_launch,
            telegrip_bridge,
        ]
    )
