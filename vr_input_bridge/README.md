# vr_input_bridge

独立的 ROS 2 Python 包，用于：

- 提供 WebXR / VR 页面
- 接收头显与控制器数据
- 发布 `/telegrip/*` 与 TF
- 可选运行头显朝向标定节点
- 可选运行 teleop 闩锁适配节点

## 目录说明

- `vr_input_bridge/`: Python 模块
- `web-ui/`: 包内静态网页资源
- `launch/`: 最小、带标定、完整三套 launch

## 复制到新项目后

建议把整个 `vr_input_bridge/` 目录直接复制到新项目工作区的 `src/` 下。

然后在工作区根目录构建：

```bash
colcon build --packages-select vr_input_bridge
source install/setup.bash
```

## 启动方式

最小桥接：

```bash
ros2 launch vr_input_bridge vr_input_bridge.launch.py
```

带朝向标定：

```bash
ros2 launch vr_input_bridge vr_input_with_calibrator.launch.py
```

完整输入链：

```bash
ros2 launch vr_input_bridge vr_input_full.launch.py
```

## 主要输出

- `/telegrip/left/pose`
- `/telegrip/right/pose`
- `/telegrip/headset/pose`
- `/telegrip/left/enable`
- `/telegrip/right/enable`
- `/telegrip/left/gripper_input`
- `/telegrip/right/gripper_input`

可选：

- `/telegrip_calibrated/*`
- `/teleop/*`
