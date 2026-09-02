from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    share = get_package_share_directory("rk3576_ws_bridge")
    parameters = os.path.join(share, "config", "bridge.yaml")
    return LaunchDescription(
        [
            Node(
                package="rk3576_ws_bridge",
                executable="bridge_node",
                name="rk3576_ws_bridge",
                output="screen",
                parameters=[parameters],
            )
        ]
    )
