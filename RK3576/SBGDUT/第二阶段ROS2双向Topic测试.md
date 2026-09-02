# 第二阶段：ROS 2 双向 Topic 公网测试

## 1. 目标与边界

本阶段只验证两端 ROS 2 的不同格式 Topic 能通过第一阶段的 WebSocket 公网中继双向传输。
RK3576（“猫”）仅承担通信，不接树莓派控制接口，不发送真实车辆控制。

```text
PC ROS 2 Jazzy <---> pc_ws_bridge <---> 云端 relay_server.py
                                        <---> rk3576_ws_bridge <---> RK3576 ROS 2 Humble
```

云服务器继续运行第一阶段的 `relay_server.py`，无需修改。

## 2. 测试 Topic

两边故意使用不同消息格式：

| 方向 | Topic | ROS 2 类型 |
| --- | --- | --- |
| PC -> RK3576 | `/pc_to_cat` | `std_msgs/msg/String` |
| RK3576 -> PC | `/cat_to_pc` | `geometry_msgs/msg/Vector3` |

发送端 bridge 订阅本机 Topic，转换为 JSON 后发送；接收端 bridge 校验 JSON，再以原 ROS
类型发布到同名 Topic。两个 Topic 的方向固定，所以不会在本机形成回送环路。

## 3. 环境准备

实际环境为 PC 使用 Ubuntu 24.04/ROS 2 Jazzy，RK3576 使用 Ubuntu 22.04/ROS 2 Humble。PC 安装依赖：

```bash
sudo apt install -y python3-colcon-common-extensions python3-websockets ros-jazzy-ros-base ros-jazzy-geometry-msgs
source /opt/ros/jazzy/setup.bash
```

如果每次打开终端都要使用 ROS 2，可把 `source` 命令加入 shell 启动文件。

## 4. 启动

保持云服务器上的第一阶段中继运行：

```powershell
py -3.11 relay_server.py
```

PC（Wi-Fi）使用标准 ROS 包运行：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

RK3576（手机热点，ROS 2 Humble）使用标准 ROS 包运行：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rk3576_ws_bridge bridge.launch.py
```

脚本默认连接 `8.134.118.29`。也可以用命令行临时覆盖完整地址，例如：

```bash
ros2 run pc_ws_bridge bridge_node --ros-args -p server_uri:=ws://8.134.118.29:8770
ros2 run rk3576_ws_bridge bridge_node --ros-args \
  -p server_uri:=ws://8.134.118.29:8771
```

## 5. 双向验收

在 PC 的另一个 ROS 2 终端持续发送字符串：

```bash
ros2 topic pub -r 1 /pc_to_cat std_msgs/msg/String "{data: 'hello from pc'}"
```

在 RK3576 的另一个终端检查是否还原为 ROS Topic：

```bash
ros2 topic echo /pc_to_cat std_msgs/msg/String
```

在 RK3576 的另一个终端持续发送三维向量：

```bash
ros2 topic pub -r 1 /cat_to_pc geometry_msgs/msg/Vector3 "{x: 1.0, y: 2.0, z: 3.0}"
```

在 PC 的另一个终端检查：

```bash
ros2 topic echo /cat_to_pc geometry_msgs/msg/Vector3
```

两边的 `echo` 都持续出现对端发送的数据，即表示第二阶段基本链路通过。

## 6. 当前 JSON 封装

PC 的字符串 Topic 示例：

```json
{"source":"pc","type":"ros_topic","seq":1,"timestamp":1788364800000,"topic":"/pc_to_cat","msg_type":"std_msgs/msg/String","data":{"data":"hello from pc"}}
```

RK3576 的向量 Topic 示例：

```json
{"source":"rk3576","type":"ros_topic","seq":1,"timestamp":1788364800010,"topic":"/cat_to_pc","msg_type":"geometry_msgs/msg/Vector3","data":{"x":1.0,"y":2.0,"z":3.0}}
```

该 schema 只用于基本链路测试。后续明确真实 Topic 和消息类型后再定义正式映射。

## 7. 注意事项

- 中继不缓存消息。对端 bridge 离线时发送的数据会丢弃，这是本阶段的预期行为。
- bridge 断线后每 2 秒自动重连；队列只保留最新一条本地消息，避免重连后发送大量过期数据。
- 接收端只接受本阶段约定的来源、Topic 和消息类型，其他 JSON 会被忽略并记录警告。
- ROS 2 DDS 只在每台机器本地工作，跨公网的数据实际走 WebSocket，不要求两台机器能通过
  DDS 互相发现。
- 当前仍是明文、无认证测试链路，不应承载真实控制指令。

## 8. 从零复现步骤

实际验证环境：PC 为 Ubuntu 24.04 / ROS 2 Jazzy，工作空间为
`/home/i4n/Desktop/GDUT`；RK3576 为 Ubuntu 22.04 / ROS 2 Humble，工作空间为
`/home/cat/Desktop/SBGDUT`。跨公网只传 UTF-8 JSON，不要求两端通过 DDS 互相发现。
每个标注“终端”的命令块应在单独终端运行。

### 8.1 构建并测试 RK3576 bridge

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
colcon build --packages-select rk3576_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select rk3576_ws_bridge --event-handlers console_direct+
colcon test-result --verbose
```

构建和测试必须成功，测试数量不能为零。

### 8.2 构建并测试 PC bridge

```bash
cd /home/i4n/Desktop/GDUT
source /opt/ros/jazzy/setup.bash
colcon build --packages-select pc_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select pc_ws_bridge --event-handlers console_direct+
colcon test-result --verbose
```

本次 PC 实际结果：

```text
Summary: 1 package finished
Summary: 32 tests, 0 errors, 0 failures, 0 skipped
```

### 8.3 启动云端中继

在 Windows 云服务器进入脚本目录：

```powershell
py -3.11 relay_server.py
```

确认 PC 入口监听 `0.0.0.0:8770`，RK3576 入口监听 `0.0.0.0:8771`，并在云安全组及
Windows 防火墙放行 TCP 8770、8771。

### 8.4 启动两个 bridge

RK3576 终端 1：

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rk3576_ws_bridge bridge.launch.py
```

PC 终端 1：

```bash
cd /home/i4n/Desktop/GDUT
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

两端都应显示：

```text
公网中继已连接
```

### 8.5 验证 PC 到 RK3576

RK3576 终端 2 先接收：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic echo /pc_to_cat std_msgs/msg/String
```

PC 终端 2 再发送：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 topic pub -r 1 /pc_to_cat std_msgs/msg/String \
  "{data: 'hello from pc jazzy'}"
```

RK3576 应持续显示：

```text
data: hello from pc jazzy
---
```

### 8.6 验证 RK3576 到 PC

PC 终端 3 先接收：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 topic echo /cat_to_pc geometry_msgs/msg/Vector3
```

RK3576 终端 3 再发送。使用以下单行命令可避免错误放置反斜杠：

```bash
source /opt/ros/humble/setup.bash && source /home/cat/Desktop/SBGDUT/install/setup.bash && ros2 topic pub -r 1 /cat_to_pc geometry_msgs/msg/Vector3 "{x: 1.0, y: 2.0, z: 3.0}"
```

PC 应持续显示：

```text
x: 1.0
y: 2.0
z: 3.0
---
```

### 8.7 节点接口与断线重连

PC 新终端检查接口：

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 node info /pc_ws_bridge
```

必须包含：

```text
Subscribers:
  /pc_to_cat: std_msgs/msg/String
Publishers:
  /cat_to_pc: geometry_msgs/msg/Vector3
```

重连验收：

1. 保持两端 `topic pub` 和 `topic echo` 运行。
2. 在 PC bridge 终端按 `Ctrl+C`，等待至少 3 秒。
3. 重新执行第 8.4 节的 PC 启动命令。
4. 确认再次出现“公网中继已连接”，双向 Topic 自动恢复。
5. 确认没有短时间集中补发大量旧消息。

### 8.8 完成判定与当前结果

满足以下条件可判定第二阶段通过：

- PC 与 RK3576 bridge 均连接云端中继。
- RK3576 收到 PC 的 `hello from pc jazzy`。
- PC 收到 RK3576 的 `x=1.0, y=2.0, z=3.0`。
- bridge 重启后自动重连并恢复双向通信。
- 未接入 `/cmd_vel`、底盘或其他真实车辆控制接口。

截至本次记录，公网双向 Topic 已实际验证成功：PC 能读取 RK3576 的 `x/y/z`，RK3576
能读取 PC 的 `hello from pc jazzy`。断线重连需按第 8.7 节单独执行并记录结果。

### 8.9 常见错误

| 现象 | 原因与处理 |
| --- | --- |
| `The passed message type is invalid` | 消息类型后的反斜杠位置错误；使用第 8.6 节单行命令 |
| `Connection refused` | 云端对应端口未监听；PC 检查 8770，RK3576 检查 8771 |
| `Package ... not found` | 未加载 ROS 或工作空间的 `setup.bash` |
| `No module named websockets` | 安装 `python3-websockets` |
| `topic echo` 无输出 | 确认两个 bridge 已连接，并确认发送端 `topic pub` 正在运行 |
| PC 与 RK 无法 DDS 互相发现 | 正常；公网传输使用 WebSocket JSON，不依赖 DDS 发现 |
