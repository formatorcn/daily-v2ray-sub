import requests
import base64
import subprocess
import time
import re
from urllib.parse import urlparse

# 步骤1: 定义GitHub代理源列表（从搜索结果中选取可靠源）
SUB_SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Config_base64_Sub.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/V2Ray-Config-By-EbraSha-All-Type.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Sub1.txt",
    # 添加更多源，如Clash转V2Ray：https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/clash.yml (需转换)
]

def fetch_proxies():
    """从源收集代理链接（支持vmess://, vless://, ss:// 等）"""
    all_proxies = set()
    for url in SUB_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                # 解析base64订阅或纯链接
                content = resp.text.strip()
                if 'base64' in url:  # base64订阅
                    decoded = base64.b64decode(content).decode('utf-8')
                    links = re.findall(r'(vmess://[^\n]+|vless://[^\n]+|ss://[^\n]+)', decoded)
                else:
                    links = [line.strip() for line in content.split('\n') if line.strip().startswith(('vmess://', 'vless://', 'ss://'))]
                all_proxies.update(links)
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    return list(all_proxies)[:100]  # 限100个避免超时

def test_speed(proxy_url):
    """测试代理速度（延迟ms，使用curl下载小文件测试）"""
    try:
        # 解析代理为SOCKS/HTTP（简化，实际需v2ray核心测试；这里用简单ping模拟）
        # 真实实现：用subprocess调用v2ray test或curl --proxy
        cmd = ['curl', '-o', '/dev/null', '-s', '--max-time', '10', '-w', '%{time_total}', 'http://www.gstatic.com/generate_204', '--proxy', proxy_url.replace('://', '://user:pass@')]  # 伪代理，需调整
        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            latency = float(result.stdout) * 1000  # ms
            return latency
        else:
            return float('inf')  # 失败=无限大
    except:
        return float('inf')

def generate_sub(proxies, top_n=10):
    """生成订阅文件：base64编码的多行链接"""
    # 测试并排序
    results = []
    for proxy in proxies:
        latency = test_speed(proxy)
        results.append((proxy, latency))
        time.sleep(1)  # 避免限速
    
    # 排序取前10
    top_proxies = sorted(results, key=lambda x: x[1])[:top_n]
    
    # 写入sub.txt（每行一个链接）
    with open('sub.txt', 'w') as f:
        for proxy, _ in top_proxies:
            f.write(proxy + '\n')
    
    # 生成base64订阅（可选，一行base64所有）
    all_links = '\n'.join([p[0] for p in top_proxies])
    b64_sub = base64.b64encode(all_links.encode()).decode()
    with open('sub_base64.txt', 'w') as f:
        f.write(b64_sub)
    
    print(f"Updated sub.txt with top {top_n} proxies")

if __name__ == "__main__":
    proxies = fetch_proxies()
    generate_sub(proxies)
