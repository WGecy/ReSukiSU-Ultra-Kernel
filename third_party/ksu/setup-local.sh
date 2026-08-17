#!/bin/sh
# setup-local.sh - 自包含版 KernelSU 集成 (无网络操作)
# 前置: KernelSU/ 已由 build.sh 从 third_party/ksu-src 复制 (无 .git)
set -eu

GKI_ROOT=$(pwd)

if test -d "$GKI_ROOT/common/drivers"; then
	DRIVER_DIR="$GKI_ROOT/common/drivers"
elif test -d "$GKI_ROOT/drivers"; then
	DRIVER_DIR="$GKI_ROOT/drivers"
else
	echo '[ERROR] "drivers/" directory not found.'
	exit 127
fi

DRIVER_MAKEFILE=$DRIVER_DIR/Makefile
DRIVER_KCONFIG=$DRIVER_DIR/Kconfig

echo "[+] Setting up KernelSU (local)..."
[ -d "$GKI_ROOT/KernelSU" ] || { echo '[ERROR] KernelSU/ missing'; exit 127; }

cd "$DRIVER_DIR"
ln -sf "$(realpath --relative-to="$DRIVER_DIR" "$GKI_ROOT/KernelSU/kernel")" "kernelsu" && echo "[+] Symlink created."

grep -q "kernelsu" "$DRIVER_MAKEFILE" || printf "\nobj-\$(CONFIG_KSU) += kernelsu/\n" >> "$DRIVER_MAKEFILE" && echo "[+] Modified Makefile."
grep -q "source \"drivers/kernelsu/Kconfig\"" "$DRIVER_KCONFIG" || sed -i "/endmenu/i\source \"drivers/kernelsu/Kconfig\"" "$DRIVER_KCONFIG" && echo "[+] Modified Kconfig."
echo '[+] Done (local).'
