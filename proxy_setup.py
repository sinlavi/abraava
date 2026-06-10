import os
import subprocess
import time
import requests

def setup_proxy():
    bin_dir = os.path.join(os.getcwd(), "bin")
    wgcf_path = os.path.join(bin_dir, "wgcf")
    wireproxy_path = os.path.join(bin_dir, "wireproxy")
    conf_path = "wgcf-profile.conf"
    wire_conf_path = "wireproxy.conf"

    if not os.path.exists(conf_path):
        print("🔧 Registering wgcf...")
        subprocess.run(["chmod", "+x", wgcf_path])
        subprocess.run([wgcf_path, "register", "--accept-tos"], input=b"yes\n")
        subprocess.run([wgcf_path, "generate"])

    if not os.path.exists(wire_conf_path):
        print("🔧 Creating wireproxy config...")
        with open(conf_path, "r") as f:
            lines = f.readlines()

        def get_val(key):
            for line in lines:
                if line.startswith(key):
                    return line.split("=")[1].strip()
            return ""

        wire_conf = f"""[WG]
PrivateKey = {get_val("PrivateKey")}
Address = {get_val("Address")}
PublicKey = {get_val("PublicKey")}
Endpoint = {get_val("Endpoint")}

[Socks5]
BindAddress = 127.0.0.1:1080
"""
        with open(wire_conf_path, "w") as f:
            f.write(wire_conf)

    print("🚀 Starting wireproxy...")
    subprocess.run(["chmod", "+x", wireproxy_path])
    subprocess.Popen([wireproxy_path, "-c", wire_conf_path])

    print("⏳ Waiting for wireproxy...")
    proxies = {
        "http": "socks5h://127.0.0.1:1080",
        "https": "socks5h://127.0.0.1:1080"
    }
    for i in range(1, 31):
        try:
            r = requests.get("https://cloudflare.com/cdn-cgi/trace", proxies=proxies, timeout=5)
            if "warp=on" in r.text:
                print("✅ WARP is ready!")
                break
        except:
            pass
        print(f"⏳ Attempt {i}/30: WARP not ready yet...")
        time.sleep(2)

    os.environ["HTTP_PROXY"] = "socks5h://127.0.0.1:1080"
    os.environ["HTTPS_PROXY"] = "socks5h://127.0.0.1:1080"
    os.environ["ALL_PROXY"] = "socks5h://127.0.0.1:1080"

if __name__ == "__main__":
    setup_proxy()
