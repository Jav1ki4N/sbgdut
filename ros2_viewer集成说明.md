# ros2_viewer 集成说明

## 1. 目标与架构

将 PC 上的 Qt 程序 `ros2_viewer` 接入现有公网中继，由 RK3576 将 viewer JSON 转换为
ROS 2 Topic。底盘接口和安全策略明确前，不连接真实车辆。

```text
PC ros2_viewer
  ↕ WebSocket JSON（control/status/ping/pong）
云端 relay_server.py：8770 ↔ 8771
  ↕ WebSocket JSON
RK3576 viewer_ws_bridge
  ↕ ROS 2 Topic
仿真节点或车辆节点
```

`ros2_viewer` 本身就是 PC 端 WebSocket 客户端。接入时应停止 `pc_ws_bridge`，两者不能
同时占用云端 PC 角色的 8770 连接。现有 Stage 2 String/Vector3 协议与 viewer 协议不同，
不可直接复用；云端 `relay_server.py` 可以继续使用。

## 2. PC 安装并启动 viewer

程序位置：

```text
/home/i4n/Documents/xwechat_files/wxid_5ili2lbas4pn32_4b93/msg/file/2026-09/ros2_viewer
```

它是 Linux x86-64 程序，只在 PC 上运行。安装缺少的运行库：

```bash
sudo apt update
sudo apt install -y libqt6websockets6 libqt6webenginewidgets6
```

启动：

```bash
chmod +x "/home/i4n/Documents/xwechat_files/wxid_5ili2lbas4pn32_4b93/msg/file/2026-09/ros2_viewer"
"/home/i4n/Documents/xwechat_files/wxid_5ili2lbas4pn32_4b93/msg/file/2026-09/ros2_viewer"
```

界面 WebSocket 地址填写：

```text
ws://8.134.118.29:8770
```

当前已完成 dummy 桥接节点，可以验证控制、状态和延迟，但不发送真实车辆控制。

## 3. RK3576 测试桥接节点

已新增 ROS 2 Humble 包 `viewer_ws_bridge`，不要修改已完成 Stage 2 验收的
`rk3576_ws_bridge`。节点应：

1. 收到 `type: "ping"`，返回相同 `timestamp` 的 `type: "pong"`。
2. 收到 `type: "control"`，严格校验后发布到本地测试控制 Topic。
3. 订阅本地状态 Topic，组合成 `type: "status"` 发给 viewer。
4. WebSocket 连接 `ws://8.134.118.29:8771`，断线自动重连且只保留最新控制帧。

控制字段：

| 字段 | 要求 |
| --- | --- |
| `steer` | 有限数值，范围 `[-1, 1]` |
| `throttle` | 有限数值，范围 `[0, 1]` |
| `brake` | 有限数值，范围 `[0, 1]` |
| `gear` | 整数，语义需确定 |
| `mode` | `manual` 或 `replay` |
| `enable` | 布尔值 |
| `timestamp` | Unix 毫秒整数，拒绝过期消息 |
| `seq` | 递增整数，拒绝重复或倒退 |

状态应完整发送：

```json
{
  "type": "status",
  "x": 1.234,
  "y": 2.345,
  "yaw": 0.785,
  "speed": 0.8,
  "battery": 24.6,
  "traffic": "green"
}
```

## 4. 实现前必须确定的 ROS 映射

| 功能 | 必须确定 |
| --- | --- |
| 控制输出 | Topic、消息类型和 QoS |
| 转向 | `steer` 到转角或角速度的换算与上限 |
| 速度 | 油门、刹车、档位到目标速度的换算与上限 |
| 位置 | odometry Topic、坐标系及 `x/y/yaw` 单位 |
| 速度反馈 | Topic 和单位 m/s |
| 电池 | Topic 和单位 V |
| 交通灯 | Topic 及 green/red/stop 映射 |
| 急停 | 独立急停入口及恢复条件 |

这些内容未确定时，控制只能发布到 dummy Topic，禁止接 `/cmd_vel`。

## 5. 安全规则

- `enable == false` 时立即输出安全停止：油门 0、刹车 1、空挡。
- 通信断开或控制超时后自动安全停止。
- 校验字段类型、范围、有限性、时间戳和序号。
- viewer 急停不能替代 RK3576/底盘侧的独立安全保护。
- 重连后不得补发旧控制帧。
- 首次联调使用仿真器、架空车轮或断开电机动力的环境。

## 6. 推荐实施顺序

1. 启动云端 `relay_server.py`，确认 8770/8771 正常。
2. 启动 viewer，验证连接 8770。
3. 启动已完成的 `viewer_ws_bridge`，验证 ping/pong。
4. 将 control 输出到日志并完成非法消息单元测试。
5. 将 control 发布到 dummy ROS Topic。
6. 用模拟 ROS 状态生成 status JSON，确认 viewer 数值和轨迹刷新。
7. 测试断线重连、控制超时和急停。
8. 明确真实 ROS 映射并通过安全评审后，再连接车辆。

## 7. 验收清单

- [ ] viewer 显示 WebSocket 已连接。
- [ ] viewer 延迟不再显示 `-- ms`，证明 ping/pong 正常。
- [ ] RK3576 能接收并校验 control JSON。
- [ ] control 到达 dummy ROS Topic，非法或过期消息被拒绝。
- [ ] viewer 显示模拟的 x、y、yaw、speed、battery、traffic。
- [ ] 网络断开、bridge 退出和控制超时都会触发安全停止。
- [ ] 重连后不执行旧控制帧。
- [ ] 完成以上测试前未连接真实底盘。

详细字段见 [通信格式](RK3576/SBGDUT/通信格式.md)，viewer 操作见
[操作说明](RK3576/SBGDUT/操作说明.md)，Stage 2 链路见
[第二阶段复现说明](RK3576/SBGDUT/第二阶段ROS2双向Topic测试.md)。

## 8. 已实现：构建与运行

将更新后的 `SBGDUT` 复制到 RK3576 后执行：

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
colcon build --packages-select viewer_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select viewer_ws_bridge --event-handlers console_direct+
colcon test-result --test-result-base build/viewer_ws_bridge --verbose
```

启动 bridge：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 launch viewer_ws_bridge bridge.launch.py
```

新终端观察 viewer 控制与超时停止：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic echo /viewer/control_test std_msgs/msg/String
```

新终端向 viewer 发送模拟状态：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 topic pub -r 5 /viewer/status_test std_msgs/msg/String \
  '{data: "{\"type\":\"status\",\"x\":1.0,\"y\":2.0,\"yaw\":0.5,\"speed\":0.8,\"battery\":24.6,\"traffic\":\"green\"}"}'
```

本次验证结果：

- `viewer_ws_bridge` 构建成功。
- 协议测试 71 项通过，0 errors，0 failures。
- 发布 `/viewer/control_test`，订阅 `/viewer/status_test`。
- 本地 WebSocket 的 ping/pong、control、status 数据流全部通过。
- 0.5 秒控制超时后发布 `enable=false`、油门 0、刹车 1 的安全停止帧。
- PC 的 viewer Qt 依赖已满足，二进制已具备用户执行权限。

以上是在 PC 的 ROS 2 Jazzy 环境完成的兼容验证。RK3576 使用 Humble，复制后必须在 RK3576
本机重新构建并运行测试。
