"""
文件工具函数测试
"""

import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.utils.file_utils import (
    should_exclude,
    should_include_extension,
    get_relative_path
)


class TestFileUtils(unittest.TestCase):
    """文件工具函数测试"""
    
    def test_should_exclude_by_filename(self):
        """测试按文件名排除"""
        patterns = ['*.pyc', '*.log', 'test_*.py']
        
        self.assertTrue(should_exclude('test.pyc', patterns))
        self.assertTrue(should_exclude('app.log', patterns))
        self.assertTrue(should_exclude('test_main.py', patterns))
        self.assertFalse(should_exclude('main.py', patterns))
    
    def test_should_exclude_by_directory(self):
        """测试按目录排除"""
        patterns = ['__pycache__', '.git', 'node_modules']
        
        self.assertTrue(should_exclude('src/__pycache__/test.py', patterns))
        self.assertTrue(should_exclude('.git/config', patterns))
        self.assertTrue(should_exclude('project/node_modules/package.json', patterns))
        self.assertFalse(should_exclude('src/main.py', patterns))
    
    def test_should_exclude_complex_patterns(self):
        """测试复杂排除规则"""
        patterns = ['*.pyc', '__pycache__', '.git', '*.tmp', 'build/*']
        
        test_cases = {
            'test.pyc': True,
            'src/__pycache__/test.py': True,
            '.git/HEAD': True,
            'temp.tmp': True,
            'main.py': False,
            'src/utils.py': False,
        }
        
        for path, expected in test_cases.items():
            self.assertEqual(should_exclude(path, patterns), expected, f"路径 {path} 判断错误")
    
    def test_should_include_extension_empty_list(self):
        """测试空扩展名列表（允许所有）"""
        self.assertTrue(should_include_extension('test.py', []))
        self.assertTrue(should_include_extension('test.js', []))
        self.assertTrue(should_include_extension('test.txt', []))
    
    def test_should_include_extension_with_list(self):
        """测试指定扩展名列表"""
        allowed = ['.py', '.js', '.md']
        
        self.assertTrue(should_include_extension('test.py', allowed))
        self.assertTrue(should_include_extension('app.js', allowed))
        self.assertTrue(should_include_extension('README.md', allowed))
        self.assertFalse(should_include_extension('test.txt', allowed))
        self.assertFalse(should_include_extension('image.jpg', allowed))
    
    def test_should_include_extension_case_insensitive(self):
        """测试扩展名大小写不敏感"""
        allowed = ['.py', '.js']
        
        self.assertTrue(should_include_extension('Test.PY', allowed))
        self.assertTrue(should_include_extension('App.JS', allowed))
    
    def test_get_relative_path(self):
        """测试获取相对路径"""
        if sys.platform == 'win32':
            base = Path('D:/projects/my-app')
            file = Path('D:/projects/my-app/src/main.py')
            expected = Path('src/main.py')
        else:
            base = Path('/home/user/my-app')
            file = Path('/home/user/my-app/src/main.py')
            expected = Path('src/main.py')
        
        result = get_relative_path(file, base)
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
