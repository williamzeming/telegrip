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

如果本机 IP 变了，以 `telegrip.main_ros2` 启动日志里打印的新地址为准。

## 三、只启动原版 telegrip

如果你只想运行原始版本，不使用 ROS 2 链路：

```bash
cd /home/andy/teleOp/telegrip
conda activate teleop
telegrip
```
