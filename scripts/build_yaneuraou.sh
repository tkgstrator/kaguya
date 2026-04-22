#!/usr/bin/env bash
#
# Build a YaneuraOu engine variant and copy the resulting binary into engines/.
#
# Usage:
#   scripts/build_yaneuraou.sh <variant> [options]
#
# Variants (preset → YANEURAOU_EDITION):
#   hkp256       YANEURAOU_ENGINE_NNUE                         (halfKP256, standard NNUE)
#   kp256        YANEURAOU_ENGINE_NNUE_KP256                   (KP256, 2019 baseline)
#   hkp512       YANEURAOU_ENGINE_NNUE_HALFKP_512X2_16_32
#   hkp768       YANEURAOU_ENGINE_NNUE_HALFKP_768X2_16_64      (AobaNNUE HKP768, FV_SCALE=40)
#   hkp1024      YANEURAOU_ENGINE_NNUE_HALFKP_1024X2_8_32
#   hkp1024_64   YANEURAOU_ENGINE_NNUE_HALFKP_1024X2_8_64
#
# Custom variants (BHKP / FMHKP / MHKP) require upstream patches to
# vendor/YaneuraOu and are not listed here yet.
#
# Options:
#   --target <cpu>      Override TARGET_CPU (default: AVX2)
#   --compiler <c>      g++ | clang++ | em++ (default: clang++)
#   --build <target>    Make target: normal | evallearn | tournament
#                       (default: normal — sufficient for match play / baseline engines;
#                        use `evallearn` when you need gensfen / shuffle_kifu)
#   --blas <kind>       OPENBLAS | BLIS | NONE (default: NONE)
#                       NONE skips BLAS entirely; only affects YaneuraOu's built-in
#                       learn command throughput, not gensfen / shuffle_kifu or
#                       nnue-pytorch training.
#   --no-clean          Skip `make clean` before building
#   --suffix <s>        Append to output filename (engines/YaneuraOu-<variant><suffix>)
#
# Output naming:
#   - normal build    → engines/YaneuraOu-<pretty-name>
#   - evallearn build → engines/YaneuraOu-<pretty-name>_learn
#   `<suffix>` if given is appended after `_learn`.

set -euo pipefail

VARIANT=${1:?usage: build_yaneuraou.sh <variant> [options]  (see script header)}
shift || true

TARGET_CPU=AVX2
if command -v clang++ &>/dev/null; then
  COMPILER=clang++
else
  COMPILER=g++
fi
BUILD_TARGET=normal
DO_CLEAN=1
SUFFIX=""
BLAS=NONE

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)   TARGET_CPU=$2;    shift 2 ;;
    --compiler) COMPILER=$2;      shift 2 ;;
    --build)    BUILD_TARGET=$2;  shift 2 ;;
    --blas)     BLAS=$2;          shift 2 ;;
    --suffix)   SUFFIX=$2;        shift 2 ;;
    --no-clean) DO_CLEAN=0;       shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$BLAS" in
  OPENBLAS|BLIS|NONE) ;;
  *) echo "unknown --blas value: $BLAS (expected OPENBLAS | BLIS | NONE)" >&2; exit 2 ;;
esac

case "$VARIANT" in
  hkp256)     EDITION=YANEURAOU_ENGINE_NNUE;                         OUT_NAME=YaneuraOu-HalfKP_256x2-32-32 ;;
  kp256)      EDITION=YANEURAOU_ENGINE_NNUE_KP256;                   OUT_NAME=YaneuraOu-K-P_256-32-32 ;;
  hkp512)     EDITION=YANEURAOU_ENGINE_NNUE_HALFKP_512X2_16_32;      OUT_NAME=YaneuraOu-HalfKP_512x2-16-32 ;;
  hkp768)     EDITION=YANEURAOU_ENGINE_NNUE_HALFKP_768X2_16_64;      OUT_NAME=YaneuraOu-HalfKP_768x2-16-64 ;;
  hkp1024)    EDITION=YANEURAOU_ENGINE_NNUE_HALFKP_1024X2_8_32;      OUT_NAME=YaneuraOu-HalfKP_1024x2-8-32 ;;
  hkp1024_64) EDITION=YANEURAOU_ENGINE_NNUE_HALFKP_1024X2_8_64;      OUT_NAME=YaneuraOu-HalfKP_1024x2-8-64 ;;
  *) echo "unknown variant: $VARIANT" >&2; echo "see script header for supported variants" >&2; exit 2 ;;
esac

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=$REPO_ROOT/vendor/YaneuraOu/source
OUT_DIR=$REPO_ROOT/engines
mkdir -p "$OUT_DIR"

if [[ ! -d $SRC ]]; then
  echo "vendor/YaneuraOu not initialized — run 'git submodule update --init --recursive'" >&2
  exit 3
fi

cd "$SRC"

if [[ $DO_CLEAN -eq 1 ]]; then
  make clean
fi

# Makefile expects BLAS=OPENBLAS|BLIS to pull in BLAS_CPPFLAGS / BLAS_LDFLAGS.
# NONE is represented by passing an empty BLAS so the ifeq guards do not match.
MAKE_BLAS=$BLAS
if [[ $BLAS == NONE ]]; then
  MAKE_BLAS=""
fi

make "$BUILD_TARGET" \
  YANEURAOU_EDITION="$EDITION" \
  COMPILER="$COMPILER" \
  TARGET_CPU="$TARGET_CPU" \
  BLAS="$MAKE_BLAS" \
  -j"$(nproc)"

case "$COMPILER" in
  g++)     BIN_NAME=YaneuraOu-by-gcc ;;
  clang++) BIN_NAME=YaneuraOu-by-clang ;;
  em++)    BIN_NAME=YaneuraOu-by-em ;;
  *)       BIN_NAME=YaneuraOu-by-$(printf '%s' "$COMPILER" | tr -d '+') ;;
esac

SRC_BIN=$SRC/$BIN_NAME
if [[ ! -f $SRC_BIN ]]; then
  echo "expected build output not found: $SRC_BIN" >&2
  exit 4
fi

BUILD_SUFFIX=""
if [[ $BUILD_TARGET == evallearn ]]; then
  BUILD_SUFFIX=_learn
fi

DEST=$OUT_DIR/${OUT_NAME}${BUILD_SUFFIX}${SUFFIX}
cp "$SRC_BIN" "$DEST"
echo "built: $DEST"
