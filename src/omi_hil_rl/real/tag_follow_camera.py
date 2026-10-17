"""Shared ROS color-image input for standalone and training tag following."""
import time
import numpy as np


class ROSCamera:
    """Depth-one input; control age starts at local monotonic callback entry.

    The header stamp is retained only for calibration's image/TCP pairing.
    It is not used to accept/reject a frame for following.
    """
    def __init__(self, node, image_topic, info_topic):
        from cv_bridge import CvBridge
        from sensor_msgs.msg import Image, CameraInfo
        from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
        self.node, self.bridge = node, CvBridge()
        self.info = self.latest = self.preview = None
        self.sequence = 0
        self.invalid_reason = 'waiting for CameraInfo/image'
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST)
        node.create_subscription(CameraInfo, info_topic, self.on_info, qos)
        node.create_subscription(Image, image_topic, self.on_image, qos)

    def on_info(self, msg):
        try:
            k = np.asarray(msg.k, dtype=float).reshape(3, 3)
            d = np.asarray(msg.d, dtype=float)
            if (msg.distortion_model not in ('plumb_bob', 'rational_polynomial')
                    or not np.isfinite(k).all() or not np.isfinite(d).all()
                    or d.size not in (0, 4, 5, 8, 12, 14)
                    or k[0, 0] <= 0 or k[1, 1] <= 0 or msg.width <= 0 or msg.height <= 0):
                raise ValueError('invalid CameraInfo or unsupported distortion model')
            self.info = (k, d, msg.width, msg.height, msg.header.frame_id)
        except (ValueError, TypeError) as exc:
            self.info = self.latest = self.preview = None
            self.invalid_reason = str(exc)

    def on_image(self, msg):
        received = time.monotonic()
        self.latest = self.preview = None
        try:
            if self.info is None:
                raise ValueError('waiting for valid CameraInfo')
            k, d, width, height, frame_id = self.info
            if (msg.width, msg.height, msg.header.frame_id) != (width, height, frame_id):
                raise ValueError('image size/frame differs from CameraInfo')
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8').copy()
            self.sequence += 1
            self.preview = (self.sequence, img, stamp, received, k.copy(), d.copy(), frame_id)
            self.latest = self.preview
            self.invalid_reason = ''
        except Exception as exc:
            self.invalid_reason = str(exc)
