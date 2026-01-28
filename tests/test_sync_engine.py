
"""
测试本地同步引擎功能
"""
import sys
import os
import shutil
import time
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.sync_engine import LocalSyncEngine

def test_local_sync():
    """测试本地同步逻辑"""
    
    # 1. 准备目录
    base_dir = Path("./tests/data")
    if base_dir.exists():
        shutil.rmtree(base_dir)
        
    source_dir = base_dir / "source"
    target_dir = base_dir / "target"
    
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    
    print(f"源目录: {source_dir}")
    print(f"目标目录: {target_dir}")
    
    # 2. 初始化引擎
    config = {
        'name': 'Test Task',
        'source_path': str(source_dir),
        'target': {
            'type': 'local',
            'path': str(target_dir)
        },
        'eol_normalize': 'lf',
        'exclude_patterns': [],
        'enabled': True
    }
    
    engine = LocalSyncEngine(config)
    
    # 3. 启动引擎 (后台会有 watchdog，但我们手动调用 sync_file 来测试核心逻辑)
    #engine.start()
    
    print("\n--- 测试 1: 创建文件 (CRLF -> LF) ---")
    file1 = source_dir / "test1.txt"
    with open(file1, 'wb') as f:
        f.write(b"Line 1\r\nLine 2\r\n")
    
    # 模拟 created 事件
    abs_path = str(file1)
    rel_path = "test1.txt"
    engine.sync_file('created', rel_path, abs_path, '')
    
    # 验证
    target_file1 = target_dir / "test1.txt"
    if target_file1.exists():
        with open(target_file1, 'rb') as f:
            content = f.read()
            if content == b"Line 1\nLine 2\n":
                print("PASS: 内容已同步且换行符已转换为 LF")
            else:
                print(f"FAIL: 内容不匹配: {content}")
    else:
        print("FAIL: 文件未同步")
        
    print("\n--- 测试 2: 修改文件 ---")
    with open(file1, 'wb') as f:
        f.write(b"Updated\r\nContent\r\n")
    
    engine.sync_file('modified', rel_path, abs_path, '')
    
    if target_file1.exists():
        with open(target_file1, 'rb') as f:
            content = f.read()
            if content == b"Updated\nContent\n":
                print("PASS: 修改已同步")
            else:
                print(f"FAIL: 内容未更新")

    print("\n--- 测试 3: 重命名文件 ---")
    file2 = source_dir / "renamed.txt"
    # 实际上操作系统会先删除旧的再创建新的，或者直接 rename。
    # 这里模拟 watchdog 可能发出的 rename 事件。
    # 注意：watchdog 的 moved 事件包含 src 和 dest
    
    # 在源目录重命名
    shutil.move(file1, file2)
    
    abs_src = str(file1)
    abs_dest = str(file2)
    
    engine.sync_file('moved', str(Path(abs_src).relative_to(source_dir)), abs_src, abs_dest)
    
    target_file2 = target_dir / "renamed.txt"
    if not target_file1.exists() and target_file2.exists():
         print("PASS: 文件重命名同步成功")
    else:
         print(f"FAIL: 重命名失败. Old exists: {target_file1.exists()}, New exists: {target_file2.exists()}")
         
    print("\n--- 测试 4: 删除文件 ---")
    if file2.exists():
        file2.unlink()
    
    engine.sync_file('deleted', str(Path(file2).relative_to(source_dir)), str(file2), '')
    
    if not target_file2.exists():
        print("PASS: 文件删除同步成功")
    else:
        print("FAIL: 文件未删除")
        
    # 清理
    shutil.rmtree(base_dir)
    print("\n测试完成")

if __name__ == "__main__":
    test_local_sync()
