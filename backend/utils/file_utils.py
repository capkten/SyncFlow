"""
文件工具函数
"""

import os
import fnmatch
from pathlib import Path
from typing import List


def should_exclude(file_path: str | Path, exclude_patterns: List[str]) -> bool:
    """
    检查文件是否应该被排除
    
    Args:
        file_path: 文件路径
        exclude_patterns: 排除规则列表（支持通配符）
        
    Returns:
        True 表示应该排除，False 表示应该同步
        
    Examples:
        >>> should_exclude("test.pyc", ["*.pyc"])
        True
        >>> should_exclude("src/__pycache__/test.py", ["__pycache__"])
        True
        >>> should_exclude("src/main.py", ["*.pyc"])
        False
    """
    file_path = Path(file_path)
    path_str = str(file_path)
    
    for pattern in exclude_patterns:
        # 检查文件名匹配
        if fnmatch.fnmatch(file_path.name, pattern):
            return True
        
        # 检查路径中是否包含该模式（用于排除目录）
        if pattern in path_str.split(os.sep):
            return True
        
        # 支持路径通配符
        if fnmatch.fnmatch(path_str, pattern):
            return True
    
    return False


def should_include_extension(file_path: str | Path, allowed_extensions: List[str]) -> bool:
    """
    检查文件扩展名是否在允许列表中
    
    Args:
        file_path: 文件路径
        allowed_extensions: 允许的扩展名列表（如 ['.py', '.js']）
                           如果为空列表，则允许所有扩展名
        
    Returns:
        True 表示应该同步，False 表示应该排除
    """
    if not allowed_extensions:
        return True
    
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    
    return ext in allowed_extensions


def get_relative_path(file_path: str | Path, base_path: str | Path) -> Path:
    """
    获取相对于基础路径的相对路径
    
    Args:
        file_path: 文件路径
        base_path: 基础路径
        
    Returns:
        相对路径
    """
    file_path = Path(file_path).resolve()
    base_path = Path(base_path).resolve()
    
    return file_path.relative_to(base_path)


def ensure_parent_dir(file_path: str | Path):
    """
    确保文件的父目录存在
    
    Args:
        file_path: 文件路径
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)


if __name__ == '__main__':
    # 测试代码
    test_patterns = ["*.pyc", "__pycache__", ".git", "node_modules"]
    
    print(should_exclude("test.pyc", test_patterns))  # True
    print(should_exclude("main.py", test_patterns))   # False
    print(should_exclude("src/__pycache__/test.py", test_patterns))  # True
    print(should_exclude(".git/config", test_patterns))  # True
    
    print(should_include_extension("test.py", [".py", ".js"]))  # True
    print(should_include_extension("test.txt", [".py", ".js"]))  # False
    print(should_include_extension("test.txt", []))  # True（空列表允许所有）
