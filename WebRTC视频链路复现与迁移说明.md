# WebRTC 视频链路复现与迁移说明

本文记录 2026-09-04 完成的 WebRTC 视频链路、实际排障过程，以及如何把当前 RK3576
验证环境迁移到 Raspberry Pi（RPi）发送端和另一台 Linux/Qt 上位机。

文档中的“云服务器”是 Windows Server `8.134.118.29`，“RK”是本次用于替代 RPi
完成验证的 RK3576，“上位机”是运行 Firefox 或 `ros2_viewer` 的 Arch Linux PC。

> 当前已经验证：RK3576 USB 摄像头的视频可以在 Firefox 网页和 Qt `ros2_viewer` 中显示。
> 当前成功路径是局域网 WebRTC 直连；还没有部署 TURN。因此，RPi 和上位机位于不同
> NAT/运营商网络时不能保证成功，详见“当前限制与正式部署”。

## 1. 最终架构

```text
                          信令（JSON over WebSocket）
RK/RPi publisher ───────────────┐
                               ▼
                     8.134.118.29:8765
                     signaling_server.py
                               ▲
Qt/Firefox viewer ─────────────┘

                          网页（HTTP）
Qt/Firefox viewer ─────► 8.134.118.29:8080/index.html

                       实际视频（WebRTC SRTP）
RK/RPi publisher ═════════════════════════════► Qt/Firefox viewer
                         局域网直连
```

云服务器的 8765 只交换 SDP 和 ICE candidate，不承载视频。8080 只提供 HTML/JavaScript
页面，也不承载持续视频流。实际视频在本次验证中从 RK 直接发送给上位机。

WebRTC 与已有业务端口相互独立：

| 端口 | 用途 |
| --- | --- |
| TCP 8765 | WebRTC 信令 WebSocket |
| TCP 8080 | WebRTC viewer 静态网页 |
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

cloud/web/index.html（云端加入 controls 后）
SHA256 6CF72484C1F35289A474AFD19B3D6F0150FE9C13B900B342E2D73DD1D76BBAB9

rk_publisher.py
SHA256 84067420892E5278CC8C6447372D369C561FAB19CB79FDEBA28FCBC9DF4DD23E
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
名称；同时 `stun.l.google.com` 没有产生可用的 server-reflexive candidate，导致双方没有
可用路径。这个问题与摄像头、H.264、8765 信令和网页服务器均无关。

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

### 9.1 当前方案只保证已验证局域网

关闭浏览器 mDNS 隐藏后，真实局域网 IP 会进入 candidate。同一局域网中可以直连；如果
RPi 和上位机分别处于家庭宽带、校园网、移动网络、CGNAT 或严格防火墙之后，即使信令仍然
成功，媒体仍可能失败。

### 9.2 正式公网需要 TURN

TURN 提供兜底媒体路径：

```text
RPi ──加密 WebRTC 媒体──► TURN ──加密 WebRTC 媒体──► Qt PC
```

不想在 Windows 云服务器安装 WSL 时，可选：

1. 使用托管 TURN，例如 Cloudflare Realtime TURN；
2. 在另一台 Linux 云主机部署 coturn；
3. 在 Windows 上运行经过审计和维护的原生 TURN 服务。

TURN 上线后，浏览器应恢复默认隐私设置，Qt 也不再依赖关闭 mDNS 的 Chromium flag。

### 9.3 安全与生产化缺口

当前是联调原型，仍需补齐：

- 8080 HTTP 升级为 HTTPS；
- 8765 `ws://` 升级为 `wss://`；
- publisher/viewer 身份认证和授权；
- 短期 TURN 凭据，禁止把长期密钥写入 HTML；
- 进程注册为 Windows Service/systemd 服务并设置自动重启；
- 日志轮转、健康检查和带宽监控；
- 限制一对一会话的抢占权限；
- TURN/信令凭据撤销和密钥轮换。

当前信令服务器对每个角色只保留一个连接，新连接会替换旧连接。它适合单车单 viewer
联调，不是多车、多用户生产信令系统。

## 10. 本次成功验收结果

截至 2026-09-04，以下项目已人工验证：

- [x] RK USB 摄像头 MJPEG 1280×720@30 可读取；
- [x] RK `mpph264enc` H.264 硬件编码链路正常；
- [x] `webrtcbin`、libnice、DTLS-SRTP 元素可用；
- [x] 云端 8765 可从公网 WebSocket 注册；
- [x] 云端 8080 可从公网打开；
- [x] publisher/viewer 的 Offer、Answer、ICE candidate 双向转发；
- [x] Firefox 关闭 mDNS 地址隐藏后显示视频；
- [x] Qt `ros2_viewer` 带 WebEngine flag 启动后显示视频；
- [ ] 真实 RPi USB/CSI 摄像头尚未实机验证；
- [ ] 不同公网/NAT 下的 TURN 路径尚未部署和验证；
- [ ] HTTPS/WSS、认证与服务自启动尚未完成。

因此当前结论是：**WebRTC 原型已经端到端成功；迁移到 RPi 时主要工作是按 RPi 实际相机
和编码器替换 GStreamer pipeline。若要求任意公网环境稳定工作，下一阶段必须增加 TURN。**
