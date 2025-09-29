import requests
import base64
import subprocess
import time
import re
from urllib.parse import urlparse, parse_qs
import socket
import json
import random
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Proxy sources (updated for 2025, multi-protocol support)
SUB_SOURCES = [
    # Multi-protocol sources
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vless",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vmess",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/trojan",
    "https://raw.githubusercontent.com/yaney01/telegram-collector/main/protocols/vless",
    "https://raw.githubusercontent.com/yaney01/telegram-collector/main/protocols/vmess",
    "https://raw.githubusercontent.com/eQnz/configs-collector-v2ray/main/protocols/vless",
    "https://raw.githubusercontent.com/Kwinshadow/TelegramV2rayCollector/main/sublinks/vless.txt",
    "https://raw.githubusercontent.com/Farid-Karimi/Config-Collector/main/vless.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/filtered/subs/vless.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Splitted-By-Protocol/vless.txt",
]

# Trusted SNI for filtering
TRUSTED_SNI = [
    'www.cloudflare.com', 'www.microsoft.com', 'www.apple.com',
    'www.amazon.com', 'www.google.com', 'www.tencent.com', 'www.baidu.com'
]

# Test URLs (prioritize reliable domestic endpoints)
TEST_URLS = ['http://www.baidu.com', 'http://www.qq.com', 'http://www.taobao.com']

def fetch_proxies(max_proxies: int = 150) -> List[str]:
    """Fetch proxy configurations from multiple sources."""
    all_proxies = set()
    for url in SUB_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            content = resp.text.strip()
            logger.debug(f"Fetched from {url}: {len(content)} chars")

            links = []
            # Try base64 decoding for subscription links
            if len(content) % 4 == 0 and re.match(r'^[A-Za-z0-9+/=]+$', content):
                try:
                    decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                    links.extend(re.findall(r'(vless|vmess|trojan|ss)://[^\s\n]+', decoded))
                except Exception as e:
                    logger.debug(f"Base64 decode failed for {url}: {e}")

            # Extract proxy links from raw content
            if not links:
                links = [line.strip() for line in content.split('\n') 
                        if line.strip().startswith(('vless://', 'vmess://', 'trojan://', 'ss://'))]

            all_proxies.update(links)
            logger.info(f"Fetched {len(links)} proxies from {url}")
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")

    logger.info(f"Total unique proxies: {len(all_proxies)}")
    return list(all_proxies)[:max_proxies]

def is_host_valid(host: str) -> bool:
    """Validate host resolution."""
    try:
        socket.gethostbyname(host)
        return True
    except socket.gaierror:
        return False

def parse_proxy(url: str) -> Optional[Dict]:
    """Parse proxy URL into components."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        protocol = parsed.scheme
        config = {
            'protocol': protocol,
            'host': parsed.hostname,
            'port': parsed.port or 443,
            'params': params,
            'path': params.get('path', [''])[0],
            'sni': params.get('sni', [''])[0],
            'security': params.get('security', ['none'])[0],
            'type': params.get('type', ['tcp'])[0],
        }
        if protocol == 'vless':
            config.update({
                'uuid': parsed.username,
                'encryption': params.get('encryption', ['none'])[0],
                'fp': params.get('fp', [''])[0],
                'pbk': params.get('pbk', [''])[0],
                'sid': params.get('sid', [''])[0]
            })
        elif protocol == 'vmess':
            config.update({
                'uuid': parsed.username,
                'aid': params.get('aid', ['0'])[0],
                'encryption': params.get('encryption', ['auto'])[0]
            })
        elif protocol == 'trojan':
            config.update({
                'password': parsed.username,
                'alpn': params.get('alpn', [''])[0]
            })
        elif protocol == 'ss':
            # Shadowsocks format: ss://<method>:<password>@<host>:<port>
            decoded = base64.b64decode(parsed.netloc.split('@')[0]).decode('utf-8')
            method, password = decoded.split(':')
            config.update({
                'method': method,
                'password': password
            })
        return config
    except Exception as e:
        logger.error(f"Parse error for {url}: {e}")
        return None

def convert_to_v2ray_config(proxy_url: str) -> Optional[Dict]:
    """Convert proxy URL to v2ray config."""
    parsed = parse_proxy(proxy_url)
    if not parsed:
        return None

    protocol = parsed['protocol']
    config = {
        "inbounds": [{"port": 1080, "protocol": "socks", "settings": {"auth": "noauth"}}],
        "outbounds": [{"protocol": protocol, "settings": {}}]
    }

    if protocol == 'vless':
        config["outbounds"][0]["settings"] = {
            "vnext": [{
                "address": parsed['host'],
                "port": parsed['port'],
                "users": [{"id": parsed['uuid'], "encryption": parsed['encryption']}]
            }]
        }
    elif protocol == 'vmess':
        config["outbounds"][0]["settings"] = {
            "vnext": [{
                "address": parsed['host'],
                "port": parsed['port'],
                "users": [{"id": parsed['uuid'], "alterId": int(parsed['aid']), "security": parsed['encryption']}]
            }]
        }
    elif protocol == 'trojan':
        config["outbounds"][0]["settings"] = {
            "servers": [{
                "address": parsed['host'],
                "port": parsed['port'],
                "password": parsed['password']
            }]
        }
    elif protocol == 'ss':
        config["outbounds"][0]["settings"] = {
            "servers": [{
                "address": parsed['host'],
                "port": parsed['port'],
                "method": parsed['method'],
                "password": parsed['password']
            }]
        }

    config["outbounds"][0]["streamSettings"] = {
        "network": parsed['type'],
        "security": parsed['security']
    }

    if parsed['type'] == 'ws':
        config["outbounds"][0]["streamSettings"]["wsSettings"] = {
            "path": parsed['path'],
            "headers": {"Host": parsed['sni'] or parsed['host']}
        }
        if parsed['security'] == 'tls':
            config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
                "serverName": parsed['sni'],
                "fingerprint": parsed.get('fp', 'chrome')
            }
    elif parsed['type'] == 'grpc' and protocol in ['vless', 'vmess']:
        config["outbounds"][0]["streamSettings"]["grpcSettings"] = {
            "serviceName": parsed['params'].get('serviceName', [''])[0]
        }
        if parsed['security'] == 'tls':
            config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
                "serverName": parsed['sni'],
                "fingerprint": parsed.get('fp', 'chrome')
            }
    elif parsed['type'] == 'tcp' and parsed['security'] == 'reality' and protocol == 'vless':
        config["outbounds"][0]["streamSettings"]["realitySettings"] = {
            "publicKey": parsed['pbk'],
            "shortId": parsed['sid'],
            "serverName": parsed['sni'],
            "fingerprint": parsed['fp'] or 'chrome'
        }

    return config

def test_speed(proxy_url: str, max_retries: int = 2, timeout: int = 15) -> float:
    """Test proxy speed with retry mechanism."""
    parsed = parse_proxy(proxy_url)
    if not parsed or not is_host_valid(parsed['host']):
        logger.warning(f"Invalid host for {proxy_url}")
        return float('inf')

    # Filter weak security proxies
    if parsed['security'] not in ['tls', 'reality'] and not any(trusted in parsed['sni'] for trusted in TRUSTED_SNI):
        logger.warning(f"Filtered out {proxy_url} due to weak security/SNI")
        return float('inf')

    config = convert_to_v2ray_config(proxy_url)
    if not config:
        logger.warning(f"Failed to generate config for {proxy_url}")
        return float('inf')

    try:
        with open('temp.json', 'w', encoding='utf-8') as f:
            json.dump(config, f)
        proc = subprocess.Popen(['/usr/local/bin/xray', 'run', '-c', 'temp.json'], 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)  # Reduced wait time for faster testing

        latency = float('inf')
        for _ in range(max_retries):
            test_url = random.choice(TEST_URLS)
            result = subprocess.run(
                ['curl', '-o', '/dev/null', '-s', '--max-time', str(timeout), '-w', '%{time_total}',
                 test_url, '--socks5', '127.0.0.1:1080'],
                capture_output=True, text=True, timeout=timeout + 5
            )
            if result.returncode == 0:
                latency = float(result.stdout) * 1000
                logger.info(f"Success: {proxy_url[:50]}... - {latency:.2f}ms (tested on {test_url})")
                break
            time.sleep(0.5)

        proc.terminate()
        return latency
    except Exception as e:
        logger.error(f"Test failed for {proxy_url[:50]}...: {e}")
        return float('inf')
    finally:
        try:
            proc.terminate()
        except:
            pass

def generate_sub(proxies: List[str], top_n: int = 20, max_latency: float = 8000) -> None:
    """Generate subscription file with top performing proxies."""
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(test_speed, proxy) for proxy in proxies]
        for i, future in enumerate(futures):
            latency = future.result()
            if latency < max_latency:
                results.append((proxies[i], latency))

    logger.info(f"Total valid proxies: {len(results)}")
    top_proxies = sorted(results, key=lambda x: x[1])[:top_n]
    logger.info(f"Top {top_n} proxies: {[(p[:50] + '...' if len(p) > 50 else p, l) for p, l in top_proxies]}")

    # Write plain text subscription
    with open('sub.txt', 'w', encoding='utf-8') as f:
        for proxy, latency in top_proxies:
            f.write(f"{proxy} # Latency: {latency:.2f}ms\n")

    # Write base64 subscription
    all_links = '\n'.join([p[0] for p in top_proxies])
    b64_sub = base64.b64encode(all_links.encode('utf-8')).decode('utf-8')
    with open('sub_base64.txt', 'w', encoding='utf-8') as f:
        f.write(b64_sub)

    logger.info(f"Generated sub.txt and sub_base64.txt with {len(top_proxies)} proxies")

if __name__ == "__main__":
    proxies = fetch_proxies()
    if not proxies:
        logger.error("No proxies fetched! Check sources.")
    else:
        generate_sub(proxies)
