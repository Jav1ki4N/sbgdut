from glob import glob

from setuptools import find_packages, setup


package_name = "pc_ws_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    tests_require=["pytest"],
    zip_safe=True,
    maintainer="SBGDUT",
    maintainer_email="maintainer@example.com",
    description="PC ROS 2 to public WebSocket JSON bridge for link testing.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "bridge_node = pc_ws_bridge.bridge_node:main",
        ],
    },
)
