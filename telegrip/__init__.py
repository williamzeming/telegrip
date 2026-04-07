"""
TeleGrip - SO100 robot teleoperation system.
"""

from .config import TelegripConfig, load_config

try:
    from .core.robot_interface import RobotInterface
    from .core.visualizer import PyBulletVisualizer as Visualizer
    from .control_loop import ControlLoop
except Exception:  # pragma: no cover - optional runtime dependencies
    RobotInterface = None
    Visualizer = None
    ControlLoop = None

__version__ = "0.2.0"
__all__ = ["RobotInterface", "Visualizer", "ControlLoop", "TelegripConfig", "load_config"] 