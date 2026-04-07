from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, ExecuteProcess
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
import os


def generate_launch_description() -> LaunchDescription:
	# Try to get package share directory, fallback to relative path
	try:
		share_dir = get_package_share_directory('v2_robot')
	except PackageNotFoundError:
		# Fallback: use the launch file's directory to find urdf
		launch_file_dir = os.path.dirname(os.path.realpath(__file__))
		share_dir = os.path.dirname(launch_file_dir)
	urdf_file = os.path.join(share_dir, 'urdf', 'whole_robot.urdf')

	# Gazebo (server + client)
	gazebo_ros_share = get_package_share_directory('gazebo_ros')
	gazebo = IncludeLaunchDescription(
		PythonLaunchDescriptionSource(
			os.path.join(gazebo_ros_share, 'launch', 'gazebo.launch.py')
		)
	)

	# Robot State Publisher to publish TF tree
	with open(urdf_file, 'r') as f:
		robot_description = f.read()

	robot_state_publisher = Node(
		package='robot_state_publisher',
		executable='robot_state_publisher',
		parameters=[{'robot_description': robot_description}],
		output='screen'
	)

	# Static transform (base_link -> base_footprint)
	static_tf = Node(
		package='tf2_ros',
		executable='static_transform_publisher',
		arguments=['0', '0', '0', '0', '0', '0', 'base_link', 'base_footprint'],
		output='screen'
	)

	# Spawn the robot into Gazebo
	spawn_entity = Node(
		package='gazebo_ros',
		executable='spawn_entity.py',
		arguments=['-file', urdf_file, '-entity', 'v2_robot'],
		output='screen'
	)

	# Optional: publish a one-shot calibration flag (ROS 1 parity)
	pub_calibrated = ExecuteProcess(
		cmd=['ros2', 'topic', 'pub', '--once', '/calibrated', 'std_msgs/msg/Bool', '{"data": true}'],
		output='screen'
	)

	return LaunchDescription([
		gazebo,
		robot_state_publisher,
		static_tf,
		spawn_entity,
		pub_calibrated
	])

