"""Read-only discovery of the receiver's separate policy/manual routes."""
import time
import math
import os


def discovery_environment():
    """Report only ROS discovery settings, never the full process environment."""
    defaults = dict(ROS_DOMAIN_ID='0 (default)', ROS_LOCALHOST_ONLY='unset',
                    ROS_AUTOMATIC_DISCOVERY_RANGE='unset', RMW_IMPLEMENTATION='default')
    return ', '.join(f'{key}={os.environ.get(key, default)}' for key, default in defaults.items())


def resolve_routes(policy, manual, requested='auto'):
    if not policy.startswith('/') or not manual.startswith('/') or policy == manual:
        raise ValueError('Receiver must expose two distinct absolute command topics')
    if policy != '/omi/action/decision':
        raise ValueError('Receiver policy topic does not match /omi/action/decision: '+policy)
    if requested != 'auto' and requested != manual:
        raise ValueError(f'Manual topic mismatch: sender={requested}, receiver={manual}')
    return manual


def motion_connection_ready(values):
    return len(values) == 2 and all(v.type == 1 and v.bool_value for v in values)


def validate_manual_motion(values, expected_rate):
    if (len(values) != 2 or values[0].type != 3 or
            not math.isfinite(values[0].double_value) or
            not math.isclose(values[0].double_value, expected_rate, rel_tol=1e-9)):
        raise ValueError('Receiver manual_command_rate must match sender --rate')
    if values[1].type != 4 or values[1].string_value != 'base':
        raise ValueError('Receiver delta_frame must be base for this mapping')


def subscription_identity(endpoints, *, allow_anonymous=False):
    """Prefer receiver node identity; optionally match one anonymous DDS endpoint.

    Used only after the named receiver parameter service has returned its routes.
    An endpoint with a known, different owner is never treated as anonymous.
    """
    expected_type = 'std_msgs/msg/Float64MultiArray'
    if any(e.node_name == 'delta_ctrl_node' and e.node_namespace == '/'
           and e.topic_type == expected_type for e in endpoints):
        return 'node_name'
    if allow_anonymous and len(endpoints) == 1:
        endpoint = endpoints[0]
        if (endpoint.node_name == '_NODE_NAME_UNKNOWN_' and
                endpoint.node_namespace == '_NODE_NAMESPACE_UNKNOWN_' and
                endpoint.topic_type == expected_type):
            return 'unique_topic_type'
    return None


def inspect_receiver(requested='auto', timeout=5., *, require_manual_receipts=False,
                     require_connected=False, expected_manual_rate=None,
                     allow_anonymous_subscriptions=False):
    import rclpy
    from rcl_interfaces.srv import GetParameters
    rclpy.init()
    node = rclpy.create_node('omi_policy_receiver_preflight', enable_rosout=False)
    try:
        client = node.create_client(GetParameters, '/delta_ctrl_node/get_parameters')
        if not client.wait_for_service(timeout_sec=timeout):
            raise ValueError('Receiver parameter service unavailable; check ROS domain/discovery and receiver process; '
                             + discovery_environment())
        req = GetParameters.Request(names=['delta_topic','manual_delta_topic'])
        future = client.call_async(req)
        rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
        if not future.done() or future.result() is None:
            raise ValueError('Receiver parameter query timed out')
        values = future.result().values
        if len(values) != 2 or any(v.type != 4 for v in values):
            raise ValueError('Receiver command topic parameters are missing or not strings')
        policy, manual = [v.string_value for v in values]
        if expected_manual_rate is not None:
            check = client.call_async(GetParameters.Request(
                names=['manual_command_rate', 'delta_frame']))
            rclpy.spin_until_future_complete(node, check, timeout_sec=timeout)
            if not check.done() or check.result() is None:
                raise ValueError('Receiver motion parameter query timed out')
            validate_manual_motion(check.result().values, expected_manual_rate)
        if require_connected:
            check = client.call_async(GetParameters.Request(
                names=['connect_on_start', 'motion_authorized']))
            rclpy.spin_until_future_complete(node, check, timeout_sec=timeout)
            if (not check.done() or check.result() is None
                    or not motion_connection_ready(check.result().values)):
                raise ValueError('Receiver is not running with robot connection and motion authorization')
        if require_manual_receipts:
            check = client.call_async(GetParameters.Request(names=['hil_manual_receipts']))
            rclpy.spin_until_future_complete(node, check, timeout_sec=timeout)
            if (not check.done() or check.result() is None or len(check.result().values) != 1
                    or check.result().values[0].type != 1 or not check.result().values[0].bool_value):
                raise ValueError('Receiver lacks tagged manual receipts; deploy the updated receiver before collection')
        resolved = resolve_routes(policy, manual, requested)
        deadline = time.monotonic()+timeout
        while True:
            identities = {}
            observed = {}
            for topic in (policy, manual):
                endpoints = node.get_subscriptions_info_by_topic(topic)
                identities[topic] = subscription_identity(
                    endpoints, allow_anonymous=allow_anonymous_subscriptions)
                observed[topic] = [(e.node_name, e.node_namespace, e.topic_type) for e in endpoints]
            if all(identities.values()):break
            if time.monotonic() >= deadline:
                raise ValueError('Receiver subscriptions do not match its configured command topics: '+str(observed))
            rclpy.spin_once(node, timeout_sec=.1)
        return dict(manual_topic=resolved, policy_topic=policy, subscriptions_verified=True,
                    anonymous_subscription_topics=[topic for topic, identity in identities.items()
                                                   if identity == 'unique_topic_type'])
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
