"""
ROS 2 node that converts controller pose streams into RViz-friendly Path topics.

This is intended as a lightweight visualization helper when the user only wants:
- raw VR controller data from telegrip
- latched teleop command poses
- trajectory visualization in RViz2
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

ROS2_IMPORT_ERROR: Optional[Exception] = None

try:
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from nav_msgs.msg import Path
    from rclpy.node import Node
except Exception as exc:  # pragma: no cover - depends on local ROS 2 install
    rclpy = None
    PoseStamped = None
    Path = None
    Node = object
    ROS2_IMPORT_ERROR = exc


@dataclass
class PathStream:
    input_topic: str
    output_topic: str
    poses: Deque[PoseStamped]


class PosePathTracker(Node):
    """Accumulate PoseStamped inputs into bounded Path outputs."""

    def __init__(self, max_points: int = 500):
        super().__init__("pose_path_tracker")
        self.max_points = max(2, int(max_points))
        self.streams: Dict[str, PathStream] = {}
        self.path_publishers: Dict[str, object] = {}

        topic_pairs = {
            "telegrip_left": ("/telegrip/left/pose", "/telegrip/left/path"),
            "telegrip_right": ("/telegrip/right/pose", "/telegrip/right/path"),
            "telegrip_calibrated_left": ("/telegrip_calibrated/left/pose", "/telegrip_calibrated/left/path"),
            "telegrip_calibrated_right": ("/telegrip_calibrated/right/pose", "/telegrip_calibrated/right/path"),
            "teleop_left": ("/teleop/left/command_pose", "/teleop/left/path"),
            "teleop_right": ("/teleop/right/command_pose", "/teleop/right/path"),
        }

        for key, (input_topic, output_topic) in topic_pairs.items():
            self.streams[key] = PathStream(
                input_topic=input_topic,
                output_topic=output_topic,
                poses=deque(maxlen=self.max_points),
            )
            self.path_publishers[key] = self.create_publisher(Path, output_topic, 10)
            self.create_subscription(
                PoseStamped,
                input_topic,
                lambda msg, key=key: self._on_pose(key, msg),
                10,
            )

        self.get_logger().info(
            f"Pose path tracker started with {self.max_points} max points per topic"
        )

    def _on_pose(self, key: str, msg: PoseStamped):
        stream = self.streams[key]
        copied_pose = PoseStamped()
        copied_pose.header = msg.header
        copied_pose.pose.position.x = msg.pose.position.x
        copied_pose.pose.position.y = msg.pose.position.y
        copied_pose.pose.position.z = msg.pose.position.z
        copied_pose.pose.orientation.x = msg.pose.orientation.x
        copied_pose.pose.orientation.y = msg.pose.orientation.y
        copied_pose.pose.orientation.z = msg.pose.orientation.z
        copied_pose.pose.orientation.w = msg.pose.orientation.w

        if stream.poses and stream.poses[-1].header.frame_id != copied_pose.header.frame_id:
            stream.poses.clear()

        stream.poses.append(copied_pose)

        path_msg = Path()
        path_msg.header.stamp = self.get_clock().now().to_msg()
        path_msg.header.frame_id = copied_pose.header.frame_id
        path_msg.poses = list(stream.poses)
        self.path_publishers[key].publish(path_msg)


def parse_args():
    parser = argparse.ArgumentParser(description="Convert telegrip pose topics into Path topics for RViz2")
    parser.add_argument(
        "--max-points",
        type=int,
        default=500,
        help="Maximum number of poses to keep in each published path",
    )
    return parser.parse_args()


def main():
    if ROS2_IMPORT_ERROR is not None:
        raise RuntimeError(
            "ROS 2 Python dependencies are unavailable. "
            "Please source your ROS 2 environment before running this node."
        ) from ROS2_IMPORT_ERROR

    args = parse_args()
    rclpy.init(args=None)
    node = PosePathTracker(max_points=args.max_points)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
