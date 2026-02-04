#!/usr/bin/env python3
"""
数据迁移脚本: 将期权数据中的 'right' 列重命名为 'option_type'

Usage:
    python scripts/migrate_option_type.py /Volumes/ORICO/option_quant
"""

import sys
from pathlib import Path

import pyarrow.parquet as pq


def migrate_parquet_file(file_path: Path) -> bool:
    """迁移单个 Parquet 文件

    Args:
        file_path: Parquet 文件路径

    Returns:
        是否进行了迁移
    """
    try:
        table = pq.read_table(file_path)
        columns = table.column_names

        if "right" not in columns:
            if "option_type" in columns:
                print(f"  ✓ Already migrated: {file_path.name}")
                return False
            print(f"  - No 'right' column: {file_path.name}")
            return False

        # 重命名列
        new_names = ["option_type" if c == "right" else c for c in columns]
        new_table = table.rename_columns(new_names)

        # 备份原文件
        backup_path = file_path.with_suffix(".parquet.bak")
        file_path.rename(backup_path)

        # 写入新文件
        pq.write_table(new_table, file_path)

        # 删除备份
        backup_path.unlink()

        print(f"  ✓ Migrated: {file_path.name}")
        return True

    except Exception as e:
        print(f"  ✗ Error migrating {file_path.name}: {e}")
        return False


def migrate_data_dir(data_dir: Path) -> dict:
    """迁移数据目录中的所有期权数据

    Args:
        data_dir: 数据目录

    Returns:
        迁移统计
    """
    stats = {"migrated": 0, "skipped": 0, "errors": 0}

    option_dir = data_dir / "option_daily"
    if not option_dir.exists():
        print(f"Option directory not found: {option_dir}")
        return stats

    print(f"\n{'='*60}")
    print("Migrating option data: 'right' -> 'option_type'")
    print(f"{'='*60}")

    for symbol_dir in sorted(option_dir.iterdir()):
        if not symbol_dir.is_dir():
            continue

        print(f"\n{symbol_dir.name}:")

        for parquet_file in sorted(symbol_dir.glob("*.parquet")):
            try:
                if migrate_parquet_file(parquet_file):
                    stats["migrated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                print(f"  ✗ Error: {e}")
                stats["errors"] += 1

    print(f"\n{'='*60}")
    print(f"Migration complete:")
    print(f"  Migrated: {stats['migrated']}")
    print(f"  Skipped:  {stats['skipped']}")
    print(f"  Errors:   {stats['errors']}")
    print(f"{'='*60}")

    return stats


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_option_type.py <data_dir>")
        print("Example: python scripts/migrate_option_type.py /Volumes/ORICO/option_quant")
        sys.exit(1)

    data_dir = Path(sys.argv[1])
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        sys.exit(1)

    migrate_data_dir(data_dir)


if __name__ == "__main__":
    main()
