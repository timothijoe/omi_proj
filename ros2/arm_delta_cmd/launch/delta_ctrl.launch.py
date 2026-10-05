from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('robot_ip', default_value='192.168.14.190'),
        DeclareLaunchArgument('arm', default_value='A'),
        DeclareLaunchArgument('delta_topic', default_value='/omi/action/decision'),
        DeclareLaunchArgument('ctrl_rate', default_value='200.0'),
        DeclareLaunchArgument('connect_on_start', default_value='false'),
        DeclareLaunchArgument('motion_authorized', default_value='false'),
        DeclareLaunchArgument('eef_publish_rate', default_value='50.0'),
        DeclareLaunchArgument('delta_timeout', default_value='0.5'),
        DeclareLaunchArgument('max_step_deg', default_value='2.0'),
        DeclareLaunchArgument('delta_splits', default_value='20'),
        DeclareLaunchArgument('delta_frame', default_value='base'),
        DeclareLaunchArgument('calib_mode', default_value='identity'),
        DeclareLaunchArgument('tool_xyzabc', default_value='[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]'),
        DeclareLaunchArgument('envelope_radius_mm', default_value='100.0'),
        DeclareLaunchArgument('start_mode', default_value='3'),
        DeclareLaunchArgument('imp_k', default_value='[6.0, 6.0, 6.0, 5.0, 3.0, 3.0, 2.0]'),
        DeclareLaunchArgument('imp_d', default_value='[0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]'),
        DeclareLaunchArgument('root_frame', default_value='base_link'),
        DeclareLaunchArgument('arm_base_frame', default_value=''),
        DeclareLaunchArgument('publish_root_tf', default_value='urdf'),

        Node(
            package='arm_delta_cmd',
            executable='delta_ctrl_node',
            name='delta_ctrl_node',
            output='screen',
            parameters=[{
                'robot_ip': LaunchConfiguration('robot_ip'),
                'arm': LaunchConfiguration('arm'),
                'delta_topic': LaunchConfiguration('delta_topic'),
                'ctrl_rate': LaunchConfiguration('ctrl_rate'),
                'connect_on_start': LaunchConfiguration('connect_on_start'),
                'motion_authorized': LaunchConfiguration('motion_authorized'),
                'eef_publish_rate': LaunchConfiguration('eef_publish_rate'),
                'delta_timeout': LaunchConfiguration('delta_timeout'),
                'max_step_deg': LaunchConfiguration('max_step_deg'),
                'delta_splits': LaunchConfiguration('delta_splits'),
                'delta_frame': LaunchConfiguration('delta_frame'),
                'calib_mode': LaunchConfiguration('calib_mode'),
                'tool_xyzabc': LaunchConfiguration('tool_xyzabc'),
                'envelope_radius_mm': LaunchConfiguration('envelope_radius_mm'),
                'start_mode': LaunchConfiguration('start_mode'),
                'imp_k': LaunchConfiguration('imp_k'),
                'imp_d': LaunchConfiguration('imp_d'),
                'root_frame': LaunchConfiguration('root_frame'),
                'arm_base_frame': LaunchConfiguration('arm_base_frame'),
                'publish_root_tf': LaunchConfiguration('publish_root_tf'),
            }],
        ),
    ])
