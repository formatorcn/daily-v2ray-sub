import requests
import base64
import subprocess
import time
import re
from urllib.parse import urlparse, parse_qs
import socket
import json
import random

# 新代理源：从 Telegram 频道收集的 VLESS 配置（2025 年活跃源）
SUB_SOURCES = [
    # V2RayRoot: 从 Telegram 频道自动收集，每 30 分钟更新
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/main/subscriptions/vless.txt",
    
    # soroushmirzaei: Telegram 频道 + 订阅链接，包含 Reality VLESS
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscriptions/vless_telegram.txt",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/subscriptions/reality_telegram.txt",
    
    # eQnz: Telegram 公共频道收集，VLESS + Reality
    "https://raw.githubusercontent.com/eQnz/configs-collector-v2ray/main/subscriptions/vless.txt",
    
    # yaney01: Telegram 公共频道，Reality/VLESS 专用
    "https://raw.githubusercontent.com/yaney01/telegram-collector/main/subscriptions/vless_reality.txt",
    
    # bugbounted: Telegram 频道，网络/协议分离
    "https://raw.githubusercontent.com/bugbounted/telegram-configs-collector/main/subscriptions/vless.txt",
    
    # NiREvil: Telegram 频道 (Arshia and The Darkness) 配置
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub.txt",
    
    # 备用：MatinGhanbari 过滤 VLESS（非 Telegram 但高质量）
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
]

# 伪装域名白名单（绕过 GFW 探测）
TRUSTED_SNI = [
    'www.cloudflare.com', 'www.microsoft.com', 'www.apple.com',
    'www.amazon.com', 'www.google.com', 'www.tencent.com', 'www.baidu.com'
]

def fetch_proxies():
    all_proxies = set()
    for url in SUB_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text.strip()
                print(f"Fetched from {url}: {len(content)} chars")  # 调试：打印内容长度
                if 'base64' in url.lower() or content.startswith('dmVzczo'):  # 检查是否 base64
                    try:
                        decoded = base64.b64decode(content).decode('utf-8')
                        links = re.findall(r'(vless://[^\n\s]+)', decoded)
                    except:
                        links = []
                else:
                    links = [line.strip() for line in content.split('\n') if line.strip().startswith('vless://')]
                all_proxies.update(links)
                print(f"Fetched {len(links)} VLESS proxies from {url}")
            else:
                print(f"Failed to fetch {url}: status {resp.status_code}")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    print(f"Total unique VLESS proxies: {len(all_proxies)}")
    return list(all_proxies)[:150]  # 增加到 150，提高成功率

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
    if not parsed or parsed['protocol'] != 'vless':
        return None
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
    
    # 放松过滤：优先 Reality/TLS，但允许其他如果 SNI 有效
    if parsed['security'] not in ['tls', 'reality'] and not (parsed['sni'] and any(trusted in parsed['sni'] for trusted in TRUSTED_SNI)):
        print(f"Filtered out {proxy_url} due to weak security/SNI")
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
        
        # 国内测试目标，重试一次
        test_urls = ['http://www.baidu.com', 'http://www.qq.com', 'http://www.taobao.com']
        latency = float('inf')
        for _ in range(2):  # 重试 2 次
            test_url = random.choice(test_urls)
            result = subprocess.run(
                ['curl', '-o', '/dev/null', '-s', '--max-time', '15', '-w', '%{time_total}',
                 test_url, '--socks5', '127.0.0.1:1080'],
                capture_output=True, text=True, timeout=20
            )
            if result.returncode == 0:
                latency = float(result.stdout) * 1000
                break
            time.sleep(1)
        
        proc.terminate()
        if latency < float('inf'):
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
    print(f"Top {top_n} proxies: {[(p[:50] + '...' if len(p) > 50 else p, l) for p, l in top_proxies]}")  # 缩短打印
    
    with open('sub.txt', 'w', encoding='utf-8') as f:
        for proxy, latency in top_proxies:
            f.write(f"{proxy} # Latency: {latency}ms\n")
    
    with open('sub.txt', 'r', encoding='utf-8') as f:
        content = f.read()
        print(f"sub.txt content preview: {content[:200]}...")  # 预览前 200 字符
    
    all_links = '\n'.join([p[0] for p in top_proxies])
    b64_sub = base64.b64encode(all_links.encode('utf-8')).decode('utf-8')
    with open('sub_base64.txt', 'w', encoding='utf-8') as f:
        f.write(b64_sub)
    
    print(f"Generated sub.txt with {len(top_proxies)} proxies")

if __name__ == "__main__":
    proxies = fetch_proxies()
    if not proxies:
        print("No proxies fetched! Check sources.")
    else:
        generate_sub(proxies)
