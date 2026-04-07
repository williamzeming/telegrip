import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    # 1. 获取包路径
    g1_description_path = get_package_share_directory('mega_robot_1st_urdf')
    we_urdf_vis_path = get_package_share_directory('we_urdf_vis_ros2')

    # 2. 读取 URDF 文件内容
    urdf_file_path = os.path.join(g1_description_path, 'urdf', 'whole_robot.urdf')
    
    with open(urdf_file_path, 'r') as infp:
        robot_desc = infp.read()

    # 3. 配置 RViz 路径
    rviz_config_path = os.path.join(g1_description_path, 'rviz', 'mega_robot_1st.rviz')

    # 4. 定义节点和操作
    
    # Robot State Publisher 节点
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_desc
        }],
        # 使用 remapping 将默认的 /joint_states 重映射到 /robot_joint_states
        remappings=[
            ('/joint_states', '/robot_joint_states')
        ]
    )

    # RViz2 节点 (ROS 2 中包名和执行文件名都是 rviz2)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config_path]
    )

    we_urdf_vis_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(we_urdf_vis_path, 'launch', 'display.launch.py')
        )
    )

    # Joint State Publisher GUI 节点 (可选)
    joint_state_publisher_gui_node = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        name='joint_state_publisher_gui'
    )

    # Static TF: pelvis -> base_link
    # 使用 static_transform_publisher 发布静态变换
    # 参数: x y z yaw pitch roll frame_id child_frame_id
    # 或者使用四元数: x y z qx qy qz qw frame_id child_frame_id
    static_tf_robot_to_DM = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_tf_robot_to_DM',
        arguments=[
            '0', '0.25', '0.8',        # x, y, z (位置偏移，单位: 米)
            '0', '0', '0', '1',   # qx, qy, qz, qw (四元数，单位旋转)
            'robot_base_link',             # parent frame
            'base_link'           # child frame
        ],
        output='screen'
    )

    return LaunchDescription([
        robot_state_publisher_node,
        rviz_node,
        we_urdf_vis_launch,
        # joint_state_publisher_gui_node,
        static_tf_robot_to_DM
    ])
