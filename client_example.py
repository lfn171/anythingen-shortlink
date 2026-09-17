import requests

# 请将此地址替换为你的实际访问地址
BASE = "https://your-domain.com"
API_KEY = "替换成你的 API_KEY"
HEADERS = {"X-API-Key": API_KEY}


def create_link(target_url, note="", code=None):
    payload = {"target_url": target_url, "note": note}
    if code:
        payload["code"] = code
    r = requests.post(f"{BASE}/api/links", json=payload, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()["data"]


def update_link(code, target_url):
    r = requests.patch(
        f"{BASE}/api/links/{code}",
        json={"target_url": target_url},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["data"]


if __name__ == "__main__":
    result = create_link(
        "https://pan.quark.cn/s/9aa07374413b",
        note="测试资源",
    )
    print(result["short_url"])
