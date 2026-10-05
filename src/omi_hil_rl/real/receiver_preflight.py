"""Read-only discovery of the receiver's separate policy/manual routes."""
import time


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


def inspect_receiver(requested='auto', timeout=5., *, require_manual_receipts=False,
                     require_connected=False):
    import rclpy
    from rcl_interfaces.srv import GetParameters
    rclpy.init()
    node = rclpy.create_node('omi_policy_receiver_preflight', enable_rosout=False)
    try:
        client = node.create_client(GetParameters, '/delta_ctrl_node/get_parameters')
        if not client.wait_for_service(timeout_sec=timeout):
            raise ValueError('Receiver parameter service unavailable; check ROS domain/discovery and receiver process')
        req = GetParameters.Request(names=['delta_topic','manual_delta_topic'])
        future = client.call_async(req)
        rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
        if not future.done() or future.result() is None:
            raise ValueError('Receiver parameter query timed out')
        values = future.result().values
        if len(values) != 2 or any(v.type != 4 for v in values):
            raise ValueError('Receiver command topic parameters are missing or not strings')
        policy, manual = [v.string_value for v in values]
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
            found = []
            for topic in (policy, manual):
                endpoints = node.get_subscriptions_info_by_topic(topic)
                found.append(any(e.node_name == 'delta_ctrl_node' and e.node_namespace == '/'
                    and e.topic_type == 'std_msgs/msg/Float64MultiArray' for e in endpoints))
            if all(found):break
            if time.monotonic() >= deadline:
                raise ValueError('Receiver subscriptions do not match its configured command topics')
            rclpy.spin_once(node, timeout_sec=.1)
        return dict(manual_topic=resolved, policy_topic=policy, subscriptions_verified=True)
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
