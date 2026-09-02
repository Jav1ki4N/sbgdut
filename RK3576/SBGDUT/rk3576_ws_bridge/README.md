# RK3576 ROS 2 WebSocket Bridge

`rk3576_ws_bridge` 是第二阶段公网 ROS 2 双向 Topic 测试的 RK3576 端标准
`ament_python` 包。它运行于 Ubuntu 22.04 / ROS 2 Humble，通过 WebSocket JSON 中继与
PC 端 ROS 2 Jazzy 通信。

本阶段只验证通信链路，不连接树莓派、底盘或 `/cmd_vel`，不执行真实车辆控制。

## 数据方向

```text
PC /pc_to_cat (String)
  -> pc_ws_bridge -> 云端 8770/8771 -> rk3576_ws_bridge
  -> RK3576 /pc_to_cat (String)

RK3576 /cat_to_pc (Vector3)
  -> rk3576_ws_bridge -> 云端 8771/8770 -> pc_ws_bridge
  -> PC /cat_to_pc (Vector3)
```

RK3576 节点：

- 节点名：`/rk3576_ws_bridge`
- 订阅：`/cat_to_pc`，类型 `geometry_msgs/msg/Vector3`
- 发布：`/pc_to_cat`，类型 `std_msgs/msg/String`
- WebSocket：`ws://8.134.118.29:8771`
- 断线后自动重连，待发送队列只保留最新消息

## 环境与依赖

```bash
sudo apt update
sudo apt install -y python3-colcon-common-extensions python3-websockets \
  ros-humble-ros-base ros-humble-geometry-msgs
```

检查环境：

```bash
source /opt/ros/humble/setup.bash
printenv ROS_DISTRO
python3 --version
python3 -c 'import rclpy, websockets; print(websockets.__version__)'
ros2 interface show std_msgs/msg/String
ros2 interface show geometry_msgs/msg/Vector3
```

`ROS_DISTRO` 应为 `humble`。

## 构建与测试

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
colcon build --packages-select rk3576_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select rk3576_ws_bridge --event-handlers console_direct+
colcon test-result --verbose
```

构建必须成功；测试数量不能为零，最终结果必须为 `0 errors, 0 failures`。

## 参数

默认参数位于 `config/bridge.yaml`：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `server_uri` | `ws://8.134.118.29:8771` | RK3576 的云端入口 |
| `outbound_topic` | `/cat_to_pc` | 本地订阅的 Vector3 Topic |
| `inbound_topic` | `/pc_to_cat` | 本地发布的 String Topic |
| `reconnect_delay` | `2.0` | 断线重连间隔，单位秒 |

临时覆盖参数：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 run rk3576_ws_bridge bridge_node --ros-args \
  -p server_uri:=ws://8.134.118.29:8771 \
  -p outbound_topic:=/cat_to_pc \
  -p inbound_topic:=/pc_to_cat \
  -p reconnect_delay:=2.0
```

## 公网复现步骤

### 1. 启动云端

Windows 云服务器运行：

```powershell
py -3.11 relay_server.py
```

确认监听 `0.0.0.0:8770`（PC）和 `0.0.0.0:8771`（RK3576），且云安全组、Windows
防火墙已放行这两个 TCP 端口。

### 2. 启动 RK3576 bridge

RK3576 终端 1：

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rk3576_ws_bridge bridge.launch.py
```

等待出现：

```text
公网中继已连接
```

### 3. 启动 PC bridge

PC 终端 1：

```bash
cd /home/i4n/Desktop/GDUT
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

同样等待“公网中继已连接”。

### 4. 测试 PC 到 RK3576

RK3576 终端 2：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic echo /pc_to_cat std_msgs/msg/String
```

PC 终端 2：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 topic pub -r 1 /pc_to_cat std_msgs/msg/String \
  "{data: 'hello from pc jazzy'}"
```

RK3576 应持续收到：

```text
data: hello from pc jazzy
---
```

### 5. 测试 RK3576 到 PC

PC 终端 3：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 topic echo /cat_to_pc geometry_msgs/msg/Vector3
```

RK3576 终端 3 使用以下单行命令：

```bash
source /opt/ros/humble/setup.bash && source /home/cat/Desktop/SBGDUT/install/setup.bash && ros2 topic pub -r 1 /cat_to_pc geometry_msgs/msg/Vector3 "{x: 1.0, y: 2.0, z: 3.0}"
```

PC 应持续收到：

```text
x: 1.0
y: 2.0
z: 3.0
---
```

## 本机接口检查

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 node info /rk3576_ws_bridge
```

必须包含：

```text
Subscribers:
  /cat_to_pc: geometry_msgs/msg/Vector3
Publishers:
  /pc_to_cat: std_msgs/msg/String
```

## 断线重连验收

1. 保持两端的 `topic pub` 和 `topic echo` 运行。
2. 在任意一端 bridge 终端按 `Ctrl+C`。
3. 等待至少 3 秒并重新启动该 bridge。
4. 确认再次出现“公网中继已连接”。
5. 确认两个方向的 Topic 恢复，且没有集中补发大量旧消息。

## JSON 协议示例

RK3576 发往 PC：

```json
{"source":"rk3576","type":"ros_topic","seq":1,"timestamp":1788364800010,"topic":"/cat_to_pc","msg_type":"geometry_msgs/msg/Vector3","data":{"x":1.0,"y":2.0,"z":3.0}}
```

RK3576 接收 PC：

```json
{"source":"pc","type":"ros_topic","seq":1,"timestamp":1788364800000,"topic":"/pc_to_cat","msg_type":"std_msgs/msg/String","data":{"data":"hello from pc jazzy"}}
```

接收端会拒绝来源、类型、Topic、消息类型或元数据错误的帧。无效消息只记录 warning，不会
导致节点退出。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| `The passed message type is invalid` | 不要写成 `Vector3\ "{...}"`；复制上面的单行发布命令 |
| `Connection refused` | 确认云端 8771 正在监听，并检查安全组和 Windows 防火墙 |
| `Package 'rk3576_ws_bridge' not found` | 重新加载 Humble 和 `/home/cat/Desktop/SBGDUT/install/setup.bash` |
| `No module named websockets` | 安装 `python3-websockets` |
| `topic echo` 没有输出 | 确认两个 bridge 都已连接，且对端 `topic pub` 正在运行 |
| PC 与 RK3576 无法通过 DDS 发现 | 正常；公网段使用 WebSocket JSON，不使用 DDS |

## 当前验收状态

已实际确认：

- PC 能收到 RK3576 发布的 `x=1.0, y=2.0, z=3.0`。
- RK3576 能收到 PC 发布的 `hello from pc jazzy`。
- PC 端 `pc_ws_bridge` 已通过 32 项测试，结果为 `0 errors, 0 failures`。

断线重连测试完成后，应把日期、两端日志和云服务器日志一并保存为最终验收证据。
