# telegrip 启动说明

当前项目只保留一条最小可用链路：

- 从 VR 中拿到原始手柄数据
- 使用头显朝向进行会话级方向标定
- 把数据发布到 ROS 2
- 在 `rviz2` 中显示实时位姿和运动轨迹

不再包含机器人模型、URDF 网格、坐标变换和 IK 相关步骤。

## 一、基础环境

下面的大部分命令都默认在项目根目录执行，并且需要先加载 ROS 2 和 conda 环境：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
conda activate teleop
```

## 二、最小可用链路

这一部分已经足够实现：

- VR 页面连接
- 原始手柄位姿进入 ROS 2
- `grip` 按键保持逻辑
- 在 `rviz2` 中显示原始轨迹和保持后的轨迹

### 可选：一键启动整套 ROS 2 链路

如果你只是想快速启动整套链路，而不想分 5 个终端手动执行，也可以直接运行：

```bash
bash /home/andy/teleOp/telegrip/start_telegrip_ros2_stack.sh
```

它会按当前文档中的默认顺序启动：

- `telegrip.main_ros2`
- `telegrip.ros2_heading_calibrator`
- `telegrip.ros2_input_adapter --input-prefix /telegrip_calibrated`
- `telegrip.ros2_path_tracker`
- 预配置 `rviz2`

说明：

- 这只是一个额外的快捷脚本，不会替代下面的单独启动方式
- 你仍然可以继续按下面的步骤逐个节点启动和调试
- 日志会写入项目根目录下的 `logs/`

常用参数：

```bash
# 开启左右镜像
bash /home/andy/teleOp/telegrip/start_telegrip_ros2_stack.sh --mirror-left-right

# 不启动 RViz
bash /home/andy/teleOp/telegrip/start_telegrip_ros2_stack.sh --no-rviz

# 只启动朝向标定节点
bash /home/andy/teleOp/telegrip/start_telegrip_ros2_stack.sh --calibrator-only
```

### 1. 启动 ROS 2 桥接节点

在第一个终端运行：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
conda activate teleop
python3 -m telegrip.main_ros2 --no-robot --no-sim --log-level info
```

它会启动以下内容：

- HTTPS 页面：`https://<你的局域网 IP>:8443`
- VR WebSocket 服务：`wss://<你的局域网 IP>:8442`
- ROS 2 话题：
  - `/telegrip/left/pose`
  - `/telegrip/right/pose`
  - `/telegrip/headset/pose`
  - `/telegrip/left/enable`
  - `/telegrip/right/enable`
  - `/telegrip/left/gripper_input`
  - `/telegrip/right/gripper_input`
- TF：
  - `vr_world -> left_controller`
  - `vr_world -> right_controller`
  - `vr_world -> headset`

运行过程中还会打印：

- 当前 VR 传输模式：`websocket` 或 `https-fallback`
- 当前 VR 输入频率，单位 Hz

### 2. 启动头显朝向标定节点

在第二个终端运行：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
conda activate teleop
python3 -m telegrip.ros2_heading_calibrator
```

如果你希望在标定后启用左右镜像：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
conda activate teleop
python3 -m telegrip.ros2_heading_calibrator --mirror-left-right
```

节点功能：

- 订阅 `/telegrip/headset/pose` 读取头显朝向
- 将 `/telegrip/*` 的原始 pose 流校正后输出到 `/telegrip_calibrated/*`
- 标定结果默认保存到 `~/.cache/telegrip/heading_calibration.json`
- 下次启动会自动加载上一次的朝向和镜像设置

在头显和机器人相对站位确定后，执行一次标定：

```bash
source /opt/ros/humble/setup.bash
ros2 service call /telegrip_heading_calibrator/calibrate std_srvs/srv/Trigger "{}"
```

建议操作方式：

- 人面向机器人正前方站好
- 头显朝向你希望定义为“机器人前方”的方向
- 再调用上面的标定服务

### 3. 启动 teleop 输入适配节点

在第三个终端运行：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
conda activate teleop
python3 -m telegrip.ros2_input_adapter --input-prefix /telegrip_calibrated
```

它会发布：

- `/teleop/left/command_pose`
- `/teleop/right/command_pose`
- `/teleop/left/gripper_cmd`
- `/teleop/right/gripper_cmd`

逻辑说明：

- 只有按住侧键 `grip` 时，`command_pose` 才会更新
- 按下 `grip` 的瞬间不会跳到当前实时手柄位置
- `grip` 按下时只记录一个参考点，按住期间根据按下后的相对位移和相对转动更新 `command_pose`
- 松开 `grip` 后，`command_pose` 保持最后一次值
- 只有按住 `grip` 时，`gripper_cmd` 才会跟随输入更新

### 4. 启动轨迹可视化节点

在第四个终端运行：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
conda activate teleop
python3 -m telegrip.ros2_path_tracker
```

它会发布这些 RViz 轨迹话题：

- `/telegrip/left/path`
- `/telegrip/right/path`
- `/teleop/left/path`
- `/teleop/right/path`

### 5. 启动 RViz2

在第五个终端运行：

```bash
bash /home/andy/teleOp/telegrip/start_rviz2_telegrip.sh
```

它会自动加载仓库内的预配置文件 `telegrip_ros2.rviz`，其中已经包含：

- `Fixed Frame = vr_world`
- `TF`
- 原始 pose:
  - `/telegrip/left/pose`
  - `/telegrip/right/pose`
- 校正后 pose:
  - `/telegrip_calibrated/left/pose`
  - `/telegrip_calibrated/right/pose`
- teleop 命令 pose:
  - `/teleop/left/command_pose`
  - `/teleop/right/command_pose`
- 原始 / 校正后 / teleop 三套路径

这样你就能同时看到：

- 原始手柄实时位姿
- 经头显朝向校正后的手柄位姿
- 按住 `grip` 后按相对运动更新的 teleop 命令位姿
- 两套数据各自的运动轨迹

### 6. 在头显中打开 VR 页面

在头显浏览器中打开：

```text
https://<你的局域网 IP>:8443
```

## 三、Mega 双臂 MoveIt + RViz 遥操

这一部分用于把现有 VR ROS 2 链路接到 `mega_robot_1st_urdf` 的双臂模型，并在 RViz 中验证双臂跟手效果。

当前实现特点：

- 使用新的 MoveIt 2 配置包 `mega_robot_1st_moveit_config`
- 只纳入左右臂 14 自由度进行 IK
- 不接真机
- 通过 MoveIt `/compute_ik` 求解左右臂关节
- 把关节结果发布成 `/joint_states`，由 `robot_state_publisher` 和 RViz 显示

说明：

- MoveIt 现在直接使用原始网格版模型：
  `URDF/mega_robot_1st_urdf/urdf/whole_robot_moveit.urdf`
- 也就是说，RViz 中会直接显示你已有的 STL 网格外观
- `mega_robot_1st_moveit_config` 仍然负责 MoveIt 的 SRDF、规划参数、桥接参数和联调 launch

### 1. 先编译 ROS 2 包

如果你还没有把新包编译进当前环境，先在工作区根目录执行：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select mega_robot_1st_urdf mega_robot_1st_moveit_config
source /home/andy/teleOp/telegrip/install/setup.bash
conda activate teleop
```

如果你的工作区之前就不是标准 colcon 工作区结构，至少要保证：

- `mega_robot_1st_moveit_config` 能被 `ros2 pkg prefix` 找到
- `telegrip` Python 包在当前 `conda` 环境里可导入

### 2. 启动 VR ROS 2 基础链路

继续按上面的“最小可用链路”方式启动：

```bash
bash /home/andy/teleOp/telegrip/start_telegrip_ros2_stack.sh --no-rviz
```

或者手动启动这些节点：

- `telegrip.main_ros2`
- `telegrip.ros2_heading_calibrator`
- `telegrip.ros2_input_adapter --input-prefix /telegrip_calibrated`
- `telegrip.ros2_path_tracker`

### 3. 启动 Mega 双臂 MoveIt + RViz

在另一个终端运行：

```bash
cd /home/andy/teleOp/telegrip
source /opt/ros/humble/setup.bash
source /home/andy/teleOp/telegrip/install/setup.bash
conda activate teleop
bash /home/andy/teleOp/telegrip/start_mega_moveit_teleop.sh
```

它会启动：

- `robot_state_publisher`
- `move_group`
- 预配置 RViz
- `telegrip.ros2_moveit_bridge`

### 4. 标定并开始遥操

先像前面一样做一次头显朝向标定：

```bash
source /opt/ros/humble/setup.bash
source /home/andy/teleOp/telegrip/install/setup.bash
ros2 service call /telegrip_heading_calibrator/calibrate std_srvs/srv/Trigger "{}"
```

然后在头显里按住左右手柄的 `grip`：

- 左手控制左臂
- 右手控制右臂
- 目标位姿会先发布到：
  - `/mega_moveit/left/target_pose`
  - `/mega_moveit/right/target_pose`
- MoveIt IK 解算成功后，机器人模型会在 RViz 中更新

### 5. 现阶段的调试建议

如果 RViz 中不动，优先检查：

- `/teleop/left/command_pose` 和 `/teleop/right/command_pose` 是否有数据
- `/mega_moveit/left/target_pose` 和 `/mega_moveit/right/target_pose` 是否在更新
- `/compute_ik` 服务是否存在
- `move_group` 日志里是否有 IK 失败

建议先这样调：

1. 先只动右手，确认右臂会跟
2. 再测试左臂
3. 如果模型跳得太远，调 `URDF/mega_robot_1st_moveit_config/config/vr_to_moveit_bridge.yaml` 中每只手的：
   - `translation_xyz`
   - `scale_xyz`
   - `workspace_min_xyz`
   - `workspace_max_xyz`
   - `neutral_quaternion_xyzw`
4. 如果姿态方向不对，优先调：
   - `rotation_rpy_deg`
   - `robot_base_rpy_deg`
5. 当前桥接逻辑已经改成：
   - 只有对应手 `grip` 按住时才发该手 IK
   - 每次重新按下 `grip` 都会重置参考点
   - 目标位姿会被夹在各自手臂的可达工作空间内

当前联调经验：

- 右臂已经可以稳定进入可达区，优先用右手确认整条链路
- 左臂也可以解，但比右臂更容易因为目标点过低而无解
- 如果左臂还不稳定，优先把左臂目标限制在上半空间，而不是继续一味放大缩放系数

当前默认工作空间约束大致为：

- 右臂：`x in [0.30, 0.55]`，`y in [-0.55, -0.20]`，`z in [0.45, 0.85]`
- 左臂：`x in [0.30, 0.55]`，`y in [0.20, 0.55]`，`z in [0.45, 0.85]`

### 6. 当前限制

这一版是“先在 RViz 跑通”的版本，当前限制包括：

- 还没有接入真实控制器或 `ros2_control`
- 还没有用 MoveIt Servo 做连续伺服，只是周期性 IK
- 只规划左右臂，躯干和头部固定在默认关节角

如果本机 IP 变了，以 `telegrip.main_ros2` 启动日志里打印的新地址为准。

## 三、只启动原版 telegrip

如果你只想运行原始版本，不使用 ROS 2 链路：

```bash
cd /home/andy/teleOp/telegrip
conda activate teleop
telegrip
```
