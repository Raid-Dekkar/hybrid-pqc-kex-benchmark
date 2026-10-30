#!/usr/bin/env bash
# Build and install liboqs 0.16.0 into $PREFIX.
# Requirements: git, a C compiler, cmake >= 3.18, ninja.
set -euo pipefail
PREFIX="${OQS_INSTALL_PATH:-$HOME/_oqs}"
TAG="0.16.0"
COMMIT="5a1a854b0dc9f2141bdc771c555ee60c37950183"
WORK="$(mktemp -d)"
git clone --depth 1 --branch "$TAG" https://github.com/open-quantum-safe/liboqs "$WORK/liboqs"
test "$(git -C "$WORK/liboqs" rev-parse HEAD)" = "$COMMIT"
# OQS_DIST_BUILD=ON  : portable binary with runtime CPU-feature dispatch
#                      (selects the AVX2 ML-KEM code path when available)
# OQS_USE_OPENSSL=OFF: liboqs uses its built-in SHA-3/SHAKE and the OS RNG
# OQS_MINIMAL_BUILD  : only compile the ML-KEM family (much faster build)
cmake -S "$WORK/liboqs" -B "$WORK/build" -GNinja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
  -DOQS_BUILD_ONLY_LIB=ON -DOQS_DIST_BUILD=ON -DOQS_USE_OPENSSL=OFF \
  -DOQS_MINIMAL_BUILD="KEM_ml_kem_512;KEM_ml_kem_768;KEM_ml_kem_1024" \
  -DCMAKE_INSTALL_PREFIX="$PREFIX"
ninja -C "$WORK/build"
ninja -C "$WORK/build" install
echo "$COMMIT" > "$PREFIX/LIBOQS_COMMIT"
echo "liboqs $TAG installed to $PREFIX"
echo "export OQS_INSTALL_PATH=$PREFIX LD_LIBRARY_PATH=$PREFIX/lib:\${LD_LIBRARY_PATH:-}"
