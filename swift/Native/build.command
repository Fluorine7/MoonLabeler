#!/bin/bash
set -euo pipefail
native_root="$(cd "$(dirname "$0")" && pwd)"
swift_root="$(dirname "$native_root")"
repo_root="$(dirname "$swift_root")"
deps="$swift_root/.build/native-deps"
mkdir -p "$deps"
fetch() {
    local url="$1" name="$2" digest="$3"
    curl --fail --location --retry 2 --max-time 180 --silent --show-error "$url" -o "$deps/$name.partial"
    printf '%s  %s\n' "$digest" "$deps/$name.partial" | shasum -a 256 -c -
    mv "$deps/$name.partial" "$deps/$name"
}
if [ ! -f "$deps/cspice/lib/cspice.a" ]; then
    if [ "$(uname -m)" != arm64 ]; then printf 'This build currently requires an Apple Silicon Mac.\n' >&2; exit 1; fi
    fetch https://naif.jpl.nasa.gov/pub/naif/toolkit/C/MacM1_OSX_clang_64bit/packages/cspice.tar.Z cspice.tar.Z 0deae048443e11ca4d093cac651d9785d4f2594631a183d85a3d58949f4d0aa9
    tar -xzf "$deps/cspice.tar.Z" -C "$deps" cspice/include cspice/lib cspice/doc/html/info
fi
if [ ! -d "$deps/cfitsio-4.6.4" ]; then
    fetch https://heasarc.gsfc.nasa.gov/FTP/software/fitsio/c/cfitsio-4.6.4.tar.gz cfitsio.tar.gz 227b637b91c9820ea96f39a65eb087f053de567d82f4338e2884f123f8183c55
    tar -xzf "$deps/cfitsio.tar.gz" -C "$deps"
fi
if [ ! -d "$deps/erfa-2.0.1" ]; then
    fetch https://codeload.github.com/liberfa/erfa/tar.gz/refs/tags/v2.0.1 erfa.tar.gz d5469fbd0b212b3c7270c1da15c9bd82f37da9218fc89627f98283d27b416cbf
    tar -xzf "$deps/erfa.tar.gz" -C "$deps"
fi
sources="$repo_root/build/temp.macosx-11.0-arm64-cpython-312/opencv/sources"
if [ ! -f "$sources/opencv-0654a42e19215ef25b1d367d822f3c630447e7c7/CMakeLists.txt" ]; then
    sources="$deps"
    if [ ! -d "$sources/opencv-0654a42e19215ef25b1d367d822f3c630447e7c7" ]; then
        fetch https://codeload.github.com/opencv/opencv/tar.gz/0654a42e19215ef25b1d367d822f3c630447e7c7 opencv.tar.gz 7a75663094ebd50bf212928423a24394e29d751db878044ad015ba28546a59db
        tar -xzf "$deps/opencv.tar.gz" -C "$deps"
    fi
    if [ ! -d "$sources/opencv_contrib-a8e9acd62cabd30419dba83007f2ac0d07de5e2c" ]; then
        fetch https://codeload.github.com/opencv/opencv_contrib/tar.gz/a8e9acd62cabd30419dba83007f2ac0d07de5e2c opencv_contrib.tar.gz c96663affc1e6125fc5b630539db83f5bcff19f911c2bbc40e9b7566f86508c9
        tar -xzf "$deps/opencv_contrib.tar.gz" -C "$deps"
    fi
fi
edge="$deps/edgedrawing"
if [ ! -f "$edge/CMakeLists.txt" ]; then
    upstream="$sources/opencv_contrib-a8e9acd62cabd30419dba83007f2ac0d07de5e2c/modules/ximgproc"
    mkdir -p "$edge/src" "$edge/include/opencv2/ximgproc"
    cp "$upstream/src/edge_drawing.cpp" "$upstream/src/edge_drawing_common.hpp" "$upstream/src/precomp.hpp" "$edge/src/"
    cp "$upstream/include/opencv2/ximgproc/edge_drawing.hpp" "$edge/include/opencv2/ximgproc/"
    printf '#pragma once\n#include <opencv2/ximgproc/edge_drawing.hpp>\n' > "$edge/include/opencv2/ximgproc.hpp"
    printf 'set(the_description "MoonLabeler EdgeDrawing")\nocv_define_module(ximgproc opencv_core opencv_imgproc)\n' > "$edge/CMakeLists.txt"
fi
cmake -S "$sources/opencv-0654a42e19215ef25b1d367d822f3c630447e7c7" -B "$swift_root/.build/opencv-native" -G Ninja \
    -C "$repo_root/native/minimal.cmake" -DBUILD_LIST=core,imgproc,flann,features2d,calib3d,ximgproc \
    -DBUILD_opencv_python3=OFF -DBUILD_opencv_python_bindings_generator=OFF -DBUILD_opencv_python_tests=OFF \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DOPENCV_EXTRA_MODULES_PATH="$edge" -DWITH_JPEG=ON -DBUILD_JPEG=ON \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_POSITION_INDEPENDENT_CODE=ON
cmake --build "$swift_root/.build/opencv-native" --parallel 8
cmake -S "$native_root" -B "$swift_root/.build/native-build" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$swift_root/.build/native-build" --parallel 8
