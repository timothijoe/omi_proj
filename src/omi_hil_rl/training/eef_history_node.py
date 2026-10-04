"""ROS 2 history policy shadow publisher (no hardware executor)."""
import argparse
import json
import time
from .eef_bc_history import PERIOD_NS
from .eef_history_online import OnlineHistoryPolicy


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint',required=True)
    p.add_argument('--wrench-enabled',nargs=2,type=int,choices=(0,1),default=(0,0))
    args,ros_args=p.parse_known_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rcl_interfaces.msg import SetParametersResult
    from sensor_msgs.msg import Image
    from geometry_msgs.msg import PoseStamped, WrenchStamped
    from std_msgs.msg import Float64MultiArray, MultiArrayDimension, String, Empty
    from marvin_msgs.msg import Jointfeedback
    runtime=OnlineHistoryPolicy(args.checkpoint,args.wrench_enabled)
    rclpy.init(args=ros_args)
    node=Node('omi_history_policy')
    action_pub=node.create_publisher(Float64MultiArray,'/omi/history_shadow/action_delta',10)
    status_pub=node.create_publisher(String,'/omi/history_shadow/status',10)
    node.declare_parameter('wrench_enabled',list(args.wrench_enabled))
    runtime.set_wrench_enabled(node.get_parameter('wrench_enabled').value)
    def configure(parameters):
        try:
            for param in parameters:
                if param.name=='wrench_enabled':runtime.set_wrench_enabled(param.value)
            return SetParametersResult(successful=True)
        except ValueError as exc:return SetParametersResult(successful=False,reason=str(exc))
    node.add_on_set_parameters_callback(configure)
    node.create_subscription(Empty,'/omi/history_shadow/reset',lambda _:runtime.reset(),10)
    def receive(key,message):
        try:runtime.ingest(key,message,node.get_clock().now().nanoseconds)
        except (ValueError,AttributeError,KeyError) as exc:
            # A malformed required input must not leave an older valid value active.
            runtime.reset();node.get_logger().warning(f'{key}: reset after invalid input: {exc}')
    for topic,key in runtime.profile.TOPICS.items():
        cls=Jointfeedback if key=='q' else PoseStamped if key=='eef' else WrenchStamped if key.endswith('_wrench') else Image
        node.create_subscription(cls,topic,lambda msg,k=key:receive(k,msg),qos_profile_sensor_data)
    next_reference=None;last_clock=None
    def tick():
        nonlocal next_reference,last_clock
        now=node.get_clock().now().nanoseconds
        if now<=0:return
        if last_clock is not None and now<last_clock:
            runtime.reset();next_reference=None
        last_clock=now
        if next_reference is None:next_reference=now
        if now<next_reference:return
        # Drop missed ticks, never run a burst of expired decisions.
        reference=next_reference+((now-next_reference)//PERIOD_NS)*PERIOD_NS
        next_reference=reference+PERIOD_NS
        started=time.monotonic_ns()
        try:status=runtime.step(reference)
        except (ValueError,KeyError) as exc:
            runtime.reset()
            status=dict(valid=False,reason='invalid_input:'+str(exc),action=None,epoch=runtime.epoch,
                        reference_ns=reference,expires_ns=reference+PERIOD_NS)
        finished=node.get_clock().now().nanoseconds
        status['inference_ms']=(time.monotonic_ns()-started)/1e6
        if finished<reference or finished>=status['expires_ns'] or status['inference_ms']>=100:
            status.update(valid=False,reason='deadline_or_clock_change',action=None)
        if status['valid']:
            msg=Float64MultiArray();msg.data=status['action']
            msg.layout.dim=[MultiArrayDimension(label='base_link:dx,dy,dz[m];rx,ry,rz[rad];'
                f"epoch={status['epoch']};seq={status['sequence']};ref_ns={reference};expires_ns={status['expires_ns']}",size=6,stride=6)]
            action_pub.publish(msg)
        msg=String();msg.data=json.dumps(status,allow_nan=False);status_pub.publish(msg)
    node.create_timer(.01,tick)
    node.get_logger().info('History policy SHADOW: candidates only; 10 Hz; no hardware executor')
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
