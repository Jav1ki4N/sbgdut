# WebRTC 视频链路复现与迁移说明

本文记录 2026-09-04 至 2026-09-05 完成的 WebRTC 视频链路、实际排障过程，以及如何把
当前 RK3576 验证环境迁移到 Raspberry Pi（RPi）发送端和另一台 Linux/Qt 上位机。

早期验证使用 Windows Server `8.134.118.29`。当前公网方案已经迁移到 Ubuntu 24.04
服务器 `203.195.243.106`；“RK”是本次用于替代 RPi 完成验证的 RK3576，“上位机”是
运行 Firefox 或 `ros2_viewer` 的 Arch Linux PC。

> 当前已经验证：RK3576 与上位机处于不同公网/NAT 网络时，可通过 Ubuntu 上的 coturn
> 中继视频，并在 Firefox 和 Qt `ros2_viewer` 中稳定显示。当前稳定测试配置为
> 640×360@15、目标 600 kbps。真实 RPi 尚未实机验证。

## 1. 最终架构

```text
                          信令（JSON over WebSocket）
RK/RPi publisher ───────────────┐
                               ▼
                     203.195.243.106:8765
                     signaling_server.py
                               ▲
Qt/Firefox viewer ─────────────┘

                          网页（HTTP）
Qt/Firefox viewer ─────► 203.195.243.106:8080/index.html

                       实际视频（WebRTC SRTP）
RK/RPi publisher ─────► 203.195.243.106:3478 coturn ─────► Qt/Firefox viewer
                         UDP 49160–49200 relay
```

云服务器的 8765 只交换 SDP 和 ICE candidate。8080 只提供 HTML/JavaScript 页面。
跨公网验证时，实际视频由 3478 上的 coturn 建立 allocation，再通过 49160–49200 中的
动态 UDP relay 端口中继。ICE 仍会优先尝试直连，无法直连时使用 TURN。

WebRTC 与已有业务端口相互独立：

| 端口 | 用途 |
| --- | --- |
| TCP 8765 | WebRTC 信令 WebSocket |
| TCP 8080 | WebRTC viewer 静态网页 |
| TCP/UDP 3478 | TURN/STUN 监听与认证 |
| UDP 49160–49200 | TURN 实际媒体中继端口范围 |
| TCP 8770 ↔ 8771 | 原有控制 JSON 转发对 |
| TCP 8772 ↔ 8773 | 导航/状态 JSON 转发对；8772 为 `status_node`，8773 为 viewer |
| TCP 8774–8777 | 当前仅监听，没有配置业务转发关系 |

不要把视频帧塞进 8770–8777 的 JSON WebSocket。视频应走 WebRTC 媒体通道。

## 2. 仓库文件

本次新增或修改的相关文件：

```text
RK3576/SBGDUT/webrtc/
├── cloud/
│   ├── signaling_server.py     # 云端一对一信令转发
│   └── web/
│       └── index.html          # 浏览器/Qt WebEngine 视频页面
└── rk_publisher.py             # RK3576 USB 摄像头发送端

RK3576/SBGDUT/relay_server.py    # 8770↔8771、8772↔8773 JSON 转发
RK3576/SBGDUT/ros2_viewer        # Linux x86-64 Qt 上位机程序
```

当前部署文件的校验值：

```text
signaling_server.py
SHA256 F3A0DE5D97D416B44659514DA68999671554E2A2CC35B7F5BCDAEC720725542E

cloud/web/index.html（含自建 TURN）
SHA256 1388D7DF87444719A22141CFC82BDDA626A353495F5A25C287E7EB4988B8ABE2

rk_publisher.py（640×360@15、600 kbps）
SHA256 789093D5C85134F94CEEF36612E3BE4705F33B87F38536BB42FD5C3EF2DB9BE8
```

注意：仓库中的 `index.html` 已同步加入 `controls`。以后如果继续修改文件，哈希自然会改变，
不应再把上面的值当作新版本的固定值。

## 3. 本次实际排障过程与结论

### 3.1 摄像头最初没有出现

RK 最初只有厂商编解码节点：

```text
/dev/video-dec0
/dev/video-enc0
```

它们不是摄像头。USB 摄像头接入后出现：

```text
/dev/video0
/dev/video1
/dev/media0
```

`/dev/video0` 支持 MJPEG 1280×720@30，因而选用 MJPEG 输入，避免使用带宽和帧率较差的
YUYV 1280×720@10。

### 3.2 摄像头采集和编码分别验证成功

摄像头读取测试：

```bash
gst-launch-1.0 -e v4l2src device=/dev/video0 num-buffers=150 \
  ! image/jpeg,width=1280,height=720,framerate=30/1 \
  ! jpegparse ! fakesink sync=false
```

约 5 秒正常 EOS，证明摄像头能够稳定输出 150 帧。

RK MPP 硬件编码测试：

```bash
gst-launch-1.0 -e v4l2src device=/dev/video0 num-buffers=150 \
  ! image/jpeg,width=1280,height=720,framerate=30/1 \
  ! jpegparse ! jpegdec ! videoconvert ! video/x-raw,format=NV12 \
  ! mpph264enc ! h264parse ! fakesink sync=false
```

同样正常 EOS，证明 MJPEG 解码、颜色转换和 H.264 硬件编码链路正常。

### 3.3 `nicesrc` / `nicesink` 缺失

虽然 `webrtcbin` 存在，但 libnice 对应的 GStreamer 元素最初缺失。安装
`gstreamer1.0-nice` 后解决：

```bash
sudo apt update
sudo apt install -y gstreamer1.0-nice
```

完整检查命令：

```bash
for e in webrtcbin nicesrc nicesink dtlssrtpenc v4l2src jpegparse jpegdec \
  mppjpegdec videoconvert mpph264enc h264parse rtph264pay; do
  gst-inspect-1.0 "$e" >/dev/null 2>&1 \
    && printf '%-16s OK\n' "$e" \
    || printf '%-16s MISSING\n' "$e"
done
for m in gi websockets; do
  python3 -c "import $m" >/dev/null 2>&1 \
    && printf 'python:%-9s OK\n' "$m" \
    || printf 'python:%-9s MISSING\n' "$m"
done
```

### 3.4 “能握手”不等于“视频能通过”

云端日志确认以下信令全部成功：

```text
viewer registered
publisher registered
publisher -> viewer | type=offer
viewer -> publisher | type=answer
publisher -> viewer | type=candidate
viewer -> publisher | type=candidate
```

但网页仍显示 `WebRTC: failed`。RK 的 GStreamer 调试日志给出了决定性原因：

```text
adding ICE candidate ... 92ce...local ... typ host
Resolving host 92ce...local
Failed to resolve 92ce...local
ICE connection state ... checking
```

浏览器为了保护本机 IP，把真实局域网地址替换成随机 `.local` mDNS 名称。RK 无法解析该
名称；同时初始配置的 `stun.l.google.com` 没有产生可用的 server-reflexive candidate，导致双方没有
可用路径。这个问题与摄像头、H.264、8765 信令和网页服务器均无关。

针对中国大陆网络，后续默认配置已调整为：RK/RPi 使用
`stun://stun.miwifi.com:3478`；网页依次尝试 `stun.miwifi.com`、`stun.hitv.com` 和
`stun.cloudflare.com`。公共 STUN 没有本项目可依赖的 SLA，正式环境仍需实测或自建。

### 3.5 Firefox 和 Qt 的处理不同

Firefox 中把以下设置改为 `false` 后，网页播放成功：

```text
about:config
media.peerconnection.ice.obfuscate_host_addresses = false
```

Qt `ros2_viewer` 使用 Qt WebEngine，即 Chromium 内核，不会继承 Firefox 的配置。因此
启动 Qt 程序时还需要单独传递：

```text
QTWEBENGINE_CHROMIUM_FLAGS=--disable-features=WebRtcHideLocalIpsWithMdns
```

带该环境变量启动后，Qt 程序内的视频也已实际显示。

## 4. 从零部署云服务器（Windows）

### 4.1 前置条件

云服务器需要：

- Windows Server，可远程桌面登录；
- Python 3.11；
- Python 包 `websockets`；
- 阿里云安全组允许 TCP 8765 和 TCP 8080；
- Windows Defender 防火墙允许 TCP 8765 和 TCP 8080。

检查 Python：

```powershell
py -3.11 --version
```

安装 WebSocket 依赖：

```powershell
py -3.11 -m pip install websockets
```

### 4.2 部署文件

将仓库中的两个文件复制到云服务器：

```text
RK3576/SBGDUT/webrtc/cloud/signaling_server.py
  -> C:\Users\Administrator\Desktop\GDUT\signaling_server.py

RK3576/SBGDUT/webrtc/cloud/web/index.html
  -> C:\Users\Administrator\Desktop\GDUT\web\index.html
```

本次服务器 SSH 22 端口主动关闭，`scp` 无法使用，所以通过远程桌面剪贴板和
PowerShell Base64 分段写入完成。其他环境可使用 SFTP、Git、RDP 文件复制或任意可靠方式，
不要求复用本次很长的 Base64 命令。复制后建议用 `Get-FileHash` 校验。

### 4.3 Windows 防火墙

管理员 PowerShell：

```powershell
New-NetFirewallRule -DisplayName "GDUT-WebRTC-Signaling-8765" `
  -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow

New-NetFirewallRule -DisplayName "GDUT-WebRTC-Web-8080" `
  -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
```

### 4.4 阿里云安全组

在 ECS 控制台为 `8.134.118.29` 所属安全组增加入方向规则：

| 协议 | 端口 | 来源 | 动作 |
| --- | --- | --- | --- |
| TCP | 8765 | `0.0.0.0/0` | 允许 |
| TCP | 8080 | `0.0.0.0/0` | 允许 |

正式部署不建议长期使用 `0.0.0.0/0` 暴露无认证服务，应增加认证、TLS 和来源限制。

### 4.5 启动信令服务

PowerShell 窗口 1：

```powershell
py -3.11 C:\Users\Administrator\Desktop\GDUT\signaling_server.py
```

预期输出：

```text
WebRTC signaling listening on ws://0.0.0.0:8765
server listening on 0.0.0.0:8765
```

### 4.6 启动网页服务

PowerShell 窗口 2：

```powershell
py -3.11 -m http.server 8080 --bind 0.0.0.0 `
  --directory C:\Users\Administrator\Desktop\GDUT\web
```

云服务器本机检查：

```powershell
(Invoke-WebRequest http://127.0.0.1:8080 -UseBasicParsing).StatusCode
```

应输出 `200`。再从上位机打开：

```text
http://8.134.118.29:8080/
```

如果本机是 200、外部打不开，优先检查阿里云安全组，而不是反复修改 Python 服务。
`favicon.ico` 的 404 不影响功能。

## 5. RK3576 发送端复现

### 5.1 本次验证环境

```text
Ubuntu 22.04.5 LTS
Python 3.10.12
GStreamer 1.22.9
USB camera: /dev/video0
输入: MJPEG 1280×720@30
编码: Rockchip mpph264enc
```

推荐依赖：

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-websockets \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-bad-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-nice v4l-utils avahi-daemon libnss-mdns
```

`mpph264enc` 来自 RK3576 厂商 GStreamer/MPP 软件栈，不是 Ubuntu 通用插件。如果缺失，
应安装板卡厂商镜像对应的插件，不能用同名空实现代替。

### 5.2 检查摄像头格式

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```

如摄像头设备不是 `/dev/video0`，启动前可设置：

```bash
export WEBRTC_CAMERA=/dev/video2
```

### 5.3 启动

把仓库中的 `RK3576/SBGDUT/webrtc/rk_publisher.py` 复制到 RK，然后执行：

```bash
export WEBRTC_SIGNAL_URL=ws://8.134.118.29:8765
export WEBRTC_CAMERA=/dev/video0
export WEBRTC_STUN_URL=stun://stun.miwifi.com:3478
python3 rk_publisher.py
```

默认值已经是上述地址和设备，因此本次实际运行命令为：

```bash
python3 ~/Downloads/rk_publisher.py
```

预期关键日志：

```text
camera pipeline started: /dev/video0 (1280x720@30)
connecting signaling: ws://8.134.118.29:8765
signaling registered; creating offer
SDP offer created
browser SDP answer applied
```

`browser SDP answer applied` 只证明 SDP 成功，不代表 ICE 和视频一定成功。

## 6. Arch Linux Qt 上位机复现

### 6.1 依赖

```bash
sudo pacman -S --needed qt6-webengine qt6-websockets sdl2
```

仓库里的 `ros2_viewer` 是 Linux x86-64 ELF，不能在 Windows、ARM RK 或 ARM RPi 上运行。

### 6.2 启动 Qt viewer

在 fish、bash 和 zsh 中都可以用 `env` 传入环境变量：

```bash
env QTWEBENGINE_CHROMIUM_FLAGS='--disable-features=WebRtcHideLocalIpsWithMdns' \
  /home/i4N/Dev.i4N/Other/sbgdut/RK3576/SBGDUT/ros2_viewer
```

Qt WebEngine 不读取 Firefox 的 `about:config`，所以这个环境变量不能省略；否则当前局域网
环境中很可能再次出现 `.local` candidate 和 `WebRTC: failed`。

### 6.3 界面配置

程序启动后：

1. 在顶部“WebRTC 页面”输入框填写 `http://8.134.118.29:8080/`。
2. 点击“加载视频”。
3. 页面先显示“信令已连接，等待视频发送端…”。
4. RK/RPi publisher 上线后，状态应变为 `WebRTC: connected`，视频开始显示。
5. 如果自动播放被拦截，使用视频底部的播放控件。

WebSocket 控制/状态连接是另一条链路，按需要在顶部 WebSocket 输入框填写 8770 或 8773
对应地址；它不影响 WebRTC 视频测试。

### 6.4 Firefox 单独测试

Firefox 地址栏打开 `about:config`，把：

```text
media.peerconnection.ice.obfuscate_host_addresses
```

改成 `false`，然后打开 `http://8.134.118.29:8080/`。测试结束后建议改回 `true`，因为关闭
该保护会向网站暴露真实本地 IP。

## 7. 迁移到 Raspberry Pi

### 7.1 哪些部分无需改变

以下组件与发送板卡无关，可以原样复用：

- 云端 `signaling_server.py`；
- 云端 `index.html`；
- TCP 8765/8080 的防火墙和安全组；
- Qt viewer 的 URL 和启动方式；
- Offer/Answer/ICE JSON 消息格式；
- `rk_publisher.py` 中 WebSocket、SDP、ICE 和重连逻辑。

需要改变的只有摄像头设备、输入格式和 H.264 编码器。

### 7.2 先在 RPi 上盘点环境

在 RPi 上执行：

```bash
uname -a
cat /etc/os-release
python3 --version
gst-launch-1.0 --version
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```

检查通用组件：

```bash
for e in webrtcbin nicesrc nicesink dtlssrtpenc v4l2src jpegparse jpegdec \
  videoconvert x264enc v4l2h264enc h264parse rtph264pay libcamerasrc; do
  gst-inspect-1.0 "$e" >/dev/null 2>&1 \
    && printf '%-16s OK\n' "$e" \
    || printf '%-16s MISSING\n' "$e"
done
for m in gi websockets; do
  python3 -c "import $m" >/dev/null 2>&1 \
    && printf 'python:%-9s OK\n' "$m" \
    || printf 'python:%-9s MISSING\n' "$m"
done
```

RPi 推荐安装：

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-websockets v4l-utils \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-bad-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-nice
```

不同 Raspberry Pi OS/Ubuntu 镜像的插件拆包可能不同。以 `gst-inspect-1.0` 的实际结果
为准，不要仅凭 apt 显示“已安装”判断 WebRTC 元素可用。

### 7.3 USB 摄像头：最通用的 RPi5 方案

如果 RPi 使用与本次相同的 USB 摄像头，并支持 MJPEG 1280×720@30，可先测试采集：

```bash
gst-launch-1.0 -e v4l2src device=/dev/video0 num-buffers=150 \
  ! image/jpeg,width=1280,height=720,framerate=30/1 \
  ! jpegparse ! fakesink sync=false
```

不要在 RPi 上使用 `mpph264enc`，它是 Rockchip 专用元素。RPi5 的保守、通用验证方案是
`x264enc` 软件编码：

```bash
gst-launch-1.0 -e v4l2src device=/dev/video0 num-buffers=150 \
  ! image/jpeg,width=1280,height=720,framerate=30/1 \
  ! jpegparse ! jpegdec ! videoconvert ! video/x-raw,format=I420 \
  ! x264enc tune=zerolatency speed-preset=ultrafast bitrate=2000 key-int-max=30 \
  ! h264parse ! fakesink sync=false
```

如果 720p30 CPU 占用过高，先降为 640×480@30 或 1280×720@15。若 RPi 镜像确实提供
并验证通过 `v4l2h264enc` 或其他硬件编码器，可以再替换 `x264enc`，但不要在未检查插件和
编码质量前假设它一定存在。

### 7.4 修改 publisher 的 RPi pipeline

复制 `rk_publisher.py` 为 `rpi_publisher.py`，保留信令逻辑，只在 `build_pipeline()` 的
pipeline 字符串中把 RK 专用片段：

```text
videoconvert ! video/x-raw,format=NV12 !
mpph264enc !
```

替换为 RPi 通用片段：

```text
videoconvert ! video/x-raw,format=I420 !
x264enc tune=zerolatency speed-preset=ultrafast bitrate=2000 key-int-max=30 !
```

其余部分保持：

```text
h264parse config-interval=-1 !
video/x-h264,stream-format=byte-stream,alignment=au !
rtph264pay config-interval=-1 pt=96 !
application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96 ! webrtc.
```

先用上节 `gst-launch-1.0` 命令验证独立编码链路，再启动 Python publisher。这样能快速区分
摄像头/编码问题和 WebRTC 问题。

### 7.5 CSI 相机注意事项

CSI 相机可能由 `libcamera`/`rpicam-apps` 管理，不一定直接表现为可用的 `/dev/video0`。
需要先用当前 RPi 镜像的 `rpicam-hello`、`rpicam-vid` 或 `libcamerasrc` 验证采集，再根据
实际输出格式构造 pipeline。本文没有在真实 RPi/CSI 相机上验证这条路径，不应直接照抄
USB 摄像头 pipeline。

### 7.6 RPi 最终启动顺序

同一局域网内的最小复现顺序：

1. 云端启动 8765 信令服务器。
2. 云端启动 8080 HTTP 服务。
3. 上位机按第 6 节方式启动 Qt viewer。
4. viewer 填写 `http://8.134.118.29:8080/` 并点击“加载视频”。
5. RPi 启动修改后的 `rpi_publisher.py`。
6. 确认云端出现 offer、answer、双方 candidate 日志。
7. 确认 Qt 页面进入 `connected` 并出现真实画面。

## 8. 常见故障定位

### 网页完全打不开

- 云端本机访问 `127.0.0.1:8080` 是 200、外部打不开：检查阿里云安全组 TCP 8080。
- 本机也打不开：检查 HTTP Python 进程和 Windows 防火墙。

### 页面一直“等待视频发送端”

- publisher 没有运行；
- publisher 无法连接 TCP 8765；
- 云端日志没有 `publisher registered`；
- 同角色的新连接会以 WebSocket code 4001 顶掉旧连接。

### 出现 Offer/Answer，但 `WebRTC: failed`

优先检查 ICE，而不是重新折腾摄像头：

```bash
GST_DEBUG='webrtc*:6,*nice*:6' python3 rk_publisher.py 2>&1 \
  | grep --line-buffered -Ei \
    'error|warning|failed|ice|candidate|connection|state|selected|resolv'
```

如果看到 `.local` 和 `Failed to resolve`：

- Firefox：临时关闭 `media.peerconnection.ice.obfuscate_host_addresses`；
- Qt：使用 `QTWEBENGINE_CHROMIUM_FLAGS` 启动；
- 正式公网：部署 TURN。

### `browser SDP answer applied` 后没有后续日志

这不是“程序卡死”。发送端正在等待 ICE 建连。必须结合网页状态和 GStreamer ICE 日志判断。

### 已连接但视频黑屏

- 点击页面底部播放控件；
- 检查浏览器是否支持 SDP 中的 H.264 profile；
- 检查 publisher 是否持续产生帧；
- 检查 GStreamer bus 是否有编码器错误；
- 在 RPi 上降低分辨率/帧率，排除软件编码跟不上。

### `nicesrc` 或 `nicesink` 缺失

安装 `gstreamer1.0-nice`，再用 `gst-inspect-1.0 nicesrc` 验证。仅有 `webrtcbin` 不代表
ICE transport 插件齐全。

## 9. 当前限制与正式部署

### 9.1 局域网直连与公网 TURN

同一局域网中可以直连。RPi/RK 和上位机分别处于家庭宽带、校园网、移动网络、CGNAT 或
严格防火墙之后时，STUN 只负责发现映射地址，不能保证打洞成功。本项目已增加自建 TURN
作为失败兜底，公网实测媒体路径经过 `203.195.243.106`。

### 9.2 当前 TURN 部署

TURN 提供兜底媒体路径：

```text
RPi ──加密 WebRTC 媒体──► TURN ──加密 WebRTC 媒体──► Qt PC
```

当前采用 Ubuntu 24.04 + coturn，不再依赖 Windows 上的 WSL/Docker。TURN 上线后，跨网
连接不再依赖浏览器暴露局域网 host candidate；Qt 启动时保留关闭 mDNS 的 Chromium flag
仅用于兼容现有测试环境，不再是 TURN 成功的必要条件。

### 9.3 安全与生产化缺口

当前是联调原型，仍需补齐：

- 8080 HTTP 升级为 HTTPS；
- 8765 `ws://` 升级为 `wss://`；
- publisher/viewer 身份认证和授权；
- 短期 TURN 凭据，禁止把长期密钥写入 HTML；
- coturn、信令和网页服务已注册 systemd 并设置开机启动；
- 日志轮转、健康检查和带宽监控；
- 限制一对一会话的抢占权限；
- TURN/信令凭据撤销和密钥轮换。

当前信令服务器对每个角色只保留一个连接，新连接会替换旧连接。它适合单车单 viewer
联调，不是多车、多用户生产信令系统。

## 10. 本次成功验收结果

截至 2026-09-05，以下项目已人工验证：

- [x] RK USB 摄像头 MJPEG 1280×720@30 可读取；
- [x] RK `mpph264enc` H.264 硬件编码链路正常；
- [x] `webrtcbin`、libnice、DTLS-SRTP 元素可用；
- [x] 云端 8765 可从公网 WebSocket 注册；
- [x] 云端 8080 可从公网打开；
- [x] publisher/viewer 的 Offer、Answer、ICE candidate 双向转发；
- [x] Firefox 关闭 mDNS 地址隐藏后显示视频；
- [x] Qt `ros2_viewer` 带 WebEngine flag 启动后显示视频；
- [x] Ubuntu 24.04 coturn 安装、认证、allocation 和 systemd 自启动；
- [x] RK 与 Arch PC 位于不同公网/NAT 时，TURN 双向媒体中继；
- [x] 云端 49160–49200 relay 端口与 PC 双向 UDP 抓包验证；
- [x] Arch 开启 Mihomo/VPN 时用策略路由绕过虚拟网卡；
- [x] 640×360@15、600 kbps 在 Firefox 与 Qt 中稳定播放；
- [ ] 真实 RPi USB/CSI 摄像头尚未实机验证；
- [ ] 720p/更高码率需要按云服务器公网带宽继续调优；
- [ ] HTTPS/WSS、业务身份认证和短期 TURN 凭据尚未完成。

因此当前结论是：**WebRTC 公网 TURN 原型已经端到端成功；迁移到 RPi 时主要工作是按
RPi 实际相机和编码器替换 GStreamer pipeline，并按云服务器公网带宽控制视频码率。**

## 11. Ubuntu 24.04 公网 TURN 实际部署记录

### 11.1 实测环境

```text
Ubuntu 24.04 云服务器
公网 IP：203.195.243.106
VPC 内网 IP：10.1.0.12

RK3576 publisher 公网出口：113.84.9.77
Arch viewer 公网出口：14.153.53.218
Arch 局域网地址：192.168.0.103
```

云厂商通过 NAT 把 `203.195.243.106` 映射到实例网卡的 `10.1.0.12`，所以实例内部
`hostname -I` 看不到公网地址是正常现象。

### 11.2 安装与 coturn 配置

```bash
sudo apt update
sudo apt install -y coturn
```

`/etc/turnserver.conf` 的已验证结构如下。`<TURN_PASSWORD>` 必须替换成随机强密码，不要
照抄仓库或聊天记录中的联调密码：

```ini
listening-port=3478
listening-ip=10.1.0.12
relay-ip=10.1.0.12
external-ip=203.195.243.106/10.1.0.12
min-port=49160
max-port=49200
fingerprint
lt-cred-mech
realm=gdut-webrtc
user=gdut:<TURN_PASSWORD>
stale-nonce=600
no-multicast-peers
no-cli
log-file=/var/log/turnserver.log
simple-log
```

Ubuntu 包安装时可能立即用默认配置启动 coturn。因此，写完配置后必须显式重启，不能只
执行 `enable --now`：

```bash
sudo sed -i 's/^#\?TURNSERVER_ENABLED=.*/TURNSERVER_ENABLED=1/' /etc/default/coturn
sudo install -o turnserver -g turnserver -m 0640 /dev/null /var/log/turnserver.log
sudo systemctl enable coturn
sudo systemctl restart coturn
sudo systemctl --no-pager --full status coturn
```

如果日志出现找不到 TLS certificate/private key 的警告，当前普通 `turn:` UDP/TCP 3478
联调仍可工作；部署 `turns:` TLS 前才需要配置证书和 5349。

### 11.3 腾讯云安全组

入站至少允许：

| 协议 | 端口 | 测试阶段来源 | 用途 |
| --- | --- | --- | --- |
| UDP | 3478 | `0.0.0.0/0` | TURN 首选传输 |
| TCP | 3478 | `0.0.0.0/0` | TURN TCP 兜底 |
| UDP | 49160–49200 | `0.0.0.0/0` | 媒体 relay |
| TCP | 8765 | `0.0.0.0/0` | WebSocket 信令 |
| TCP | 8080 | `0.0.0.0/0` | viewer 页面 |

只开放 3478 不够：3478 用于认证和 allocation，实际媒体由 49160–49200 中选出的端口
转发。本次抓包实际选中了 UDP 49161。

### 11.4 信令和网页 systemd 服务

云端目录：

```text
/home/ubuntu/webrtc-cloud/
├── signaling_server.py
└── web/index.html
```

信令服务 `gdut-signaling.service`：

```ini
[Unit]
Description=GDUT WebRTC Signaling Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/webrtc-cloud
ExecStart=/usr/bin/python3 /home/ubuntu/webrtc-cloud/signaling_server.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

网页服务 `gdut-web.service`：

```ini
[Unit]
Description=GDUT WebRTC Viewer Web Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/webrtc-cloud/web
ExecStart=/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0 --directory /home/ubuntu/webrtc-cloud/web
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gdut-signaling gdut-web
```

### 11.5 Mihomo/VPN 路由问题

Arch PC 开启 Mihomo 后，最初到云服务器的流量被送入虚拟网卡：

```text
203.195.243.106 via 198.18.0.2 dev Mihomo table 2022 src 198.18.0.1
```

真实 Wi-Fi 路径为 `192.168.0.1 dev wlp3s0`。联调时增加高优先级策略，使云服务器流量
保持直连而 VPN 继续用于其他流量：

```bash
sudo ip rule add priority 100 to 203.195.243.106/32 lookup main
ip -4 route get 203.195.243.106
```

期望输出包含：

```text
via 192.168.0.1 dev wlp3s0 src 192.168.0.103
```

这条规则重启后消失；正式使用可交给 NetworkManager dispatcher 或 Mihomo 的直连规则
持久化。若重复添加提示 `File exists`，先用 `ip -4 rule show` 检查现有规则。

### 11.6 已验证低码率 pipeline

未限制码率时，720p30 通过 TURN 出现少量首帧、极端延迟、静止画面和最终断线。抓包确认
媒体已经进入 coturn 并到达 PC，根因是自动码率超过云服务器公网带宽，而不是 TURN、
摄像头或防火墙。

当前稳定设置：

```text
USB 摄像头：MJPEG 640×360@30
编码输出：H.264 640×360@15
码控：CBR
目标：600000 bps
最小：300000 bps
最大：800000 bps
GOP：15（约每秒一个 I 帧）
```

核心 pipeline 片段：

```text
v4l2src device=/dev/video0 !
image/jpeg,width=640,height=360,framerate=30/1 !
jpegparse ! jpegdec ! videoconvert ! videorate !
video/x-raw,format=NV12,framerate=15/1 !
mpph264enc rc-mode=cbr bps=600000 bps-min=300000 bps-max=800000 gop=15 !
h264parse config-interval=-1 ! rtph264pay config-interval=-1 pt=96 ! webrtc.
```

提高画质前先确认云服务器公网出带宽。经验起点：1 Mbps 带宽使用约 700–800 kbps；
3 Mbps 带宽使用 720p15、1.5–2 Mbps；必须为 TURN、DTLS、RTP 和信令保留余量。

### 11.7 Firefox 与 Qt 验证顺序

当前信令服务器每个角色只允许一个连接。Firefox 与 Qt 同时打开时会每两秒互相替换，日志
重复出现 `viewer new connection replaced the old connection` 和关闭码 4001。测试时只保留
一个 viewer：

1. 停止 RK publisher；
2. 关闭其他 Firefox WebRTC 标签页和 Qt viewer；
3. 打开 `http://203.195.243.106:8080/`，等待“信令已连接”；
4. 再执行 `python3 ~/Downloads/rk_publisher.py`，且不要使用 `timeout`；
5. 切换 Firefox/Qt 时先停止 publisher，再按相同顺序启动。

Qt 启动命令：

```bash
env QTWEBENGINE_CHROMIUM_FLAGS='--disable-features=WebRtcHideLocalIpsWithMdns' \
  /home/i4N/Dev.i4N/Other/sbgdut/RK3576/SBGDUT/ros2_viewer
```

Qt 中填写：

```text
http://203.195.243.106:8080/
```

不要把带 `timeout 35s` 或 `timeout 45s` 的调试命令当作正式启动命令；时间到后 publisher
会被主动终止，viewer 随后显示 `failed`，这不是 TURN allocation 过期。

### 11.8 抓包验收证据

本次云端抓包确认：

```text
RK 113.84.9.77:55071 → TURN 10.1.0.12:3478
TURN 10.1.0.12:49161 → PC 14.153.53.218:33284
PC 14.153.53.218:33284 → TURN 10.1.0.12:49161
```

Arch 的 `wlp3s0` 同时捕获到 `203.195.243.106:49161 → 192.168.0.103` 的连续 RTP/SRTP
数据包。因此公网 TURN 的 allocation、权限、双向 relay 和媒体抵达均已实际验证。
