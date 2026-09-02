# viewer_ws_bridge

RK3576 端 Qt viewer 测试桥接包。它只向 dummy ROS Topic 发布控制 JSON，不连接真实底盘。

## 构建

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
colcon build --packages-select viewer_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select viewer_ws_bridge --event-handlers console_direct+
colcon test-result --verbose
```

## 启动与观察控制

终端 1：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 launch viewer_ws_bridge bridge.launch.py
```

终端 2：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic echo /viewer/control_test std_msgs/msg/String
```

## 模拟状态

终端 3：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic pub -r 5 /viewer/status_test std_msgs/msg/String \
  '{data: "{\"type\":\"status\",\"x\":1.0,\"y\":2.0,\"yaw\":0.5,\"speed\":0.8,\"battery\":24.6,\"traffic\":\"green\"}"}'
```

PC 上停止 `pc_ws_bridge`，启动 `ros2_viewer`，WebSocket 地址填写
`ws://8.134.118.29:8770`。完整说明见工作空间根目录 `ros2_viewer集成说明.md`。
