# openhu-dab: DAB/DAB+ receiver for the OpenHU radio plugin, on top of the DAB library of dab-cmdline
# (J. van Katwijk, GPL-2.0-or-later). The library sources are compiled in (no shared library to install);
# native/build.sh fetches the pinned dab-cmdline source, checks its sha256, applies patches/ and passes it as
# DAB_CMDLINE_DIR.
#
# SPDX-License-Identifier: GPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(openhu-dab VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(DAB_CMDLINE_DIR "" CACHE PATH "dab-cmdline source tree (patched)")
set(DAB_CMDLINE_VERSION "unknown" CACHE STRING "dab-cmdline commit, shown by --version")
if(NOT EXISTS "${DAB_CMDLINE_DIR}/library/dab-api.cpp")
  message(FATAL_ERROR "DAB_CMDLINE_DIR must point to the dab-cmdline sources (native/build.sh does that)")
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(RTLSDR REQUIRED IMPORTED_TARGET librtlsdr)
pkg_check_modules(FFTW3F REQUIRED IMPORTED_TARGET fftw3f)
pkg_check_modules(SAMPLERATE REQUIRED IMPORTED_TARGET samplerate)
pkg_check_modules(ZLIB REQUIRED IMPORTED_TARGET zlib)
find_path(FAAD_INCLUDE_DIR neaacdec.h REQUIRED)
find_library(FAAD_LIBRARY faad REQUIRED)
find_package(Threads REQUIRED)

set(LIB "${DAB_CMDLINE_DIR}/library")
# the source list of library/CMakeLists.txt (dab-cmdline)
set(DAB_SOURCES
  ${LIB}/dab-api.cpp
  ${LIB}/src/dab-processor.cpp
  ${LIB}/src/time-converter.cpp
  ${LIB}/src/ofdm/ensemble.cpp
  ${LIB}/src/ofdm/phasereference.cpp
  ${LIB}/src/ofdm/phasetable.cpp
  ${LIB}/src/ofdm/freq-interleaver.cpp
  ${LIB}/src/ofdm/ofdm-decoder.cpp
  ${LIB}/src/ofdm/sample-reader.cpp
  ${LIB}/src/ofdm/timesyncer.cpp
  ${LIB}/src/ofdm/fic-handler.cpp
  ${LIB}/src/ofdm/fib-config.cpp
  ${LIB}/src/ofdm/fib-decoder.cpp
  ${LIB}/src/ofdm/tii-detector.cpp
  ${LIB}/src/backend/firecode-checker.cpp
  ${LIB}/src/backend/backend-base.cpp
  ${LIB}/src/backend/galois.cpp
  ${LIB}/src/backend/reed-solomon.cpp
  ${LIB}/src/backend/msc-handler.cpp
  ${LIB}/src/backend/virtual-backend.cpp
  ${LIB}/src/backend/audio-backend.cpp
  ${LIB}/src/backend/data-backend.cpp
  ${LIB}/src/backend/audio/mp4processor.cpp
  ${LIB}/src/backend/audio/mp2processor.cpp
  ${LIB}/src/backend/data/virtual-datahandler.cpp
  ${LIB}/src/backend/data/tdc-datahandler.cpp
  ${LIB}/src/backend/data/pad-handler.cpp
  ${LIB}/src/backend/data/data-processor.cpp
  ${LIB}/src/backend/data/mot/mot-handler.cpp
  ${LIB}/src/backend/data/mot/mot-dir.cpp
  ${LIB}/src/backend/data/mot/mot-object.cpp
  ${LIB}/src/support/band-handler.cpp
  ${LIB}/src/support/charsets.cpp
  ${LIB}/src/support/protection.cpp
  ${LIB}/src/support/protTables.cpp
  ${LIB}/src/support/eep-protection.cpp
  ${LIB}/src/support/uep-protection.cpp
  ${LIB}/src/support/fft-handler.cpp
  ${LIB}/src/support/dab-params.cpp
  ${LIB}/src/support/tii_table.cpp
  ${LIB}/src/support/viterbi-spiral/viterbi-spiral.cpp
  ${DAB_CMDLINE_DIR}/devices/device-handler.cpp
)
# Viterbi: SSE2 on amd64 (every x86-64 CPU has it); the generic code elsewhere (the NEON variant of dab-cmdline
# is written for 32 bit ARMv7)
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
  list(APPEND DAB_SOURCES ${LIB}/src/support/viterbi-spiral/spiral-sse.c)
  set(VITERBI_DEFINITIONS SSE_AVAILABLE)
else()
  list(APPEND DAB_SOURCES ${LIB}/src/support/viterbi-spiral/spiral-no-sse.c)
  set(VITERBI_DEFINITIONS)
endif()

add_library(dab STATIC ${DAB_SOURCES})
target_include_directories(dab PUBLIC
  ${DAB_CMDLINE_DIR}
  ${LIB}
  ${LIB}/includes
  ${LIB}/includes/ofdm
  ${LIB}/includes/backend
  ${LIB}/includes/backend/audio
  ${LIB}/includes/backend/data
  ${LIB}/includes/backend/data/mot
  ${LIB}/includes/backend/data/journaline
  ${LIB}/includes/support
  ${LIB}/includes/support/viterbi-spiral
  ${FAAD_INCLUDE_DIR}
)
# the library prints debug output with printf: openhu-dab moves its own stdout (the PCM) away and points fd 1
# at stderr, DEBUG_PRINT goes to stderr directly
target_compile_definitions(dab PUBLIC DAB_API_STATIC DEBUG_PRINT_TO_STDERR=1 ${VITERBI_DEFINITIONS})
# third-party code: its warnings are not ours
target_compile_options(dab PRIVATE -w)
target_link_libraries(dab PUBLIC PkgConfig::FFTW3F PkgConfig::ZLIB ${FAAD_LIBRARY} Threads::Threads ${CMAKE_DL_LIBS})

add_executable(openhu-dab openhu-dab.cpp rtlsdr-device.cpp)
target_compile_options(openhu-dab PRIVATE -Wall -Wextra)
target_compile_definitions(openhu-dab PRIVATE
  OPENHU_DAB_VERSION="${PROJECT_VERSION}" DAB_CMDLINE_VERSION="${DAB_CMDLINE_VERSION}")
target_link_libraries(openhu-dab PRIVATE dab PkgConfig::RTLSDR PkgConfig::SAMPLERATE)
install(TARGETS openhu-dab RUNTIME DESTINATION bin)
