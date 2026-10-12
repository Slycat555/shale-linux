cmake_minimum_required(VERSION 3.22)
project(shale-decoration LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ECM 6.0 REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 REQUIRED COMPONENTS Core Gui)
find_package(KF6CoreAddons REQUIRED)
find_package(KDecoration3 REQUIRED)

add_library(org.shale.decoration MODULE shaledecoration.cpp)
target_link_libraries(org.shale.decoration PRIVATE
    Qt6::Core Qt6::Gui KF6::CoreAddons KDecoration3::KDecoration)

install(TARGETS org.shale.decoration DESTINATION ${KDE_INSTALL_PLUGINDIR}/org.kde.kdecoration3)
