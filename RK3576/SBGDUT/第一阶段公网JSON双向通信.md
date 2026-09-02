# 第一阶段：公网 JSON 双向通信

## 1. 阶段状态

**状态：已完成，双向通信测试成功。**

本阶段不使用 ROS 2，也不传输 `.json` 文件。PC 和 RK3576 将实时数据序列化为 JSON
文本消息，分别主动连接公网云服务器，由云服务器透明转发。

已验证链路：

```text
PC（Wi-Fi）
    │ WebSocket，端口 8770
    ▼
云服务器 8.134.118.29
    ▲
    │ WebSocket，端口 8771
RK3576（手机热点）
```

已确认：

- RK3576 能连接云服务器并持续上传 JSON。
- PC 能连接云服务器并收到 RK3576 的 JSON。
- PC 发出的不同格式 JSON 能经云服务器到达 RK3576。
- RK3576 能响应 PC 的应用层 `ping`，PC 能显示往返延迟 RTT。
- PC 与 RK3576 位于不同网络，证明链路经过公网中继，而非局域网直连。

## 2. 使用的程序

| 设备 | 程序 | 连接地址 | 作用 |
| --- | --- | --- | --- |
| Windows 云服务器 | `relay_server.py` | 监听 `0.0.0.0:8770` 和 `0.0.0.0:8771` | 双向透明转发合法 JSON |
| RK3576 | `rk3576_client.py` | `ws://8.134.118.29:8771` | 发送状态、接收 PC 指令、回复 `ping` |
| Arch Linux PC | `pc_client.py` | `ws://8.134.118.29:8770` | 发送测试指令和 `ping`、接收状态、计算 RTT |

云服务器只负责转发，不修改两端 JSON，不运行 ROS 2，也不负责车辆控制。

## 3. 测试环境

### 云服务器

- 公网 IP：`8.134.118.29`
- 操作系统：Windows Server 2022
- Python：3.11.0
- Python 包：`websockets==11.0.3`

### RK3576

- 架构：ARM64 / `aarch64`
- 系统：Ubuntu 22.04.5 LTS
- Python：3.10.12
- 网络：手机热点

### PC

- 架构：x86-64
- 系统：Arch Linux
- Python：3.14.7
- 网络：Wi-Fi
- 到云服务器的实测 ICMP 延迟约为 34–41 ms

PC 与 RK3576 的系统时间应同步。两端时区可以不同，因为消息中的时间戳使用 Unix
毫秒时间戳；但系统时钟不同步会使单向延迟计算失真。

## 4. 从零复现

### 4.1 配置云平台入口规则

在阿里云或腾讯云控制台的防火墙/安全组中添加入方向规则：

| 协议 | 端口 | 测试阶段来源 |
| --- | ---: | --- |
| TCP | 8770 | PC 的公网出口地址；排障时可临时用 `0.0.0.0/0` |
| TCP | 8771 | RK3576 的公网出口地址；排障时可临时用 `0.0.0.0/0` |

手机热点的公网出口地址可能变化。链路验证完成后，应收紧规则或加入应用层认证。

### 4.2 配置 Windows 防火墙

以管理员身份打开 PowerShell：

```powershell
New-NetFirewallRule -DisplayName "GDUT-PC-8770" -Direction Inbound -Protocol TCP -LocalPort 8770 -Action Allow
New-NetFirewallRule -DisplayName "GDUT-RK3576-8771" -Direction Inbound -Protocol TCP -LocalPort 8771 -Action Allow
```

### 4.3 启动云服务器

安装依赖：

```powershell
py -3.11 -m pip install websockets==11.0.3
```

进入程序目录并启动：

```powershell
cd C:\GDUT
py -3.11 relay_server.py
```

预期输出：

```text
启动双向 JSON 中继
PC     -> ws://<server>:8770
RK3576 -> ws://<server>:8771
```

检查监听：

```powershell
netstat -ano | findstr :8770
netstat -ano | findstr :8771
```

两个端口都应显示 `LISTENING`。

### 4.4 启动 RK3576

安装或升级依赖：

```bash
python3 -m pip install --user "websockets>=10,<12"
```

启动：

```bash
cd ~/Desktop/SBGDUT
python3 rk3576_client.py
```

预期输出：

```text
[连接] ws://8.134.118.29:8771
[已连接] 开始双向 JSON 测试
[发送] seq=1: ...
```

如果 PC 尚未启动，云服务器显示“收到 RK3576 消息，但对端尚未连接”是正常现象。
服务器不会缓存这些消息。

### 4.5 启动 Arch Linux PC

安装依赖并启用网络时间同步：

```bash
sudo pacman -S --needed python-websockets
sudo timedatectl set-ntp true
```

启动：

```bash
python pc_client.py
```

预期输出：

```text
[已连接] 开始 PC <-> RK3576 双向测试
[发送指令] seq=1: ...
[接收数据] {'source': 'rk3576', ...}
[延迟] RTT=... ms，估算单向约 ... ms
```

此时 RK3576 应显示收到 `test_command` 和 `ping`，并显示已经回复 `pong`。

## 5. 正常启动与停止顺序

推荐启动顺序：

1. 启动云服务器 `relay_server.py`。
2. 启动 RK3576 的 `rk3576_client.py`。
3. 启动 PC 的 `pc_client.py`。

PC 和 RK3576 客户端都带自动重连，因此顺序错误不会破坏程序；推荐顺序只是让日志更清晰。

推荐停止顺序：

1. 在 PC 客户端终端按 `Ctrl+C`。
2. 在 RK3576 客户端终端按 `Ctrl+C`。
3. 最后在云服务器终端按 `Ctrl+C`。

如果只是临时断开一端，另一端和云服务器可以继续运行。客户端会在网络恢复后自动重连。

## 6. 当前 JSON 示例

PC 发出的测试指令：

```json
{
  "source": "pc",
  "type": "test_command",
  "seq": 1,
  "timestamp": 1788364800000,
  "command": {
    "name": "link_test",
    "value": 1,
    "message": "hello from pc"
  }
}
```

RK3576 发出的测试状态：

```json
{
  "source": "rk3576",
  "type": "test_status",
  "seq": 1,
  "timestamp": 1788364800010,
  "data": {
    "hostname": "lubancat",
    "message": "hello from rk3576"
  }
}
```

以上格式只用于第一阶段链路验证，不是第二阶段最终 ROS 消息规范。

## 7. 运行注意事项

- `relay_server.py` 每个角色只保留一个连接；新的 PC 或 RK3576 连接会替换旧连接。
- 对端未连接时，服务器直接丢弃消息，不缓存、不补发，适合低延迟控制测试。
- 当前消息上限是 1 MiB，不应通过该链路发送视频或大型文件。
- `ping_interval` 是 WebSocket 连接保活；JSON 中的 `type: ping/pong` 用于应用层延迟测量，二者不同。
- RTT 除以二只是单向延迟估算。上下行路由不对称时，实际单向延迟可能不同。
- RK3576 曾配置本地 HTTP 代理 `127.0.0.1:7897`。使用 `curl` 排障时应加 `--noproxy '*'`，避免测试请求被本地代理截获。
- `LISTENING` 只表示 Windows 本机有程序监听；公网连接仍同时受云安全组和 Windows 防火墙影响。
- 两个客户端会持续每秒发送测试消息，长期运行会产生大量控制台日志。

## 8. 安全边界

当前实现仅用于第一阶段测试，存在以下限制：

- 使用明文 `ws://`，数据未加密。
- 没有账号、令牌或设备身份认证。
- 知道公网 IP 和端口的人可能尝试连接，并替换当前客户端。
- 云端日志可能记录 JSON 的类型和连接地址。

因此不要把真实车辆控制接入当前测试程序。进入实际控制阶段前，至少应增加 `wss://`、
设备认证、消息校验、控制超时和 RK3576/树莓派本地失联保护。

## 9. 常见故障

### RK3576 只显示“连接”

检查云安全组、Windows 防火墙、`relay_server.py` 是否运行，以及 `8771` 是否监听。

直接绕过代理测试：

```bash
curl --noproxy '*' --verbose --max-time 8 http://8.134.118.29:8771/
```

普通 HTTP 请求不一定获得正常网页响应，但不应在 TCP 连接阶段超时。

### 云服务器提示“对端尚未连接”

这不是服务器故障，表示只有一端在线。确认 PC 连接 `8770`、RK3576 连接 `8771`。

### PC 可以 ping 云服务器但程序无法连接

ICMP ping 成功不代表 TCP 端口开放。检查：

```bash
timeout 8 bash -c 'exec 3<>/dev/tcp/8.134.118.29/8770' \
  && echo "8770 reachable" \
  || echo "8770 unreachable"
```

### 延迟明显不合理

两端分别执行：

```bash
date
timedatectl status
```

确保系统时钟已经同步。RTT 本身只依赖 PC 的时间差，但后续比较两端消息时间戳时，两台设备都必须同步。

## 10. 下一阶段

第二阶段在 PC 与 RK3576 分别加入 ROS 2 bridge：订阅本地 ROS 2 Topic，将消息序列化为
JSON 后通过现有云链路发送；对端收到 JSON 后再转换为对应 ROS 2 消息并发布。云服务器的
透明中继结构可以继续使用。
