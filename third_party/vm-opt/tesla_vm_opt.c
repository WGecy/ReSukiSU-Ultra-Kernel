// SPDX-License-Identifier: GPL-2.0
/*
 * tesla_vm_opt - 按内存大小自动调优 vm 参数 (内核态)
 *
 * 逻辑 (对齐官方脚本 set_system_opt):
 *   内存 > 12GB:
 *     - extfrag_threshold = 800    (碎片回收阈值, 官方 500 → 800 更积极)
 *     - compact_unevictable_allowed = 0  (禁止回收 unevictable 页)
 *     - page_cluster = 0           (禁用 swap 预读)
 *  通用:
 *     - oom_dump_tasks = 0         (禁用 OOM dump Task Info)
 *
 * 2026-08-16: 内核态实现 (替代用户态脚本, 开机即生效)
 */
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>

extern int sysctl_extfrag_threshold;
extern int sysctl_compact_unevictable_allowed;
extern int sysctl_oom_dump_tasks;

static int __init tesla_vm_opt_init(void)
{
	unsigned long mem_mb = totalram_pages() * (PAGE_SIZE / 1024) / 1024;

	/* oom_dump_tasks: 始终禁用 (省 logcat 空间 + 隐私) */
	sysctl_oom_dump_tasks = 0;

	/* >12GB: 激进内存优化 */
	if (mem_mb > 12288) {
		sysctl_extfrag_threshold = 800;
		sysctl_compact_unevictable_allowed = 0;
		/* page_cluster 在 mm/swap.c, 通过 sysctl 设置 */
		pr_info("tesla_vm_opt: %lu MB RAM, 高配优化 (extfrag=800, compact_unevictable=0)\n",
			mem_mb);
	} else {
		pr_info("tesla_vm_opt: %lu MB RAM, 默认参数\n", mem_mb);
	}
	return 0;
}
late_initcall(tesla_vm_opt_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Tesla VM auto-tune by RAM size");
