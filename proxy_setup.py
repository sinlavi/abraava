import os
import subprocess
import time
import requests
import re

def is_proxy_working():
    proxies = {
        "http": "socks5h://127.0.0.1:1080",
        "https": "socks5h://127.0.0.1:1080"
    }
    try:
        r = requests.get("https://cloudflare.com/cdn-cgi/trace", proxies=proxies, timeout=5)
        return "warp=on" in r.text
    except:
        return False

def setup_proxy():
    # If running in GitHub Actions, assume proxy is already set up by the workflow
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("🤖 CI environment detected (GitHub Actions). Checking for existing proxy...")
        if is_proxy_working():
            print("✅ Proxy is already running on 1080. Setting environment variables...")
            os.environ["HTTP_PROXY"] = "socks5h://127.0.0.1:1080"
            os.environ["HTTPS_PROXY"] = "socks5h://127.0.0.1:1080"
            os.environ["ALL_PROXY"] = "socks5h://127.0.0.1:1080"
            return
        else:
            print("⚠️ Proxy not detected in CI, but skipping setup to avoid FileNotFoundError.")
            return

    # Check if proxy is already working before attempting setup
    if is_proxy_working():
        print("✅ Proxy is already working. Skipping setup.")
        os.environ["HTTP_PROXY"] = "socks5h://127.0.0.1:1080"
        os.environ["HTTPS_PROXY"] = "socks5h://127.0.0.1:1080"
        os.environ["ALL_PROXY"] = "socks5h://127.0.0.1:1080"
        return

    bin_dir = os.path.join(os.getcwd(), "bin")
    wgcf_path = os.path.join(bin_dir, "wgcf")
    wireproxy_path = os.path.join(bin_dir, "wireproxy")
    conf_path = "wgcf-profile.conf"
    wire_conf_path = "wireproxy.conf"

    if not os.path.exists(bin_dir):
        print("⚠️ bin directory not found. Skipping proxy setup.")
        return

    if not os.path.exists(conf_path):
        print("🔧 Registering wgcf...")
        if not os.path.exists(wgcf_path):
            print("❌ wgcf binary not found.")
            return
        subprocess.run(["chmod", "+x", wgcf_path])
        subprocess.run([wgcf_path, "register", "--accept-tos"], input=b"yes\n")
        subprocess.run([wgcf_path, "generate"])

    if not os.path.exists(wire_conf_path):
        print("🔧 Creating wireproxy config...")
        if not os.path.exists(conf_path):
            print("❌ wgcf-profile.conf not found.")
            return

        with open(conf_path, "r") as f:
            content = f.read()

        def get_val(key):
            m = re.search(fr"^{key}\s*=\s*(.*)$", content, re.MULTILINE)
            return m.group(1).strip() if m else ""

        address = get_val("Address")
        ipv4, ipv6 = "", ""
        if address:
            parts = [p.strip() for p in address.split(",")]
            for p in parts:
                if ":" in p: ipv6 = p
                else: ipv4 = p

        wire_conf = f"""[WG]
PrivateKey = {get_val("PrivateKey")}
IPv4 = {ipv4}
IPv6 = {ipv6}

[Peer]
PublicKey = {get_val("PublicKey")}
Endpoint = {get_val("Endpoint")}
AllowedIPs = 0.0.0.0/0, ::/0

[Socks5]
BindAddress = 127.0.0.1:1080
"""
        with open(wire_conf_path, "w") as f:
            f.write(wire_conf)

    print("🚀 Starting wireproxy...")
    if not os.path.exists(wireproxy_path):
        print("❌ wireproxy binary not found.")
        return
    subprocess.run(["chmod", "+x", wireproxy_path])
    # Run wireproxy in background and don't block
    subprocess.Popen([wireproxy_path, "-c", wire_conf_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("⏳ Waiting for wireproxy...")
    for i in range(1, 31):
        if is_proxy_working():
            print("✅ WARP is ready!")
            break
        print(f"⏳ Attempt {i}/30: WARP not ready yet...")
        time.sleep(2)

    os.environ["HTTP_PROXY"] = "socks5h://127.0.0.1:1080"
    os.environ["HTTPS_PROXY"] = "socks5h://127.0.0.1:1080"
    os.environ["ALL_PROXY"] = "socks5h://127.0.0.1:1080"

if __name__ == "__main__":
    setup_proxy()
