#!/usr/bin/env python3
"""
补丁应用 - 由 config.yaml 的 features 开关驱动
每个 feature 对应一个补丁文件, 简单直接
"""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class PatchError(Exception):
    pass


def run(cmd, cwd=None, check=True):
    cwd = str(cwd) if cwd else None
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0 and check:
        tail = (r.stderr or r.stdout or "")[-2000:]
        raise PatchError(f"命令失败: {cmd}\n{tail}")
    return r


# feature -> 补丁文件路径 (相对 patches/)
FEATURE_PATCHES = {
    "mthp":            "03-mm/08-mthp.patch",
    "lru_gen_export":  "03-mm/16-lru-gen-export.patch",
    "ufs_fastdiscard": "04-block-io/07-ufs-fastdiscard.patch",
    "ssg":             "04-block-io/15-ssg.patch",
    "zstd":            "04-block-io/zstd-1.5.7.patch",
    "bbr3":            "05-net/06-bbrv3.patch",
    "cpuidle":         "07-drivers/09-cpuidle.patch",
    "thermal_offset":  "08-thermal/thermal-offset.patch",
    "perf_tune":       "06-tune/performance-tune.patch",
    "vm_defaults":     "06-tune/vm-defaults.patch",
}

# OS3 时代逆向自建模块 (2026-08-14 退役): OS4 官方已内置/直装, 与官方冲突
# 已归档到 patches/11-os3-retired/, 不再启用
RETIRED_PATCHES = {
    "binder_prio":       "11-os3-retired/01-binder-prio.patch",
    "kshrink_slabd":     "11-os3-retired/02-kshrink-slabd.patch",
    "tesla_guard":       "11-os3-retired/03-tesla-guard.patch",
    "dynamic_readahead": "11-os3-retired/06-dynamic-readahead.patch",
    "mi_wq":             "11-os3-retired/07-mi-wq-dynamic-priority.patch",
}


def apply_adios(common):
    """ADIOS: 补丁"""
    return apply_patch("04-block-io/14-adios.patch", common)


def apply_patch(rel_path, common):
    pfile = ROOT / "patches" / rel_path
    if not pfile.exists():
        raise PatchError(f"补丁文件缺失: {rel_path}")
    # git apply 优先 (正确处理 new file; patch 对 new file 会误判 delete)
    r = run(f"git apply --check {pfile}", cwd=common, check=False)
    if r.returncode == 0:
        run(f"git apply {pfile}", cwd=common)
        return "✓"
    # git apply 失败 → 已应用? → patch fallback
    r2 = run(f"git apply --check -R {pfile}", cwd=common, check=False)
    if r2.returncode == 0:
        return "已应用, 跳过"
    r3 = run(f"patch -p1 -F 3 -N --batch < {pfile}", cwd=common, check=False)
    if r3.returncode != 0:
        # patch -N 对"已内置/已应用"的目标值会产生 Reversed + .rej 并返回非 0
        # (如 6.6.118 官方已内置 perf_tune/zstd 目标值)。判定:
        #   含 Reversed 且不含真 FAILED → 已内置/已应用, 清理 .rej 后跳过
        #   否则 → 真冲突
        out = (r3.stdout or "") + (r3.stderr or "")
        if "Reversed" in out and "FAILED" not in out:
            for rej in Path(common).rglob("*.rej"):
                rej.unlink()
            return "已内置/已应用, 跳过"
        raise PatchError(f"补丁冲突 [{rel_path}]:\n{out[-1000:]}")
    return "✓"


def apply_zram_lz4kd(common):
    """zram LZ4 补丁栈 (参照 zzh build.yml / T-677 SukiSU_patch 平铺结构)"""
    z = ROOT / "third_party" / "zram-stack"
    # LZ4 1.10 + NEON
    for f in ("lib/lz4/lz4_compress.c", "lib/lz4/lz4_decompress.c",
              "lib/lz4/lz4defs.h", "lib/lz4/lz4hc_compress.c"):
        (common / f).unlink(missing_ok=True)
    shutil.copytree(z / "lz4", common / "lib" / "lz4", dirs_exist_ok=True)
    shutil.copytree(z / "include" / "linux", common / "include" / "linux", dirs_exist_ok=True)
    run(f"bash {z/'apply_lz4_neon.sh'}", cwd=common)
    # lz4k (平铺: lz4k/include lz4k/lib lz4k/crypto)
    l4k = z / "lz4k"
    shutil.copytree(l4k / "include" / "linux", common / "include" / "linux", dirs_exist_ok=True)
    shutil.copytree(l4k / "lib", common / "lib", dirs_exist_ok=True)
    shutil.copytree(l4k / "crypto", common / "crypto", dirs_exist_ok=True)
    shutil.copytree(z / "lz4k_oplus", common / "lib" / "lz4k_oplus", dirs_exist_ok=True)
    # lz4kd / lz4k_oplus patch (已应用检测: patch -R dry-run 通过即跳过)
    for name in ("lz4kd.patch", "lz4k_oplus.patch"):
        p = z / "zram_patch" / "6.6" / name
        if p.exists():
            r2 = run(f"patch -p1 -F 3 -R --dry-run < {p}", cwd=common, check=False)
            if r2.returncode == 0:
                continue
            r = run(f"patch -p1 -F 3 -N --batch < {p}", cwd=common, check=False)
            if r.returncode != 0:
                raise PatchError(f"zram {name} 应用失败:\n{r.stderr[-800:]}")
    f2fs = common / "fs" / "f2fs" / "Makefile"
    line = "f2fs-$(CONFIG_F2FS_IOSTAT) += iostat.o"
    if f2fs.exists() and line not in f2fs.read_text():
        with open(f2fs, "a") as f:
            f.write(line + "\n")
    return "✓"


def apply_fusebpf(common):
    """FUSEBPF 修复 (补丁随 KSU 仓库走: build/repo/KernelSU/kernel-patches/fusebpf/)"""
    d = KSU_PATCH_DIR = ROOT / "build" / "repo" / "KernelSU" / "kernel-patches" / "fusebpf"
    if not d.exists():
        # 回退到本地 third_party (KSU 未拉取时)
        d = ROOT / "third_party" / "fusebpf"
    for name in ("fusebpf-lookup-revalidate.patch", "fusebpf-no-eexist.patch"):
        p = d / name
        if not p.exists():
            raise PatchError(f"fusebpf 补丁缺失: {name}")
        r = run(f"patch -p1 -F 3 -N --batch < {p}", cwd=common, check=False)
        if r.returncode != 0:
            r2 = run(f"patch -p1 -F 3 -R --dry-run < {p}", cwd=common, check=False)
            if r2.returncode == 0:
                continue
            raise PatchError(f"fusebpf {name} 应用失败:\n{r.stderr[-800:]}")
    return "✓"


def apply_unicode_bypass(common):
    """Unicode 零宽字符绕过 (SUSFS 相关)"""
    p = ROOT / "patches" / "09-android" / "unicode_bypass_fix_6.1+.patch"
    if not p.exists():
        raise PatchError(f"补丁缺失: {p}")
    r = run(f"patch -p1 --forward < {p}", cwd=common, check=False)
    if r.returncode != 0:
        r2 = run(f"patch -p1 -R --dry-run < {p}", cwd=common, check=False)
        if r2.returncode == 0:
            return "已应用, 跳过"
        # SUSFS 未开启时可能无上下文, 给警告不中断
        print(f"  ! unicode_bypass 应用失败 (可能需 SUSFS): {r.stderr[-500:]}")
        return "跳过 (需 SUSFS)"
    return "✓"


def apply_cve_fix(common, sublevel):
    """CVE-2026-43499 rtmutex 修复链 (T-677 同款脚本)"""
    sp = ROOT / "third_party" / "security_patch"
    script = sp / "apply_cve_2026_43499.sh"
    if not script.exists():
        raise PatchError(f"CVE 脚本缺失: {script}")
    r = run(f"bash {script} 6.6 {sublevel} {sp}", cwd=common, check=False)
    if r.returncode != 0:
        raise PatchError(f"CVE 修复链失败:\n{r.stderr[-800:]}")
    return "✓"


def apply_lts_fixes(common):
    """LTS 官方修复 (01-baseline 目录所有补丁)"""
    d = ROOT / "patches" / "01-baseline"
    if not d.exists():
        raise PatchError(f"LTS 补丁目录缺失: {d}")
    n = 0
    for p in sorted(d.glob("*.patch")):
        r = run(f"patch -p1 -F 3 -N --batch < {p}", cwd=common, check=False)
        if r.returncode != 0:
            r2 = run(f"patch -p1 -F 3 -R --dry-run < {p}", cwd=common, check=False)
            if r2.returncode == 0:
                continue
            raise PatchError(f"LTS {p.name} 应用失败:\n{r.stderr[-800:]}")
        n += 1
    return f"✓ ({n} 个)"


def apply_uksm(common):
    """UKSM 补丁 (T-677 同款顺序: 先主补丁 10 创建 uksm.c, 再应用其余增量)"""
    d = ROOT / "patches" / "03-mm" / "uksm"
    if not d.exists():
        raise PatchError(f"UKSM 补丁目录缺失: {d}")
    main = d / "10-97a4fd7e.patch"
    if not main.exists():
        raise PatchError(f"UKSM 主补丁缺失: {main}")
    n = 0
    # 1. 主补丁 (创建 mm/uksm.c)
    r = run(f"patch -p1 -F 3 -N --batch < {main}", cwd=common, check=False)
    if r.returncode != 0:
        r2 = run(f"patch -p1 -F 3 -R --dry-run < {main}", cwd=common, check=False)
        if r2.returncode != 0:
            raise PatchError(f"UKSM 主补丁失败:\n{r.stderr[-800:]}")
    else:
        n += 1
    # 2. 增量补丁 (跳过主补丁)
    for p in sorted(d.glob("[0-9][0-9]-*.patch")):
        if p.name == main.name:
            continue
        r = run(f"patch -p1 -F 3 -N --batch < {p}", cwd=common, check=False)
        if r.returncode != 0:
            r2 = run(f"patch -p1 -F 3 -R --dry-run < {p}", cwd=common, check=False)
            if r2.returncode == 0:
                continue
            raise PatchError(f"UKSM {p.name} 失败:\n{r.stderr[-800:]}")
        n += 1
    return f"✓ ({n} 个应用)"


def apply_bbg(common, kernel_root):
    """BBG 防格机 (需网络下载 setup.sh, 失败跳过)"""
    import subprocess
    r = subprocess.run("timeout 120 wget -qO- https://github.com/vc-teahouse/Baseband-guard/raw/main/setup.sh | bash",
                       shell=True, cwd=kernel_root, capture_output=True, text=True, timeout=150)
    if r.returncode != 0:
        print(f"  ! BBG 下载失败, 跳过 (不影响构建): {r.stderr[-300:]}")
        return "跳过 (网络失败)"
    # defconfig + LSM (T-677 同款: config LSM 块内 default 行尾追加 baseband_guard)
    defconfig = kernel_root / "common" / "arch" / "arm64" / "configs" / "gki_defconfig"
    txt = defconfig.read_text()
    if "CONFIG_BBG=y" not in txt:
        txt += "CONFIG_BBG=y\n"
    defconfig.write_text(txt)
    kconfig = common / "security" / "Kconfig"
    if kconfig.exists() and "baseband_guard" not in kconfig.read_text():
        # zzh 同款: selinux 后插 baseband_guard (保持 LSM 初始化顺序, 不破坏现有列表)
        r = run("sed -i '/^config LSM$/,/^help$/{ /^[[:space:]]*default/ { /baseband_guard/! s/selinux/selinux,baseband_guard/ } }' security/Kconfig",
                cwd=common, check=False)
        if r.returncode != 0:
            raise PatchError(f"LSM Kconfig 修改失败:\n{r.stderr[-500:]}")
    return "✓"


def apply_ipset(kernel_root):
    """ipset 网络支持 (defconfig 注入)"""
    defconfig = kernel_root / "common" / "arch" / "arm64" / "configs" / "gki_defconfig"
    lines = ["CONFIG_IP_SET=y", "CONFIG_IP_SET_BITMAP_IP=y", "CONFIG_IP_SET_BITMAP_IPMAC=y",
             "CONFIG_IP_SET_BITMAP_PORT=y", "CONFIG_IP_SET_HASH_IP=y", "CONFIG_IP_SET_HASH_IPMARK=y",
             "CONFIG_IP_SET_HASH_IPPORT=y", "CONFIG_IP_SET_HASH_IPPORTIP=y", "CONFIG_IP_SET_HASH_IPPORTNET=y",
             "CONFIG_IP_SET_HASH_MAC=y", "CONFIG_IP_SET_HASH_NET=y", "CONFIG_IP_SET_HASH_NETIFACE=y",
             "CONFIG_IP_SET_HASH_NETNET=y", "CONFIG_IP_SET_HASH_NETPORT=y", "CONFIG_IP_SET_HASH_NETPORTNET=y",
             "CONFIG_IP_SET_LIST_SET=y", "CONFIG_NETFILTER_XT_SET=y"]
    txt = defconfig.read_text()
    for c in lines:
        if c not in txt:
            txt += c + "\n"
    defconfig.write_text(txt)
    return f"✓ ({len(lines)} 项)"


def apply_nomount(common):
    """NoMount VFS 文件重定向框架 (内核内建)"""
    # 1. 应用 hook 补丁 (namei/d_path/readdir/stat/statfs/task_mmu/Kconfig/Makefile)
    msg = apply_patch("09-android/nomount-6.6.patch", common)
    # 2. 拷贝 nomount.c/h 源码 (补丁不含源码文件)
    src_c = ROOT / "third_party" / "nomount" / "nomount.c"
    src_h = ROOT / "third_party" / "nomount" / "nomount.h"
    if not src_c.exists():
        raise PatchError(f"nomount.c 缺失: {src_c}")
    dst_c = common / "fs" / "nomount.c"
    dst_h = common / "fs" / "nomount.h"          # nomount.c 用 #include "nomount.h" (相对路径)
    dst_h2 = common / "include" / "linux" / "nomount.h"
    if not dst_c.exists():
        shutil.copy2(src_c, dst_c)
    if not dst_h.exists():
        shutil.copy2(src_h, dst_h)
    if not dst_h2.exists():
        shutil.copy2(src_h, dst_h2)
    return f"{msg} + 源码已拷贝"



def apply_all(cfg, kernel_root, sublevel="77", kernel_base="6.6.77"):
    """按 config.yaml features 应用补丁"""
    common = kernel_root / "common"
    features = cfg.get("features", {})
    results = []

    # 6.6.118 (2026-01) 已内置的功能, 对应补丁自动跳过
    BUILTIN_118 = {"zstd"}   # zstd 1.5.7 + compression_level 参数已在内核

    for feat, on in features.items():
        if not on:
            continue
        if kernel_base == "6.6.118" and feat in BUILTIN_118:
            results.append((feat, "6.6.118 已内置, 跳过"))
            continue
        try:
            if feat == "zram_lz4kd":
                msg = apply_zram_lz4kd(common)
            elif feat == "fusebpf":
                msg = apply_fusebpf(common)
            elif feat == "unicode_bypass":
                msg = apply_unicode_bypass(common)
            elif feat == "uksm":
                msg = apply_uksm(common)
            elif feat == "adios":
                msg = apply_adios(common)
            elif feat == "lts_fixes":
                msg = apply_lts_fixes(common)
            elif feat == "cve_fix":
                msg = apply_cve_fix(common, sublevel)
            elif feat == "bbg":
                msg = apply_bbg(common, kernel_root)
            elif feat == "ipset":
                msg = apply_ipset(kernel_root)
            elif feat == "nomount":
                msg = apply_nomount(common)
            elif feat in FEATURE_PATCHES:
                msg = apply_patch(FEATURE_PATCHES[feat], common)
            else:
                msg = "未知 feature, 跳过"
            results.append((feat, msg))
        except PatchError as e:
            print(f"  ✗ [{feat}] {e}")
            raise
    return results
