#!/bin/sh
# Build the instrumented DOSBox-X reference emulator.
# autoconf breaks on the spaces in the repo path, so the tree lives in
# $SWOTL_DOSBOX_X_SRC (default ~/.local/src/swotl-dosbox-x) and
# tools/vendor/dosbox-x links to it. Patches apply in tools/patches/ORDER.
set -eu
TAG=dosbox-x-v2026.08.31
REPO=$(cd "$(dirname "$0")/.." && pwd)
SRC=${SWOTL_DOSBOX_X_SRC:-$HOME/.local/src/swotl-dosbox-x}

if [ ! -d "$SRC/.git" ]; then
	git clone --branch "$TAG" --depth 1 https://github.com/joncampbell123/dosbox-x.git "$SRC"
fi
mkdir -p "$REPO/tools/vendor"
ln -sfn "$SRC" "$REPO/tools/vendor/dosbox-x"

cd "$SRC"
if [ "${1:-}" = "--reset" ]; then
	git reset -q --hard "$TAG"
	git clean -fdxq
fi
if git diff --quiet "$TAG" -- . ':!*.in' 2>/dev/null; then
	while read -r patch; do
		git apply "$REPO/tools/patches/$patch"
	done < "$REPO/tools/patches/ORDER"
fi
[ -f configure ] || ./autogen.sh
[ -f Makefile ] || ./configure --enable-debug=heavy --enable-sdl2 --disable-sdl2test \
	--disable-sdl --disable-sdltest --prefix="$SRC/local"
make -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
