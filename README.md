# ReSukiSU-Ultra-Kernel

ReSukiSU-Ultra 内核一键构建仓库 (仿 GKI_KernelSU_SUSFS)

## 支持版本
- **6.6.77** (OS3 时代基线, 2025-03)
- **6.6.118** (OS4 主基线, android15-8 冻结 KMI, 2026-01)
- 不跟随 LTS (无 lts_merge / lts backport)

## 功能
- **KSU**: ReSukiSU-Ultra 分支 (netisolate 联网隔离 / FUSEBPF 修复 / 隐藏 BL 锁 / 自定义签名)
- **SUSFS**: 全功能
- **内存**: MGLRU FORCE3 / mTHP
- **IO**: ADIOS (默认) / UFS FastDiscard / zstd 1.5.7 / zram lz4kd
- **网络**: BBRv3 / ipset
- **性能**: cpuidle / 温控偏移 / perf_tune / vm_defaults
- **安全**: CVE-2026-43499 / NoMount / unicode_bypass
- 管理器: ReSukiSU-Ultra (CI 自动构建, 随内核发布)

## 使用
1. 打开 Actions → "内核构建 - Android 15 (6.6)"
2. 选择版本 (6.6.77 / 6.6.118 / 全部) + 功能开关
3. 运行 → 下载产物 (AnyKernel3 zip + 管理器 APK)

## 本地构建
```bash
python3 build.py        # 全流程
python3 build.py --step 9   # 从步骤 9 续跑
```
