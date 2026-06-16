from setuptools import find_packages, setup

package_name = 'cobot1'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='lee',
    maintainer_email='lee@todo.todo',
    description='TODO: Package description',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'move_basic = cobot1.move_basic:main',
            'basic_node = cobot1.basic_node:main',
            'move_periodic = cobot1.move_periodic:main',
            'grip_test = cobot1.grip_test:main',
            'force_test = cobot1.force_test:main',
            'mini_jog = dsr_rokey2.mini_jog:main',
            'error_case = cobot1.error_case:main',
            'paper_grip_v1 = cobot1.paper_grip_v1:main',
            'pick_tumbler = cobot1.pick_tumbler:main',
            'rolling = cobot1.rolling_v3:main',
            'paper_to_desk = cobot1.paper_to_desk:main'
        ],
    },
)
