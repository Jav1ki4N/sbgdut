# GDUT 公网双向通信测试

PC 与 RK3576 通过云端 WebSocket 中继双向通信。云服务器凭据请单独保管，不要写入仓库。

云端始终运行：

```powershell
py -3.11 relay_server.py
```

## Stage 1：JSON 链路

PC：

```bash
cd /home/i4n/Desktop/GDUT
python3 pc_client.py
```

RK3576：

```bash
cd /home/cat/Desktop/SBGDUT
python3 rk3576_client.py
```

结果：两端 JSON 可经公网双向传输。详见 [第一阶段说明](RK3576/SBGDUT/第一阶段公网JSON双向通信.md)。

## Stage 2：ROS 2 Topic

PC 启动 Bridge：

```bash
cd /home/i4n/Desktop/GDUT
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

RK3576 启动 Bridge：

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rk3576_ws_bridge bridge.launch.py
```

PC 新终端，发送 String：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 topic pub -r 1 /pc_to_cat std_msgs/msg/String "{data: 'hello from pc jazzy'}"
```

PC 新终端，接收 Vector3：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 topic echo /cat_to_pc geometry_msgs/msg/Vector3
```

RK3576 新终端，接收 String：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic echo /pc_to_cat std_msgs/msg/String
```

RK3576 新终端，发送 Vector3：

```bash
source /opt/ros/humble/setup.bash && source /home/cat/Desktop/SBGDUT/install/setup.bash && ros2 topic pub -r 1 /cat_to_pc geometry_msgs/msg/Vector3 "{x: 1.0, y: 2.0, z: 3.0}"
```

结果：PC 已收到 `x/y/z`，RK3576 已收到 `hello from pc jazzy`。

详见 [第二阶段复现说明](RK3576/SBGDUT/第二阶段ROS2双向Topic测试.md)、
[RK3576 Bridge README](RK3576/SBGDUT/rk3576_ws_bridge/README.md) 和
[PC Bridge README](pc_ws_bridge/README.md)。

后续 Qt 上位机接入见 [ros2_viewer 集成说明](ros2_viewer集成说明.md)。
