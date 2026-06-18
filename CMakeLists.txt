cmake_minimum_required(VERSION 3.8)
project(hitos_setup)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

# Generic, type-erased topic-rate monitor (publishes <topic>/hz).
add_executable(topic_hz_monitor src/topic_hz_monitor.cpp)
ament_target_dependencies(topic_hz_monitor rclcpp std_msgs)
install(TARGETS topic_hz_monitor DESTINATION lib/${PROJECT_NAME})

# Ouster internal-osc -> wall-clock offset (IMU-calibrated): imu_recal + clock_offset.
add_executable(ouster_recal_node src/ouster_recal_node.cpp)
ament_target_dependencies(ouster_recal_node rclcpp sensor_msgs std_msgs)
install(TARGETS ouster_recal_node DESTINATION lib/${PROJECT_NAME})

# GPS-only sliding-window smoother (Python) — runnable via ros2 run / launch.
install(PROGRAMS scripts/gps_smoother_node.py DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

install(DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)

install(DIRECTORY scripts/
  DESTINATION share/${PROJECT_NAME}/scripts
)

install(DIRECTORY web_manager/
  DESTINATION share/${PROJECT_NAME}/web_manager
)

install(DIRECTORY systemctl_services/
  DESTINATION share/${PROJECT_NAME}/systemctl_services
)

# Robot model: only the runtime artifacts get installed (URDF + tessellated meshes).
install(DIRECTORY urdf/
  DESTINATION share/${PROJECT_NAME}/urdf
)
install(DIRECTORY meshes/
  DESTINATION share/${PROJECT_NAME}/meshes
)

ament_package()
