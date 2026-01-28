"""
文件同步助手 - 换行符统一处理模块

功能：
1. 检测文件是否为文本文件
2. 统一换行符（CRLF ↔ LF）
3. 计算文件哈希（统一换行符后）
"""

import os
from pathlib import Path
from typing import Literal

# 常见文本文件扩展名
TEXT_EXTENSIONS = {
    # 编程语言
    '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rs', '.rb', '.php',
    '.swift', '.kt', '.scala', '.r', '.m', '.mm',
    # 配置文件
    '.json', '.yaml', '.yml', '.xml', '.toml', '.ini', '.cfg', '.conf',
    # 标记语言
    '.md', '.markdown', '.rst', '.txt', '.html', '.htm', '.css', '.scss', '.sass', '.less',
    # 脚本
    '.sh', '.bash', '.zsh', '.bat', '.cmd', '.ps1',
    # 数据
    '.sql', '.csv', '.tsv',
    # 其他
    '.gitignore', '.gitattributes', '.editorconfig', '.env'
}

# 常见二进制文件扩展名（用于避免启发式误判）
BINARY_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico',
    '.pdf',
    '.zip', '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz',
    '.exe', '.dll', '.so', '.dylib',
    '.whl', '.jar',
    '.mp3', '.wav', '.flac', '.mp4', '.mkv', '.avi', '.mov',
    '.woff', '.woff2', '.ttf', '.otf',
}

EOLType = Literal['lf', 'crlf', 'keep']


def is_text_file(file_path: str | Path) -> bool:
    """
    检测文件是否为文本文件
    
    策略：
    1. 先检查扩展名白名单
    2. 启发式检测：读取前8KB，检查是否包含null字节
    
    Args:
        file_path: 文件路径
        
    Returns:
        True 表示文本文件，False 表示二进制文件
    """
    file_path = Path(file_path)
    
    # 检查扩展名
    ext = file_path.suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return False
    if ext in TEXT_EXTENSIONS:
        return True
    
    # 特殊文件名（无扩展名）
    special_names = {'Makefile', 'Dockerfile', 'Jenkinsfile', 'README', 'LICENSE'}
    if file_path.name in special_names:
        return True
    
    # 启发式检测
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(8192)
            # 空文件视为文本文件
            if len(chunk) == 0:
                return True
            # 包含null字节的是二进制文件
            if b'\x00' in chunk:
                return False
            return True
    except Exception:
        return False


def detect_line_ending(file_path: str | Path) -> str:
    """
    检测文件当前使用的换行符类型
    
    Args:
        file_path: 文件路径
        
    Returns:
        'crlf', 'lf', 'cr', 或 'mixed'（混合）
    """
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        
        crlf_count = content.count(b'\r\n')
        lf_count = content.count(b'\n') - crlf_count
        cr_count = content.count(b'\r') - crlf_count
        
        if crlf_count > 0 and lf_count == 0 and cr_count == 0:
            return 'crlf'
        elif lf_count > 0 and crlf_count == 0 and cr_count == 0:
            return 'lf'
        elif cr_count > 0 and crlf_count == 0 and lf_count == 0:
            return 'cr'
        else:
            return 'mixed'
    except Exception:
        return 'unknown'


def normalize_line_endings(
    file_path: str | Path,
    target: EOLType = 'lf',
    in_place: bool = True
) -> bytes | None:
    """
    统一文件换行符
    
    Args:
        file_path: 文件路径
        target: 目标换行符类型 ('lf', 'crlf', 'keep')
        in_place: 是否直接修改文件（True），或仅返回转换后内容（False）
        
    Returns:
        如果 in_place=False，返回转换后的字节内容
        如果 in_place=True，返回 None（直接修改文件）
    """
    file_path = Path(file_path)
    
    # 如果是 keep 模式，不做处理
    if target == 'keep':
        if in_place:
            return None
        else:
            with open(file_path, 'rb') as f:
                return f.read()
    
    # 读取文件内容
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
    except Exception as e:
        raise IOError(f"读取文件失败: {e}")
    
    # 统一换行符
    # 1. 先将所有 CRLF 转为 LF
    normalized = content.replace(b'\r\n', b'\n')
    # 2. 将所有单独的 CR 转为 LF
    normalized = normalized.replace(b'\r', b'\n')
    
    # 3. 根据目标类型转换
    if target == 'crlf':
        normalized = normalized.replace(b'\n', b'\r\n')
    # target == 'lf' 时已经是 LF，无需额外处理
    
    # 写回文件或返回内容
    if in_place:
        try:
            with open(file_path, 'wb') as f:
                f.write(normalized)
            return None
        except Exception as e:
            raise IOError(f"写入文件失败: {e}")
    else:
        return normalized


def calculate_file_hash_normalized(
    file_path: str | Path,
    eol_mode: EOLType = 'lf',
    hash_algorithm: str = 'md5'
) -> str:
    """
    计算文件哈希值（统一换行符后）
    
    这个函数确保即使文件在不同系统间换行符不同，
    只要实际内容相同，哈希值也相同。
    
    Args:
        file_path: 文件路径
        eol_mode: 换行符统一模式（'lf', 'crlf', 'keep'）
        hash_algorithm: 哈希算法（'md5', 'sha256'）
        
    Returns:
        哈希值（十六进制字符串）
    """
    import hashlib
    
    file_path = Path(file_path)
    
    # 如果不是文本文件或 keep 模式，直接计算原始哈希
    if eol_mode == 'keep' or not is_text_file(file_path):
        hasher = hashlib.new(hash_algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    # 文本文件：统一换行符后计算哈希
    normalized_content = normalize_line_endings(file_path, target=eol_mode, in_place=False)
    hasher = hashlib.new(hash_algorithm)
    hasher.update(normalized_content)
    return hasher.hexdigest()


if __name__ == '__main__':
    # 测试代码
    import tempfile
    
    # 创建测试文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, newline='') as f:
        test_file = f.name
        f.write("line1\r\nline2\nline3\r\n")  # 混合换行符
    
    print(f"测试文件: {test_file}")
    print(f"是否为文本文件: {is_text_file(test_file)}")
    print(f"当前换行符类型: {detect_line_ending(test_file)}")
    
    # 统一为 LF
    normalize_line_endings(test_file, target='lf', in_place=True)
    print(f"统一为 LF 后: {detect_line_ending(test_file)}")
    
    # 计算哈希
    hash_lf = calculate_file_hash_normalized(test_file, eol_mode='lf')
    hash_crlf = calculate_file_hash_normalized(test_file, eol_mode='crlf')
    print(f"LF 模式哈希: {hash_lf}")
    print(f"CRLF 模式哈希: {hash_crlf}")
    
    # 清理
    os.unlink(test_file)
