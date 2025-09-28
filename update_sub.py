import requests
import base64
import subprocess
import time
import re
from urllib.parse import urlparse, parse_qs
import socket
import json

# 代理源
SUB_SOURCES = [
    # 添加更可靠的源
    "https://raw.githubusercontent.com/some-reliable-source/v2ray/main/sub.txt",
    # 通过动态搜索获取
]

def fetch_proxies():
    all_proxies = set()
    for url in SUB_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text.strip()
                if 'base64' in url.lower():
                    decoded = base64.b64decode(content).decode('utf-8')
                    links = re.findall(r'(vmess://[^\n]+|vless://[^\n]+|ss://[^\n]+)', decoded)
                else:
                    links = [line.strip() for line in content.split('\n') if line.strip().startswith(('vmess://', 'vless://', 'ss://'))]
                all_proxies.update(links)
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    return list(all_proxies)[:100]

def is_host_valid(host):
    try:
        socket.gethostbyname(host)
        return True
    except:
        return False

def parse_proxy(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return {
            'protocol': parsed.scheme,
            'uuid': parsed.username,
            'host': parsed.hostname,
            'port': parsed.port,
            'params': params
        }
    except:
        return None

def convert_to_v2ray_config(proxy_url):
    # 简化的转换逻辑，实际需根据协议类型生成 JSON 配置
    parsed = parse_proxy(proxy_url)
    if not parsed:
        return None
    # 示例 v2ray JSON 配置
    config = {
        "inbounds": [{"port": 1080, "protocol": "socks", "settings": {"auth": "noauth"}}],
        "outbounds": [{
            "protocol": parsed['protocol'],
            "settings": {
                "vnext": [{
                    "address": parsed['host'],
                    "port": parsed['port'],
                    "users": [{"id": parsed['uuid']}]
                }]
            }
        }]
    }
    return config

def test_speed(proxy_url):
    parsed = parse_proxy(proxy_url)
    if not parsed or not is_host_valid(parsed['host']):
        print(f"Invalid host for {proxy_url}")
        return float('inf')
    
    config = convert_to_v2ray_config(proxy_url)
    if not config:
        print(f"Failed to parse {proxy_url}")
        return float('inf')
    
    try:
        with open('temp_config.json', 'w') as f:
            json.dump(config, f)
        subprocess.run(['v2ray', 'run', '-c', 'temp_config.json'], timeout=5, stdout=subprocess.DEVNULL)
        result = subprocess.run(
            ['curl', '-o', '/dev/null', '-s', '--max-time', '10', '-w', '%{time_total}', 
             'http://www.gstatic.com/generate_204', '--proxy', 'socks5://127.0.0.1:1080'],
            capture_output=True, text=True, timeout=15
        )
        latency = float(result.stdout) * 1000
        print(f"Tested {proxy_url}: {latency}ms")
        return latency
    except Exception as e:
        print(f"Test failed for {proxy_url}: {e}")
        return float('inf')

def generate_sub(proxies, top_n=10, max_latency=1000):
    results = []
    for proxy in proxies:
        latency = test_speed(proxy)
        if latency < max_latency:
            results.append((proxy, latency))
        time.sleep(1)
    
    top_proxies = sorted(results, key=lambda x: x[1])[:top_n]
    
    with open('sub.txt', 'w') as f:
        for proxy, _ in top_proxies:
            f.write(proxy + '\n')
    
    all_links = '\n'.join([p[0] for p in top_proxies])
    b64_sub = base64.b64encode(all_links.encode()).decode()
    with open('sub_base64.txt', 'w') as f:
        f.write(b64_sub)
    
    print(f"Generated sub.txt with {len(top_proxies)} proxies")

if __name__ == "__main__":
    proxies = fetch_proxies()
    generate_sub(proxies)
