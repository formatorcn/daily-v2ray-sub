import requests
import base64
import subprocess
import time
import re
from urllib.parse import urlparse, parse_qs
import socket
import json
import random

# 优化的代理源，添加针对中国环境的源
SUB_SOURCES = [
    # 高质量 VLESS 源（支持 Reality 或伪装域名）
    "https://raw.githubusercontent.com/Mahdi0024/ProxyCollector/main/proxies/vless.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/vless_configs.txt",
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub.txt",
    # 新增源：专注于 Reality 协议或伪装流量
    "https://raw.githubusercontent.com/hiddify/hiddify-configs/main/subscriptions/vless_reality.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    # 保留部分原源，但优先级降低
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt",
]

# 伪装域名白名单（绕过 GFW 探测）
TRUSTED_SNI = [
    'www.cloudflare.com', 'www.microsoft.com', 'www.apple.com',
    'www.amazon.com', 'www.google.com', 'www.tencent.com'
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
                    links = re.findall(r'(vless://[^\n]+)', decoded)
                else:
                    links = [line.strip() for line in content.split('\n') if line.strip().startswith('vless://')]
                all_proxies.update(links)
                print(f"Fetched {len(links)} VLESS proxies from {url}")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    print(f"Total unique VLESS proxies: {len(all_proxies)}")
    return list(all_proxies)[:100]  # 限制测试数量以提高效率

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
            'port': parsed.port or 443,
            'params': params,
            'path': params.get('path', [''])[0],
            'sni': params.get('sni', [''])[0],
            'security': params.get('security', ['none'])[0],
            'type': params.get('type', ['tcp'])[0],
            'encryption': params.get('encryption', ['none'])[0],
            'fp': params.get('fp', [''])[0],
            'pbk': params.get('pbk', [''])[0],
            'sid': params.get('sid', [''])[0]
        }
    except Exception as e:
        print(f"Parse error for {url}: {e}")
        return None

def convert_to_v2ray_config(proxy_url):
    parsed = parse_proxy(proxy_url)
    if not parsed:
        return None
    if parsed['protocol'] != 'vless':
        return None  # 只处理 VLESS
    config = {
        "inbounds": [{"port": 1080, "protocol": "socks", "settings": {"auth": "noauth"}}],
        "outbounds": [{
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": parsed['host'],
                    "port": parsed['port'],
                    "users": [{"id": parsed['uuid'], "encryption": parsed['encryption']}]
                }]
            },
            "streamSettings": {
                "network": parsed['type'],
                "security": parsed['security'],
            }
        }]
    }
    if parsed['type'] == 'ws':
        config["outbounds"][0]["streamSettings"]["wsSettings"] = {
            "path": parsed['path'],
            "headers": {"Host": parsed.get('host', parsed['sni'])}
        }
        if parsed['security'] == 'tls':
            config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
                "serverName": parsed['sni'],
                "fingerprint": parsed['fp'] or 'chrome'
            }
    elif parsed['type'] == 'grpc':
        config["outbounds"][0]["streamSettings"]["grpcSettings"] = {
            "serviceName": parsed['params'].get('serviceName', [''])[0]
        }
        if parsed['security'] == 'tls':
            config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
                "serverName": parsed['sni'],
                "fingerprint": parsed['fp'] or 'chrome'
            }
    elif parsed['type'] == 'tcp' and parsed['security'] == 'reality':
        config["outbounds"][0]["streamSettings"]["realitySettings"] = {
            "publicKey": parsed['pbk'],
            "shortId": parsed['sid'],
            "serverName": parsed['sni'],
            "fingerprint": parsed['fp'] or 'chrome'
        }
    return config

def test_speed(proxy_url):
    parsed = parse_proxy(proxy_url)
    if not parsed or not is_host_valid(parsed['host']):
        print(f"Invalid host for {proxy_url}")
        return float('inf')
    
    # 过滤不适合中国环境的配置
    if parsed['security'] not in ['tls', 'reality'] or (parsed['sni'] and parsed['sni'] not in TRUSTED_SNI):
        print(f"Filtered out {proxy_url} due to unsupported security or SNI")
        return float('inf')

    config = convert_to_v2ray_config(proxy_url)
    if not config:
        print(f"Failed to generate config for {proxy_url}")
        return float('inf')
    
    try:
        with open('temp.json', 'w', encoding='utf-8') as f:
            json.dump(config, f)
        proc = subprocess.Popen(['/usr/local/bin/xray', 'run', '-c', 'temp.json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(3)
        
        # 使用国内可访问的测试目标
        test_urls = [
            'http://www.baidu.com',
            'http://www.qq.com',
            'http://www.taobao.com'
        ]
        test_url = random.choice(test_urls)
        result = subprocess.run(
            ['curl', '-o', '/dev/null', '-s', '--max-time', '15', '-w', '%{time_total}',
             test_url, '--socks5', '127.0.0.1:1080'],
            capture_output=True, text=True, timeout=20
        )
        
        proc.terminate()
        if result.returncode == 0:
            latency = float(result.stdout) * 1000
            print(f"Success: {proxy_url} - {latency}ms (tested on {test_url})")
            return latency
        else:
            print(f"Curl failed for {proxy_url}: {result.stderr}")
            return float('inf')
    except Exception as e:
        print(f"Test failed for {proxy_url}: {e}")
        return float('inf')

def generate_sub(proxies, top_n=10, max_latency=5000):
    results = []
    for proxy in proxies:
        latency = test_speed(proxy)
        if latency < max_latency:
            print(f"Adding to results: {proxy} - {latency}ms")
            results.append((proxy, latency))
        time.sleep(1)
    
    print(f"Total valid proxies: {len(results)}")
    top_proxies = sorted(results, key=lambda x: x[1])[:top_n]
    print(f"Top {top_n} proxies: {top_proxies}")
    
    with open('sub.txt', 'w', encoding='utf-8') as f:
        for proxy, latency in top_proxies:
            f.write(f"{proxy} # Latency: {latency}ms\n")
    
    with open('sub.txt', 'r', encoding='utf-8') as f:
        content = f.read()
        print(f"sub.txt content: {content}")
    
    all_links = '\n'.join([p[0] for p in top_proxies])
    b64_sub = base64.b64encode(all_links.encode('utf-8')).decode('utf-8')
    with open('sub_base64.txt', 'w', encoding='utf-8') as f:
        f.write(b64_sub)
    
    print(f"Generated sub.txt with {len(top_proxies)} proxies")

if __name__ == "__main__":
    proxies = fetch_proxies()
    generate_sub(proxies)
