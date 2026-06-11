cmake_minimum_required(VERSION 3.8)
project(hitos_setup)

find_package(ament_cmake REQUIRED)

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

ament_package()
