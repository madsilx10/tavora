import asyncio
import requests
from urllib.parse import parse_qs, unquote
from pyrogram import Client
from pyrogram.raw import functions

# ================================
# CONFIG
# ================================
API_ID = 0           # ganti
API_HASH = ""        # ganti
SESSION_STRING = ""  # session string akun lo

BOT_USERNAME = "TavoraNode_Bot"
APP_URL = "https://tavoranode.vip/"

# ================================
# GET INIT DATA
# ================================
async def get_init_data():
    app = Client(
        "session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING
    )

    async with app:
        print("[*] Connecting...")
        peer = await app.resolve_peer(BOT_USERNAME)

        result = await app.invoke(
            functions.messages.RequestWebView(
                peer=peer,
                bot=peer,
                platform="android",
                url=APP_URL,
                from_bot_menu=False,
            )
        )

        full_url = result.url
        print(f"[+] Full URL:\n{full_url}\n")

        # Extract tgWebAppData
        fragment = full_url.split("#")[1] if "#" in full_url else full_url.split("?", 1)[1]
        params = parse_qs(fragment)
        init_data = unquote(params.get("tgWebAppData", [""])[0])

        if not init_data:
            print("[-] initData not found")
            return None

        print(f"[+] initData:\n{init_data}\n")

        with open("initdata.txt", "w") as f:
            f.write(init_data)
        print("[+] Saved to initdata.txt")

        return init_data

# ================================
# TEST HIT API
# ================================
def test_api(init_data: str):
    headers = {
        "Authorization": init_data,
        "Content-Type": "application/json",
        "Lang": "en",
        "Referer": "https://tavoranode.vip/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    }

    endpoints = [
        ("GET",  "/api/deal/user/dividend/stats"),
        ("GET",  "/api/crypto/user/crypto-assets/list"),
        ("GET",  "/api/deal/user/list"),
        ("GET",  "/api/deal/rum"),
        ("GET",  "/api/user/info"),
        ("GET",  "/api/task/list"),
    ]

    base_url = "https://tavoranode.vip"

    for method, path in endpoints:
        try:
            url = base_url + path
            resp = requests.request(method, url, headers=headers, timeout=10)
            print(f"[{resp.status_code}] {method} {path}")
            try:
                print(f"  → {str(resp.json())[:300]}\n")
            except:
                print(f"  → {resp.text[:300]}\n")
        except Exception as e:
            print(f"[ERR] {path}: {e}")

async def main():
    init_data = await get_init_data()
    if init_data:
        print("\n[*] Testing endpoints...\n")
        test_api(init_data)

if __name__ == "__main__":
    asyncio.run(main())
