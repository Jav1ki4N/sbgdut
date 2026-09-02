# 第二阶段 PC 端 Codex 完整交接说明

> 用途：把本文件复制到 PC 的工程目录，然后在该目录启动 Codex，让 PC 端 Codex 完成本阶段
> PC 侧 ROS 2 bridge。本文是实现任务书，不依赖原聊天记录。

## 0. 给 PC 端 Codex 的直接指令

请先完整阅读本文件，再实施。不要参考同目录中的 `.docx`、`.pdf` 或
`webrtc2_gst_server.py` 来决定本阶段协议；它们只是历史参考。以本文件及复制过来的
`通信格式.md`、`第一阶段公网JSON双向通信.md`、`第二阶段ROS2双向Topic测试.md` 为准。

你的任务是：在 PC 上创建并验证标准 ROS 2 Jazzy `ament_python` 包
`pc_ws_bridge`。该节点订阅 PC 本机 `/pc_to_cat`（`std_msgs/msg/String`），转换成本文固定
JSON，经 WebSocket 连接云服务器 `ws://8.134.118.29:8770`；同时接收 RK3576 发来的
JSON，严格校验后发布为 PC 本机 `/cat_to_pc`（`geometry_msgs/msg/Vector3`）。

这只是公网双向基本链路测试，不接真实车辆控制，不实现 `/cmd_vel`，不根据参考论文推测
里程计、雷达、电池、树莓派或底盘接口。完成代码、构建、单元测试和本机节点接口验证后，
再等待 RK3576 在线进行公网端到端验收。

## 1. 已确认的整体目标

项目要验证一台 PC 与一台 RK3576（简称“猫”）在不同网络下，通过公网云服务器双向交换
ROS 2 Topic：

```text
PC（Wi-Fi，Ubuntu 24.04，ROS 2 Jazzy）
  本地 ROS Topic
       ↕
  pc_ws_bridge
       ↕ WebSocket ws://8.134.118.29:8770
  Windows 云服务器 relay_server.py
       ↕ WebSocket ws://8.134.118.29:8771
  rk3576_ws_bridge
       ↕
  RK3576（手机热点，Ubuntu 22.04，ROS 2 Humble）
```

公网段传输 UTF-8 JSON 文本，不传 DDS/RTPS。因此 Humble 与 Jazzy 不需要直接发现彼此，
也不要求相同 ROS 发行版或 `ROS_DOMAIN_ID`。两端只需遵守相同 JSON schema。

## 2. 各机器职责

### 2.1 云服务器

- 公网 IP：`8.134.118.29`
- 操作系统：Windows Server 2022
- 运行现有 `relay_server.py`
- PC 连接 TCP/WebSocket 端口 `8770`
- RK3576 连接 TCP/WebSocket 端口 `8771`
- 服务器只验证合法 JSON 并透明转发原始文本
- 服务器不运行 ROS 2、不转换字段、不缓存消息
- 每个角色只保留一个 WebSocket 连接，新连接替换旧连接

### 2.2 RK3576（已经完成）

- 当前实际机器是 RK3576，不是 PC
- Ubuntu 22.04 / ROS 2 Humble / Python 3.10
- 使用手机热点接入公网
- 标准包：`rk3576_ws_bridge`
- 节点名：`/rk3576_ws_bridge`
- WebSocket：`ws://8.134.118.29:8771`
- 订阅 `/cat_to_pc`，类型 `geometry_msgs/msg/Vector3`
- 发布 `/pc_to_cat`，类型 `std_msgs/msg/String`
- 已通过 `colcon build`
- 已通过 9 项协议单元测试
- 已在 RK3576 实际验证 ROS 发布/订阅接口注册

RK3576 包的协议实现位于：

```text
rk3576_ws_bridge/rk3576_ws_bridge/protocol.py
rk3576_ws_bridge/rk3576_ws_bridge/bridge_node.py
```

如果这些文件也被复制到 PC，请把它们当成协议真值，用镜像方向实现 PC 节点。

### 2.3 PC（本任务）

- 预期 Ubuntu 24.04 / ROS 2 Jazzy
- 使用 Wi-Fi 接入公网
- 创建包 `pc_ws_bridge`
- 节点名 `/pc_ws_bridge`
- WebSocket 默认连接 `ws://8.134.118.29:8770`
- 订阅 `/pc_to_cat` 的 `std_msgs/msg/String`，转 JSON 发给 RK3576
- 接收 RK3576 JSON，发布 `/cat_to_pc` 的 `geometry_msgs/msg/Vector3`

## 3. 第二阶段固定 Topic

两边故意使用不同消息类型，以证明不是简单字符串原样转发：

| 网络方向 | 发送机本地订阅 | 接收机本地发布 | ROS 类型 |
| --- | --- | --- | --- |
| PC → RK3576 | PC `/pc_to_cat` | RK3576 `/pc_to_cat` | `std_msgs/msg/String` |
| RK3576 → PC | RK3576 `/cat_to_pc` | PC `/cat_to_pc` | `geometry_msgs/msg/Vector3` |

不要改 Topic 名、类型、方向或 JSON 字段，除非两端代码和本交接文档同时更新。

## 4. 固定 JSON 协议

### 4.1 通用规则

- 一条 WebSocket 文本消息对应一个完整 JSON 对象
- 编码为 UTF-8
- JSON 顶层必须是对象，不接受数组、标量或二进制帧
- `timestamp` 是 Unix epoch 毫秒整数
- `seq` 是每个发送端从 1 开始递增的整数
- `type` 固定为 `"ros_topic"`
- `msg_type` 使用 ROS 2 完整写法，例如 `std_msgs/msg/String`
- 云服务器透明转发，不修改 JSON
- 本阶段最大 WebSocket 消息为 1 MiB

### 4.2 PC → RK3576

精确示例：

```json
{
  "source": "pc",
  "type": "ros_topic",
  "seq": 1,
  "timestamp": 1788364800000,
  "topic": "/pc_to_cat",
  "msg_type": "std_msgs/msg/String",
  "data": {
    "data": "hello from pc"
  }
}
```

PC 编码规则：

- `source` 必须为 `pc`
- `topic` 必须为 `/pc_to_cat`
- `msg_type` 必须为 `std_msgs/msg/String`
- `data.data` 来自 `String.data`，必须是 JSON string

### 4.3 RK3576 → PC

精确示例：

```json
{
  "source": "rk3576",
  "type": "ros_topic",
  "seq": 1,
  "timestamp": 1788364800010,
  "topic": "/cat_to_pc",
  "msg_type": "geometry_msgs/msg/Vector3",
  "data": {
    "x": 1.0,
    "y": 2.0,
    "z": 3.0
  }
}
```

PC 接收端必须检查：

- 顶层是对象
- `source == "rk3576"`
- `type == "ros_topic"`
- `topic == "/cat_to_pc"`（或配置后的接收 Topic）
- `msg_type == "geometry_msgs/msg/Vector3"`
- `seq` 是非负整数，布尔值不能当整数
- `timestamp` 是非负整数，布尔值不能当整数
- `data` 是对象
- `data.x/y/z` 都是有限数值；布尔值不能当数值

通过校验后创建 `Vector3(x=..., y=..., z=...)` 并发布。无效消息只写 warning 并忽略，
不能导致节点退出。

## 5. PC 包应有的目录结构

建议直接建立以下标准 `ament_python` 结构：

```text
pc_ws_bridge/
├── package.xml
├── setup.py
├── setup.cfg
├── README.md
├── resource/
│   └── pc_ws_bridge
├── config/
│   └── bridge.yaml
├── launch/
│   └── bridge.launch.py
├── pc_ws_bridge/
│   ├── __init__.py
│   ├── protocol.py
│   └── bridge_node.py
└── test/
    └── test_protocol.py
```

`package.xml` 至少声明：

```text
buildtool_depend: ament_python
exec_depend: rclpy
exec_depend: std_msgs
exec_depend: geometry_msgs
exec_depend: python3-websockets
exec_depend: ros2launch
test_depend: python3-pytest
```

`setup.py` 注册：

```python
entry_points={
    "console_scripts": [
        "bridge_node = pc_ws_bridge.bridge_node:main",
    ],
}
```

并安装 `package.xml`、`resource`、`launch/*.launch.py`、`config/*.yaml`。

## 6. PC 节点参数

所有容易变化的值必须用 ROS 参数提供，不要只写成模块常量：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `server_uri` | `ws://8.134.118.29:8770` | PC 连接的云端入口 |
| `outbound_topic` | `/pc_to_cat` | PC 本地订阅 Topic |
| `inbound_topic` | `/cat_to_pc` | PC 本地发布 Topic |
| `reconnect_delay` | `2.0` | 断线重连间隔（秒） |

启动时校验 `server_uri` 以 `ws://` 或 `wss://` 开头，`reconnect_delay > 0`。

## 7. 并发模型要求

推荐保持 RK3576 节点现有模型，避免不必要的线程：

1. 主线程通过 `asyncio.run()` 运行事件循环。
2. 一个协程每约 10 ms 调用一次 `rclpy.spin_once(node, timeout_sec=0)`。
3. ROS 订阅回调把 JSON dict 放入 `asyncio.Queue(maxsize=1)`。
4. 队列满时丢弃旧消息、保留最新消息，防止断线后补发大量过期控制类数据。
5. WebSocket 会话内分别运行发送协程和接收协程。
6. 任意一方结束后取消另一协程，退出连接上下文，再进入重连循环。
7. `websockets.connect` 参数：
   - `open_timeout=10`
   - `ping_interval=20`
   - `ping_timeout=10`
   - `max_size=1024 * 1024`
8. 异常记录类型和信息，等待 `reconnect_delay` 后重连。
9. `asyncio.CancelledError` 必须继续抛出，不能误当普通断线吞掉。
10. Ctrl+C 后销毁节点并执行 `rclpy.shutdown()`。

不要把 ROS DDS 暴露到公网，也不要让 PC 直接连接 RK3576 的 IP。

## 8. 可靠性与安全边界

- 当前是链路测试，不实现 TLS 或身份认证。
- 当前云端连接采用明文 `ws://`。
- 云端不缓存消息，对端离线时消息会丢失，这是预期行为。
- 客户端列只保留最新帧，以降低重连后的陈旧数据风险。
- 不接真实底盘，不发送真实驾驶命令。
- 不要自动扩展到动态任意 ROS 消息反射；本阶段只允许两个固定消息类型。
- 不要因为论文出现 `/cmd_vel` 就实现车辆控制。
- 不要根据 `操作文档.docx` 或 `webrtc2_gst_server.py` 改写这里的协议。

## 9. PC 环境准备

PC 预期是 Ubuntu 24.04 + ROS 2 Jazzy：

```bash
source /opt/ros/jazzy/setup.bash
sudo apt update
sudo apt install -y \
  python3-colcon-common-extensions \
  python3-websockets \
  ros-jazzy-ros-base \
  ros-jazzy-geometry-msgs
```

确认环境：

```bash
printenv ROS_DISTRO
python3 -c 'import rclpy, websockets; print(websockets.__version__)'
ros2 interface show std_msgs/msg/String
ros2 interface show geometry_msgs/msg/Vector3
```

预期 `ROS_DISTRO=jazzy`。脚本也应尽量兼容 Humble，但 PC 的验收标准以 Jazzy 为准。

## 10. 构建与自动测试

从包含 `pc_ws_bridge/` 的工作空间根目录执行：

```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select pc_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select pc_ws_bridge --event-handlers console_direct+
colcon test-result --verbose
```

协议测试至少覆盖：

1. `String` 正确编码为 PC JSON。
2. `Vector3` JSON 正确解析为三个浮点数。
3. 错误 `source` 被拒绝。
4. 错误 `type` 被拒绝。
5. 错误 `topic` 被拒绝。
6. 错误 `msg_type` 被拒绝。
7. 缺少或类型错误的 `x/y/z` 被拒绝。
8. 布尔类型 `x/y/z` 被拒绝。
9. 非法 `seq` 或 `timestamp` 被拒绝。
10. NaN 和 Infinity 被拒绝，避免产生非标准 JSON。

最终必须报告 `0 errors, 0 failures`，不能只运行 `py_compile`。

## 11. PC 本地 ROS 接口验收

先用一个不可达的本地端口验证节点即使 WebSocket 离线也能保持 ROS 接口：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run pc_ws_bridge bridge_node --ros-args \
  -p server_uri:=ws://127.0.0.1:9 \
  -p reconnect_delay:=1.0
```

另一个终端执行：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 node info /pc_ws_bridge
```

必须看到：

```text
Subscribers:
  /pc_to_cat: std_msgs/msg/String
Publishers:
  /cat_to_pc: geometry_msgs/msg/Vector3
```

日志应每约 1 秒提示连接失败并重连，节点不能退出。

## 12. 公网端到端验收步骤

只有在 PC 本地构建和测试通过后才开始。

### 12.1 云服务器

确认 `relay_server.py` 正在运行，并监听：

```text
0.0.0.0:8770  PC
0.0.0.0:8771  RK3576
```

云安全组和 Windows 防火墙必须允许两个 TCP 端口。

### 12.2 RK3576

RK3576 操作者执行：

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rk3576_ws_bridge bridge.launch.py
```

### 12.3 PC

PC 操作者执行：

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

两端都应出现“公网中继已连接”。云服务器应同时显示 PC 和 RK3576 已连接。

### 12.4 PC → RK3576

PC 发布：

```bash
ros2 topic pub -r 1 /pc_to_cat std_msgs/msg/String \
  "{data: 'hello from pc jazzy'}"
```

RK3576 查看：

```bash
ros2 topic echo /pc_to_cat std_msgs/msg/String
```

预期 RK3576 每秒看到：

```text
data: hello from pc jazzy
```

### 12.5 RK3576 → PC

RK3576 发布：

```bash
ros2 topic pub -r 1 /cat_to_pc geometry_msgs/msg/Vector3 \
  "{x: 1.0, y: 2.0, z: 3.0}"
```

PC 查看：

```bash
ros2 topic echo /cat_to_pc geometry_msgs/msg/Vector3
```

预期 PC 每秒看到：

```text
x: 1.0
y: 2.0
z: 3.0
```

### 12.6 断线重连

1. 保持两端 `topic pub` 运行。
2. 停止 PC bridge。
3. 等待至少 3 秒。
4. 重新启动 PC bridge。
5. 确认 PC 自动重新连接，双向 Topic 恢复。
6. 确认没有短时间爆发式补发大量旧消息。

## 13. 完成定义

只有全部满足才算 PC 侧完成：

- [ ] 创建标准 `pc_ws_bridge` ament Python 包
- [ ] `colcon build` 成功
- [ ] 协议测试全部通过且不是 0 tests
- [ ] 节点可以通过 `ros2 run` 启动
- [ ] launch 文件可以启动节点
- [ ] 参数文件可以修改服务器地址 URI 和两个 Topic
- [ ] `ros2 node info` 显示正确发布/订阅接口
- [ ] 无效 JSON 不会导致节点退出
- [ ] WebSocket 断线后自动重连
- [ ] PC → RK3576 的 String 实际跨公网到达
- [ ] RK3576 → PC 的 Vector3 实际跨公网到达
- [ ] 保存两端及云服务器日志作为验收证据

## 14. 给 PC 端 Codex 的汇报格式

完成后请报告：

1. 新增和修改的文件。
2. PC 的 ROS 发行版、Python 和 websockets 版本。
3. `colcon build` 结果。
4. `colcon test-result --verbose` 的测试数量和结果。
5. `ros2 node info /pc_ws_bridge` 的 Topic 接口。
6. 是否已完成真实公网双向验收；如果没有，明确缺少云服务器还是 RK3576 在线配合。
7. 不要声称未实际执行的公网测试已经通过。

## 15. 当前已知事实摘要

- 第一阶段普通 JSON 双向公网链路已经验证成功。
- 云服务器地址 IP 是 `8.134.118.29`。
- 云端 PC 入口是 `8770`，RK3576 入口是 `8771`。
- 云端使用 `websockets==11.0.3`。
- RK3576 使用 Humble；PC 使用 Jazzy是允许的，因为公网段是 JSON。
- RK3576 只负责本阶段通信，不负责最终车辆控制。
- 真实业务 Topic 和正式 schema 尚未定义，本阶段不能自行扩大范围。
