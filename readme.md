# SBGDUT 远程车端通信与视频系统

本项目用于连接远程上位机与 RK3576/Raspberry Pi 车端，提供三类能力：

- WebSocket JSON 控制、状态和导航数据转发；
- ROS 2 Topic 与公网 WebSocket 之间的桥接；
- 摄像头 H.264/WebRTC 实时视频，在无法点对点直连时通过 TURN 中继。

当前车端视频发送器在 RK3576 上运行；后续迁移到 Raspberry Pi 时保留信令、TURN 和 Qt
viewer，只需根据 RPi 的摄像头与编码器替换 GStreamer pipeline。

## 系统架构

```text
                             JSON / ROS 2
Qt ros2_viewer  ◄──── WebSocket relay 8770–8777 ────► RK/RPi ROS 2 bridge

                              WebRTC 信令
Qt/Firefox       ◄──── 203.195.243.106:8765 ───────► RK/RPi publisher

                              视频媒体
RK/RPi publisher ───► coturn 203.195.243.106:3478 ───► Qt/Firefox
                            UDP 49160–49200

                              Viewer 页面
Qt/Firefox       ◄──── http://203.195.243.106:8080/
```

信令端口 8765 只交换 SDP 和 ICE candidate，8080 只提供网页。视频优先尝试 WebRTC 直连；
无法穿透 NAT 时，coturn 通过 49160–49200 中的动态 UDP 端口中继媒体。

JSON relay 与 WebRTC 是两条独立链路。不要把视频帧放入 8770–8777 的 JSON WebSocket。

## 主要组件

| 组件 | 位置 | 作用 |
| --- | --- | --- |
| `relay_server.py` | `RK3576/SBGDUT/` | 建立成对的公网 JSON WebSocket 端口 |
| `pc_ws_bridge` | `pc_ws_bridge/` | PC ROS 2 Jazzy 与 WebSocket 桥接 |
| `rk3576_ws_bridge` | `RK3576/SBGDUT/rk3576_ws_bridge/` | RK ROS 2 Humble 与 WebSocket 桥接 |
| `viewer_ws_bridge` | `RK3576/SBGDUT/viewer_ws_bridge/` | Qt viewer 控制/状态协议与 ROS 2 桥接 |
| `signaling_server.py` | `RK3576/SBGDUT/webrtc/cloud/` | 一对一 WebRTC 信令 |
| `index.html` | `RK3576/SBGDUT/webrtc/cloud/web/` | Firefox/Qt WebEngine 视频页面 |
| `rk_publisher.py` | `RK3576/SBGDUT/webrtc/` | 摄像头采集、H.264 编码和 WebRTC 发布 |
| `ros2_viewer` | `RK3576/SBGDUT/` | Linux x86-64 Qt 上位机 |

## 端口规划

| 端口 | 协议 | 用途 |
| --- | --- | --- |
| 3478 | TCP/UDP | coturn TURN/STUN 监听与认证 |
| 8080 | TCP | WebRTC viewer 页面 |
| 8765 | TCP | WebRTC WebSocket 信令 |
| 8770 ↔ 8771 | TCP | 控制 JSON 双向转发对 |
| 8772 ↔ 8773 | TCP | 导航/状态 JSON 双向转发对 |
| 8774–8777 | TCP | 预留连接；尚未定义业务路由 |
| 49160–49200 | UDP | TURN 媒体 relay 端口范围 |

云安全组和主机防火墙必须同时允许实际使用的端口。TURN 不能只开放 3478，否则可以完成
认证，却无法通过动态 relay 端口持续传输视频。

## 快速启动：WebRTC 视频

### 云服务器

当前 Ubuntu 24.04 云服务器地址为 `203.195.243.106`，运行以下 systemd 服务：

```bash
sudo systemctl status coturn
sudo systemctl status gdut-signaling
sudo systemctl status gdut-web
```

需要重启时：

```bash
sudo systemctl restart coturn gdut-signaling gdut-web
```

部署目录：

```text
/home/ubuntu/webrtc-cloud/
├── signaling_server.py
└── web/index.html
```

coturn 配置位于 `/etc/turnserver.conf`。完整安装、配置与 systemd 文件见
[WebRTC 视频链路复现与迁移说明](WebRTC视频链路复现与迁移说明.md#11-ubuntu-2404-公网-turn-实际部署记录)。

### RK3576 视频发布端

确认 USB 摄像头设备存在：

```bash
v4l2-ctl --list-devices
```

启动 publisher：

```bash
python3 ~/Downloads/rk_publisher.py
```

默认连接：

```text
信令：ws://203.195.243.106:8765
TURN：turn://203.195.243.106:3478
摄像头：/dev/video0
```

也可以通过环境变量覆盖：

```bash
WEBRTC_CAMERA=/dev/video2 \
WEBRTC_SIGNAL_URL=ws://203.195.243.106:8765 \
WEBRTC_TURN_URL='turn://<USER>:<PASSWORD>@203.195.243.106:3478' \
python3 ~/Downloads/rk_publisher.py
```

当前稳定 pipeline 为：

```text
MJPEG 640×360@30 采集
→ videorate 15 FPS
→ Rockchip mpph264enc CBR 600 kbps，最大 800 kbps，GOP 15
→ RTP/H.264
→ WebRTC/TURN
```

提高分辨率或码率前，必须先确认云服务器公网出带宽。TURN 会让视频经过云服务器，未限制
的 720p30 自动码率可能造成延迟持续累积、画面冻结和 ICE 断线。

### Arch/Qt 上位机

如果 Arch 正在使用 Mihomo VPN，保留 VPN 开启，同时让新云服务器走真实 Wi-Fi：

```bash
sudo ip rule add priority 100 to 203.195.243.106/32 lookup main
ip -4 route get 203.195.243.106
```

期望路径包含：

```text
via 192.168.0.1 dev wlp3s0
```

这条规则重启后消失；网关或网卡名称改变时需要重新确认，正式使用应改为 Mihomo
`DIRECT` 规则或 NetworkManager 持久化策略。

启动 Qt viewer：

```bash
env QTWEBENGINE_CHROMIUM_FLAGS='--disable-features=WebRtcHideLocalIpsWithMdns' \
  /home/i4N/Dev.i4N/Other/sbgdut/RK3576/SBGDUT/ros2_viewer
```

Qt 的 WebRTC 页面地址填写：

```text
http://203.195.243.106:8080/
```

也可以先用 Firefox 独立查看：

```bash
firefox 'http://203.195.243.106:8080/'
```

当前信令只允许一个 viewer。不要同时打开 Firefox 页面和 Qt viewer，否则两者会以关闭码
4001 互相替换并每两秒重连。切换 viewer 时，先停止 publisher、关闭旧 viewer，打开新
viewer 并等待信令连接，再启动 publisher。

不要用带 `timeout 35s` 或 `timeout 45s` 的调试命令长期运行 publisher；时间到后进程会
被主动杀死，viewer 随后显示 `failed`。

## 快速启动：JSON 与 ROS 2 Bridge

### 云端 relay

```bash
python3 RK3576/SBGDUT/relay_server.py
```

当前路由关系：

```text
8770 ⇄ 8771
8772 ⇄ 8773
```

8774–8777 仅接受连接，没有转发目标；“端口正在监听”不代表端口之间已经建立业务桥接。

### PC：ROS 2 Jazzy

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

### RK3576：ROS 2 Humble

```bash
cd /home/cat/Desktop/SBGDUT
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch rk3576_ws_bridge bridge.launch.py
```

Qt viewer 协议使用独立的 `viewer_ws_bridge`：

```bash
source /opt/ros/humble/setup.bash
source /home/cat/Desktop/SBGDUT/install/setup.bash
ros2 launch viewer_ws_bridge bridge.launch.py
```

不要同时让 `pc_ws_bridge` 和 Qt viewer 占用同一个云端角色连接；新连接会替换旧连接。

## Raspberry Pi 迁移

云端 coturn、信令服务、viewer 网页和 Qt 程序无需因车端从 RK3576 换成 RPi 而改变。
RPi 侧需要完成：

1. 确认 USB V4L2 或 CSI/libcamera 摄像头输入；
2. 选择 RPi 可用的 H.264 硬件编码器；
3. 将 `mpph264enc` 替换为 RPi 对应编码器；
4. 保持 H.264 RTP、`webrtcbin`、信令和 TURN 配置；
5. 从保守码率开始，再按云服务器公网带宽逐步提高画质。

RK 的 `mpph264enc` 是 Rockchip 专用元素，不能直接复制到 RPi。USB 摄像头若输出 MJPEG，
可以继续使用 `v4l2src ! jpegparse ! jpegdec`；CSI 摄像头通常需要 `libcamerasrc` 或
`rpicam` 对应接口。

## 配置与安全

当前系统仍属于联调原型：

- 8080 使用 HTTP，8765 使用未加密的 `ws://`；
- 信令没有业务身份认证；
- TURN 使用长期静态凭据，浏览器端凭据对用户可见；
- relay 端口没有面向多车、多用户的会话隔离；
- 同一角色的新连接会替换旧连接。

投入公网长期运行前，应完成：

1. 使用 HTTPS/WSS 和可信证书；
2. 改为短期 TURN REST 凭据并轮换当前联调密码；
3. 为 publisher/viewer 增加认证、设备 ID 和授权；
4. 限制安全组来源，启用日志轮转、带宽监控和健康检查；
5. 为多车场景实现按 room/device 路由，禁止不同用户互相抢占。

云服务器密码、SSH 私钥和正式 TURN 密钥不得提交到仓库。

## 文档索引

- [WebRTC 视频链路部署、迁移与排障](WebRTC视频链路复现与迁移说明.md)
- [Qt ros2_viewer 集成说明](ros2_viewer集成说明.md)
- [操作说明](RK3576/SBGDUT/操作说明.md)
- [通信格式](RK3576/SBGDUT/通信格式.md)
- [第一阶段公网 JSON 双向通信](RK3576/SBGDUT/第一阶段公网JSON双向通信.md)
- [第二阶段 ROS 2 双向 Topic](RK3576/SBGDUT/第二阶段ROS2双向Topic测试.md)
- [PC Bridge README](pc_ws_bridge/README.md)
- [RK3576 Bridge README](RK3576/SBGDUT/rk3576_ws_bridge/README.md)
- [Viewer Bridge README](RK3576/SBGDUT/viewer_ws_bridge/README.md)
