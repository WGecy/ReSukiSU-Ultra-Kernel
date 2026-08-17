#!/system/bin/sh
# boot-tune: 开机调优 (adios 默认 + vm + nr_requests + MGLRU)
# 由 KSU 模块 service.d 调用 (晚于 init.rc, 覆盖系统默认)

# 1. adios 设为默认调度器 (内核已默认 + 防覆盖, 这里兜底)
for d in /sys/block/*/queue/scheduler; do
    [ -w "$d" ] && echo adios > "$d" 2>/dev/null
done

# 2. nr_requests: 128 -> 256 (高 IO 吞吐)
for d in /sys/block/*/queue/nr_requests; do
    [ -w "$d" ] && echo 256 > "$d" 2>/dev/null
done

# 3. MGLRU: 强制开启 (内核已拦截关闭, 这里兜底)
echo 0x3 > /sys/kernel/mm/lru_gen/enabled 2>/dev/null

# 4. vm 参数 (tesla_vm_opt 已内核态, 这里兜底)
echo 70 > /proc/sys/vm/watermark_scale_factor 2>/dev/null
echo 0 > /proc/sys/vm/page-cluster 2>/dev/null
echo 50 > /proc/sys/vm/vfs_cache_pressure 2>/dev/null
