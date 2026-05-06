"""Launch VR input bridge together with heading calibrator."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("log_level", default_value="info"),
            DeclareLaunchArgument("host", default_value="0.0.0.0"),
            DeclareLaunchArgument("https_port", default_value="8443"),
            DeclareLaunchArgument("ws_port", default_value="8442"),
            DeclareLaunchArgument("frame_id", default_value="vr_world"),
            Node(
                package="vr_input_bridge",
                executable="vr_input_bridge",
                name="vr_input_bridge",
                output="screen",
                arguments=[
                    "--log-level",
                    LaunchConfiguration("log_level"),
                    "--host",
                    LaunchConfiguration("host"),
                    "--https-port",
                    LaunchConfiguration("https_port"),
                    "--ws-port",
                    LaunchConfiguration("ws_port"),
                    "--ros-frame-id",
                    LaunchConfiguration("frame_id"),
                ],
            ),
            Node(
                package="vr_input_bridge",
                executable="vr_heading_calibrator",
                name="telegrip_heading_calibrator",
                output="screen",
            ),
        ]
    )
