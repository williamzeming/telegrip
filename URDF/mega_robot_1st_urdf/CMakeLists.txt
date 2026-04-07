cmake_minimum_required(VERSION 3.8)

project(mega_robot_1st_urdf)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY meshes urdf launch rviz
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
