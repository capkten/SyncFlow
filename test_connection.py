import socket

def test_connection():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', 8888))
        sock.close()
        
        if result == 0:
            print("✓ 端口 8888 可以连接")
            return True
        else:
            print(f"✗ 端口 8888 无法连接 (错误码: {result})")
            return False
    except Exception as e:
        print(f"✗ 连接测试失败: {e}")
        return False

if __name__ == "__main__":
    test_connection()
