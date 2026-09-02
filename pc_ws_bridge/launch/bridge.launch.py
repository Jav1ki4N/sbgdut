"""Launch the PC WebSocket bridge with its default parameter file."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    """Build the launch description."""
    config = os.path.join(
        get_package_share_directory("pc_ws_bridge"), "config", "bridge.yaml"
    )
    return LaunchDescription(
        [
            Node(
                package="pc_ws_bridge",
                executable="bridge_node",
                name="pc_ws_bridge",
                output="screen",
                parameters=[config],
            )
        ]
    )
