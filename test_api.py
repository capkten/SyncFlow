import http.client
import json

def test_api():
    try:
        conn = http.client.HTTPConnection("localhost", 8888, timeout=5)
        conn.request("GET", "/api/health")
        response = conn.getresponse()
        
        print(f"状态码: {response.status}")
        print(f"状态信息: {response.reason}")
        
        data = response.read()
        print(f"响应内容: {data.decode('utf-8')}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"请求失败: {e}")
        return False

if __name__ == "__main__":
    print("测试 API 健康检查...")
    test_api()
