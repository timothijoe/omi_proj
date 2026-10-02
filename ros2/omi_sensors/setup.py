from setuptools import setup

setup(
    name="omi_sensors", version="0.1.0", packages=["omi_sensors"],
    python_requires=">=3.10", install_requires=["setuptools", "numpy", "PyYAML"],
    extras_require={"viz": ["Pillow>=9"]},
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/omi_sensors"]),
        ("share/omi_sensors", ["package.xml"]),
        ("share/omi_sensors/config", ["config/sensors.example.json", "config/sdk_dashboard.example.json", "config/sdk_dashboard.rviz"]),
    ],
    entry_points={"console_scripts": ["omi-sensors = omi_sensors.cli:main", "omi-sdk-view = omi_sensors.dashboard_launcher:main"]},
)
