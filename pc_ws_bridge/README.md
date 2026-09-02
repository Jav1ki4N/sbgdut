# pc_ws_bridge

ROS 2 Jazzy bridge for the second-stage GDUT public-network link test.

The node subscribes to `/pc_to_cat` (`std_msgs/msg/String`), sends fixed-schema
JSON to `ws://8.134.118.29:8770`, validates JSON received from the RK3576, and
publishes it on `/cat_to_pc` (`geometry_msgs/msg/Vector3`). It deliberately does
not expose DDS to the public network and does not implement vehicle control.

## Build and test

```bash
cd /home/i4n/Desktop/GDUT
source /opt/ros/jazzy/setup.bash
colcon build --packages-select pc_ws_bridge --symlink-install
source install/setup.bash
colcon test --packages-select pc_ws_bridge --event-handlers console_direct+
colcon test-result --verbose
```

## Run

```bash
source /opt/ros/jazzy/setup.bash
source /home/i4n/Desktop/GDUT/install/setup.bash
ros2 launch pc_ws_bridge bridge.launch.py
```

Parameters can be overridden on the command line or edited in
`config/bridge.yaml`: `server_uri`, `outbound_topic`, `inbound_topic`, and
`reconnect_delay`.
