from setuptools import find_packages, setup


package_name = "vr_input_bridge"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(include=[package_name, f"{package_name}.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", [
            "launch/vr_input_bridge.launch.py",
            "launch/vr_input_with_calibrator.launch.py",
            "launch/vr_input_full.launch.py",
        ]),
        (f"share/{package_name}/web-ui", [
            "web-ui/index.html",
            "web-ui/styles.css",
            "web-ui/interface.js",
            "web-ui/vr_app.js",
            "web-ui/aframe.min.js",
        ]),
    ],
    install_requires=["setuptools", "websockets"],
    zip_safe=True,
    maintainer="Andy",
    maintainer_email="andy@example.com",
    description="Standalone VR web input bridge for ROS 2 teleoperation pipelines.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "vr_input_bridge = vr_input_bridge.main:main_cli",
            "vr_heading_calibrator = vr_input_bridge.heading_calibrator:main",
            "vr_teleop_input_adapter = vr_input_bridge.input_adapter:main",
        ],
    },
)
