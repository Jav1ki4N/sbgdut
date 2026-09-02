"""Launch the viewer bridge with its default parameter file."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Build the launch description."""
    config = os.path.join(
        get_package_share_directory("viewer_ws_bridge"), "config", "bridge.yaml"
    )
    return LaunchDescription(
        [
            Node(
                package="viewer_ws_bridge",
                executable="bridge_node",
                name="viewer_ws_bridge",
                output="screen",
                parameters=[config],
            )
        ]
    )
