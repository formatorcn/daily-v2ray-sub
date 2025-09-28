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
    # Barry-far 的新路径（Splitted-By-Protocol，按协议分开，避免大文件）
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",  # Vless 专用
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vmess.txt",  # Vmess 专用
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/ss.txt",     # Shadowsocks 专用
    
    # Epodonios 的合并源（每5分钟更新）
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt",
    
    # MatinGhanbari 的过滤源（每15分钟更新，支持多协议）
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vmess.txt",
    
    # Ebrasha 的多类型源（每30分钟更新）
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/vless_configs.txt",
    
    # 其他活跃源（2025年更新）
    "https://raw.githubusercontent.com/Mahdi0024/ProxyCollector/main/proxies/vless.txt",  # 自动测试过的
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub.txt",  # 简单 vless 列表
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
                print(f"Fetched {len(links)} proxies from {url}")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    print(f"Total unique proxies: {len(all_proxies)}")
    return list(all_proxies)[:50]

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
    config = {
        "inbounds": [{"port": 1080, "protocol": "socks", "settings": {"auth": "noauth"}}],
        "outbounds": [{}]
    }
    outbound = config["outbounds"][0]
    if parsed['protocol'] == 'vless':
        outbound["protocol"] = "vless"
        outbound["settings"] = {
            "vnext": [{
                "address": parsed['host'],
                "port": parsed['port'],
                "users": [{"id": parsed['uuid'], "encryption": parsed['encryption']}]
            }]
        }
        if parsed['type'] == 'ws':
            outbound["streamSettings"] = {
                "network": "ws",
                "wsSettings": {"path": parsed['path'], "headers": {"Host": parsed.get('host', '')}},
                "security": parsed['security'],
                "tlsSettings": {"serverName": parsed['sni']} if parsed['security'] == 'tls' else {}
            }
        elif parsed['type'] == 'grpc':
            outbound["streamSettings"] = {
                "network": "grpc",
                "grpcSettings": {"serviceName": parsed['params'].get('serviceName', [''])[0]},
                "security": parsed['security']
            }
        elif parsed['type'] == 'tcp':
            outbound["streamSettings"] = {
                "network": "tcp",
                "security": parsed['security'],
                "tlsSettings": {"serverName": parsed['sni']} if parsed['security'] == 'tls' else {}
            }
    elif parsed['protocol'] == 'vmess':
        outbound["protocol"] = "vmess"
        outbound["settings"] = {
            "vnext": [{
                "address": parsed['host'],
                "port": parsed['port'],
                "users": [{"id": parsed['uuid'], "alterId": 0, "security": parsed.get('scy', 'auto')}]
            }]
        }
        if parsed['type'] == 'ws':
            outbound["streamSettings"] = {
                "network": "ws",
                "wsSettings": {"path": parsed['path'], "headers": {"Host": parsed.get('host', '')}},
                "security": parsed['security']
            }
    elif parsed['protocol'] == 'ss':
        try:
            decoded = base64.b64decode(parsed['uuid'].split('@')[0]).decode('utf-8')
            cipher, password = decoded.split(':')
            outbound["protocol"] = "shadowsocks"
            outbound["settings"] = {
                "servers": [{
                    "address": parsed['host'],
                    "port": parsed['port'],
                    "method": cipher,
                    "password": password
                }]
            }
        except Exception as e:
            print(f"Failed to parse Shadowsocks URL {proxy_url}: {e}")
            return None
    else:
        return None
    return config

def test_speed(proxy_url):
    parsed = parse_proxy(proxy_url)
    if not parsed or not is_host_valid(parsed['host']):
        print(f"Invalid host for {proxy_url}")
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
        
        result = subprocess.run(
            ['curl', '-o', '/dev/null', '-s', '--max-time', '20', '-w', '%{time_total}',
             'http://www.gstatic.com/generate_204', '--socks5', '127.0.0.1:1080'],
            capture_output=True, text=True, timeout=25
        )
        
        proc.terminate()
        if result.returncode == 0:
            latency = float(result.stdout) * 1000
            print(f"Success: {proxy_url} - {latency}ms")
            return latency
        else:
            print(f"Curl failed for {proxy_url}: {result.stderr}")
            return float('inf')
    except Exception as e:
        print(f"Test failed for {proxy_url}: {e}")
        return float('inf')

def generate_sub(proxies, top_n=10, max_latency=10000):
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
