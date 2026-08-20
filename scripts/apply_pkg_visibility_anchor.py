#!/usr/bin/env python3
"""pkg-visibility 锚点插入脚本 (兼容 +archive 源码, 不依赖行号)
用法: python3 apply_pkg_visibility_anchor.py <kernel_common_dir>
"""
import sys
from pathlib import Path


def insert_after(file: Path, anchor: str, block: str) -> bool:
    txt = file.read_text()
    if block.strip() in txt:
        print(f"{file}: 已存在, 跳过")
        return True
    if anchor not in txt:
        print(f"{file}: 锚点未找到: {anchor[:60]!r}")
        return False
    file.write_text(txt.replace(anchor, anchor + block, 1))
    print(f"{file}: 插入成功")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: apply_pkg_visibility_anchor.py <common_dir>")
        return 1
    common = Path(sys.argv[1])
    ok = True

    # ---- fs/fuse/fuse_i.h: filter_pkg_dirs 标志 ----
    ok &= insert_after(
        common / "fs/fuse/fuse_i.h",
        "\t\t/* Version of cache we are reading */\n\t\tu64 version;\n",
        "\n\t\t/* ReSukiSU-Ultra: filter other apps' package dirs on Android/data|obb */\n"
        "\t\tbool filter_pkg_dirs;\n",
    )

    # ---- fs/fuse/readdir.c ----
    rd = common / "fs/fuse/readdir.c"
    txt = rd.read_text()
    if "pkg_vis_current_allowed" not in txt:
        helper = """/* ReSukiSU-Ultra: package dir visibility filtering on Android/data|obb */
#include <linux/sched.h>
#include <linux/uidgid.h>
#include <linux/dcache.h>

extern bool __ksu_is_allow_uid(uid_t uid);
extern bool ksu_is_manager_uid(u32 uid);

#define PKG_VIS_SYSTEM_UID_MAX 10000

static bool pkg_vis_current_allowed(void)
{
	uid_t uid = current_uid().val;

	if (uid == 0)
		return true;
	if (ksu_is_manager_uid(uid))
		return true;
	if (__ksu_is_allow_uid(uid))
		return true;
	if (uid < PKG_VIS_SYSTEM_UID_MAX)
		return true;
	return false;
}

static bool pkg_vis_dir_is_android_data(struct dentry *dentry)
{
	struct dentry *parent;
	struct qstr *name;

	if (!dentry || !dentry->d_parent)
		return false;
	name = &dentry->d_name;
	if (name->len != 4 || strncmp(name->name, "data", 4) != 0)
		return false;
	parent = dentry->d_parent;
	if (!parent || !parent->d_name.name)
		return false;
	if (parent->d_name.len != 7 || strncmp(parent->d_name.name, "Android", 7) != 0)
		return false;
	return true;
}

static bool pkg_vis_dir_is_android_obb(struct dentry *dentry)
{
	struct dentry *parent;
	struct qstr *name;

	if (!dentry || !dentry->d_parent)
		return false;
	name = &dentry->d_name;
	if (name->len != 3 || strncmp(name->name, "obb", 3) != 0)
		return false;
	parent = dentry->d_parent;
	if (!parent || !parent->d_name.name)
		return false;
	if (parent->d_name.len != 7 || strncmp(parent->d_name.name, "Android", 7) != 0)
		return false;
	return true;
}

static bool pkg_vis_should_filter(struct file *file)
{
	struct dentry *dentry = file->f_path.dentry;

	return pkg_vis_dir_is_android_data(dentry) ||
	       pkg_vis_dir_is_android_obb(dentry);
}

static bool pkg_vis_hide_dirent(struct file *file, struct fuse_dirent *dirent)
{
	struct super_block *sb;
	struct inode *inode;
	uid_t owner;
	bool hide;

	if (pkg_vis_current_allowed())
		return false;

	sb = file_inode(file)->i_sb;
	inode = ilookup(sb, dirent->ino);
	if (!inode)
		return false;

	owner = from_kuid(&init_user_ns, inode->i_uid);
	hide = (owner != current_uid().val);
	iput(inode);
	return hide;
}

"""
        anchor = '#include "fuse_i.h"\n'
        if anchor not in txt:
            print("readdir.c: include 锚点未找到")
            ok = False
        else:
            txt = txt.replace(anchor, anchor + helper, 1)
            print("readdir.c: helper 插入成功")

    old_emit = """	if (ff->open_flags & FOPEN_CACHE_DIR)
		fuse_add_dirent_to_cache(file, dirent, ctx->pos);

	return dir_emit(ctx, dirent->name, dirent->namelen, dirent->ino,
			dirent->type);"""
    new_emit = """	if (ff->open_flags & FOPEN_CACHE_DIR)
		fuse_add_dirent_to_cache(file, dirent, ctx->pos);

	if (ff->readdir.filter_pkg_dirs && pkg_vis_hide_dirent(file, dirent))
		return true;

	return dir_emit(ctx, dirent->name, dirent->namelen, dirent->ino,
			dirent->type);"""
    if "filter_pkg_dirs && pkg_vis_hide_dirent" not in txt:
        if old_emit not in txt:
            print("readdir.c: fuse_emit 锚点未找到")
            ok = False
        else:
            txt = txt.replace(old_emit, new_emit, 1)
            print("readdir.c: fuse_emit 过滤插入成功")

    old_rd = """	if (fuse_is_bad(inode))
		return -EIO;

	mutex_lock(&ff->readdir.lock);"""
    new_rd = """	if (fuse_is_bad(inode))
		return -EIO;

	ff->readdir.filter_pkg_dirs = pkg_vis_should_filter(file);

	mutex_lock(&ff->readdir.lock);"""
    if "filter_pkg_dirs = pkg_vis_should_filter" not in txt:
        if old_rd not in txt:
            print("readdir.c: fuse_readdir 锚点未找到")
            ok = False
        else:
            txt = txt.replace(old_rd, new_rd, 1)
            print("readdir.c: fuse_readdir 标志设置成功")
    rd.write_text(txt)

    # ---- fs/fuse/dir.c ----
    dc = common / "fs/fuse/dir.c"
    txt = dc.read_text()
    if "pkg_vis_hide_target" not in txt:
        helper = """/* ReSukiSU-Ultra: package dir visibility filtering on Android/data|obb */
#include <linux/sched.h>
#include <linux/uidgid.h>
#include <linux/dcache.h>

extern bool __ksu_is_allow_uid(uid_t uid);
extern bool ksu_is_manager_uid(u32 uid);

#define PKG_VIS_SYSTEM_UID_MAX 10000

static bool pkg_vis_current_allowed(void)
{
	uid_t uid = current_uid().val;

	if (uid == 0)
		return true;
	if (ksu_is_manager_uid(uid))
		return true;
	if (__ksu_is_allow_uid(uid))
		return true;
	if (uid < PKG_VIS_SYSTEM_UID_MAX)
		return true;
	return false;
}

static bool pkg_vis_dentry_on_android_data(struct dentry *dentry)
{
	struct dentry *parent;

	if (!dentry || !dentry->d_parent)
		return false;
	if (dentry->d_name.len != 4 ||
	    strncmp(dentry->d_name.name, "data", 4) != 0)
		return false;
	parent = dentry->d_parent;
	if (!parent || !parent->d_name.name)
		return false;
	if (parent->d_name.len != 7 ||
	    strncmp(parent->d_name.name, "Android", 7) != 0)
		return false;
	return true;
}

static bool pkg_vis_dentry_on_android_obb(struct dentry *dentry)
{
	struct dentry *parent;

	if (!dentry || !dentry->d_parent)
		return false;
	if (dentry->d_name.len != 3 ||
	    strncmp(dentry->d_name.name, "obb", 3) != 0)
		return false;
	parent = dentry->d_parent;
	if (!parent || !parent->d_name.name)
		return false;
	if (parent->d_name.len != 7 ||
	    strncmp(parent->d_name.name, "Android", 7) != 0)
		return false;
	return true;
}

static bool pkg_vis_hide_target(struct dentry *entry, struct inode *inode)
{
	struct dentry *parent;

	if (pkg_vis_current_allowed())
		return false;
	if (!inode)
		return false;
	if (!entry || !entry->d_parent)
		return false;
	parent = entry->d_parent;
	if (!pkg_vis_dentry_on_android_data(parent) &&
	    !pkg_vis_dentry_on_android_obb(parent))
		return false;
	return from_kuid(&init_user_ns, inode->i_uid) != current_uid().val;
}

"""
        anchor = "#include <linux/kernel.h>\n"
        if anchor not in txt:
            print("dir.c: include 锚点未找到")
            ok = False
        else:
            txt = txt.replace(anchor, anchor + helper, 1)
            print("dir.c: helper 插入成功")

    old_lk = """	err = -EIO;
	if (inode && get_node_id(inode) == FUSE_ROOT_ID)
		goto out_iput;

	newent = d_splice_alias(inode, entry);"""
    new_lk = """	err = -EIO;
	if (inode && get_node_id(inode) == FUSE_ROOT_ID)
		goto out_iput;

	if (inode && pkg_vis_hide_target(entry, inode)) {
		err = -ENOENT;
		goto out_iput;
	}

	newent = d_splice_alias(inode, entry);"""
    if "pkg_vis_hide_target(entry, inode)" not in txt:
        if old_lk not in txt:
            print("dir.c: fuse_lookup 锚点未找到")
            ok = False
        else:
            txt = txt.replace(old_lk, new_lk, 1)
            print("dir.c: fuse_lookup 过滤插入成功")

    old_ga = """	if (fuse_is_bad(inode))
		return -EIO;

	if (!fuse_allow_current_process(fc)) {"""
    new_ga = """	if (fuse_is_bad(inode))
		return -EIO;

	if (pkg_vis_hide_target(path->dentry, inode))
		return -ENOENT;

	if (!fuse_allow_current_process(fc)) {"""
    if "pkg_vis_hide_target(path->dentry" not in txt:
        if old_ga not in txt:
            print("dir.c: fuse_getattr 锚点未找到")
            ok = False
        else:
            txt = txt.replace(old_ga, new_ga, 1)
            print("dir.c: fuse_getattr 过滤插入成功")
    dc.write_text(txt)

    # ---- fs/namei.c ----
    nc = common / "fs/namei.c"
    txt = nc.read_text()
    if "pkg_vis_hide_data_data" not in txt:
        helper = """/* ReSukiSU-Ultra: hide /data/data/<pkg> existence from other apps */
#include <linux/sched.h>
#include <linux/uidgid.h>

extern bool __ksu_is_allow_uid(uid_t uid);
extern bool ksu_is_manager_uid(u32 uid);

#define PKG_VIS_SYSTEM_UID_MAX 10000

static bool pkg_vis_current_allowed(void)
{
	uid_t uid = current_uid().val;

	if (uid == 0)
		return true;
	if (ksu_is_manager_uid(uid))
		return true;
	if (__ksu_is_allow_uid(uid))
		return true;
	if (uid < PKG_VIS_SYSTEM_UID_MAX)
		return true;
	return false;
}

/* dentry chain: <pkg> -> data -> data -> / */
static bool pkg_vis_on_data_data(struct dentry *dentry)
{
	struct dentry *d1, *d2;

	if (!dentry || !dentry->d_parent)
		return false;
	if (dentry->d_name.len < 1)
		return false;
	d1 = dentry->d_parent;
	if (!d1 || !d1->d_name.name || d1->d_name.len != 4 ||
	    strncmp(d1->d_name.name, "data", 4) != 0)
		return false;
	d2 = d1->d_parent;
	if (!d2 || !d2->d_name.name || d2->d_name.len != 4 ||
	    strncmp(d2->d_name.name, "data", 4) != 0)
		return false;
	return true;
}

static bool pkg_vis_hide_data_data(struct dentry *dentry)
{
	struct inode *inode;

	if (pkg_vis_current_allowed())
		return false;
	if (!pkg_vis_on_data_data(dentry))
		return false;
	inode = dentry->d_inode;
	if (!inode)
		return false;
	return from_kuid(&init_user_ns, inode->i_uid) != current_uid().val;
}

"""
        anchor = '#include "mount.h"\n'
        if anchor not in txt:
            print("namei.c: include 锚点未找到")
            ok = False
        else:
            txt = txt.replace(anchor, anchor + helper, 1)
            print("namei.c: helper 插入成功")

    old_ld = """		if (unlikely(error <= 0)) {
			if (!error)
				d_invalidate(dentry);
			dput(dentry);
			return ERR_PTR(error);
		}
	}
"""
    # lookup_dcache 独有的结尾: d_revalidate 错误处理 + return dentry
    new_ld = """		if (unlikely(error <= 0)) {
			if (!error)
				d_invalidate(dentry);
			dput(dentry);
			return ERR_PTR(error);
		}
	}
	if (dentry && !IS_ERR(dentry) && pkg_vis_hide_data_data(dentry)) {
		if (d_in_lookup(dentry))
			d_lookup_done(dentry);
		dput(dentry);
		return NULL;
	}
"""
    if "pkg_vis_hide_data_data(dentry)" not in txt:
        if old_ld not in txt:
            print("namei.c: lookup_dcache 锚点未找到")
            ok = False
        else:
            txt = txt.replace(old_ld, new_ld, 1)
            print("namei.c: lookup_dcache 调用插入成功")
    nc.write_text(txt)

    print("pkg-visibility 锚点插入完成" if ok else "部分失败, 请检查")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
