from setuptools import find_packages, setup

package_name = 'arm_delta_cmd'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/delta_ctrl.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dc',
    maintainer_email='dc@todo.todo',
    description='接收10Hz六维增量话题，200Hz关节角控制天机机械臂',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'delta_ctrl_node = arm_delta_cmd.delta_ctrl_node:main',
        ],
    },
)
