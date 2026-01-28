try:
    import requests
    response = requests.get("http://localhost:8888/api/health", timeout=3)
    print(f"✓ API 响应成功!")
    print(f"状态码: {response.status_code}")
    print(f"内容: {response.json()}")
except requests.exceptions.Timeout:
    print("✗ 请求超时")
except requests.exceptions.ConnectionError:
    print("✗ 无法连接到服务器")
except Exception as e:
    print(f"✗ 错误: {e}")
