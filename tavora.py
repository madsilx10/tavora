import asyncio
import json
import time
import requests
from urllib.parse import parse_qs, unquote
from pyrogram import Client
from pyrogram.raw import functions
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import base64

# ================================
# CONFIG
# ================================
API_ID = 0
API_HASH = ""

BOT_USERNAME = "TavoraNode_Bot"
APP_URL = "https://tavoranode.vip/"

# ================================
# CRYPTO
# ================================
KEY1 = b"J8gD4uKpT2rV9ZbQ"
KEY2 = b"L1hW7gFqP3kM0VbY"

def encrypt(data):
    if not isinstance(data, str):
        data = json.dumps(data, separators=(',', ':'))
    cipher = AES.new(KEY1, AES.MODE_CBC, KEY2)
    padded = pad(data.encode('utf-8'), AES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode('utf-8')

def decrypt(data):
    raw = base64.b64decode(data)
    cipher = AES.new(KEY1, AES.MODE_CBC, KEY2)
    return unpad(cipher.decrypt(raw), AES.block_size).decode('utf-8')

def build_auth(init_data: str):
    payload = {
        "authorization": init_data,
        "time": int(time.time() * 1000),
        "lang": "en"
    }
    return encrypt(payload)

# ================================
# GET INIT DATA
# ================================
async def get_init_data(session_string: str):
    app = Client(
        "session_tmp",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session_string
    )
    async with app:
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
        fragment = full_url.split("#")[1] if "#" in full_url else full_url.split("?", 1)[1]
        params = parse_qs(fragment)
        return unquote(params.get("tgWebAppData", [""])[0])

# ================================
# API
# ================================
def get_headers(init_data: str):
    return {
        "Authorization": build_auth(init_data),
        "Content-Type": "application/json",
        "Lang": "en",
        "Referer": "https://tavoranode.vip/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    }

def api(method, path, init_data, data=None):
    url = "https://tavoranode.vip" + path
    resp = requests.request(method, url, headers=get_headers(init_data), json=data, timeout=10)
    try:
        result = resp.json()
        if isinstance(result, dict) and "e" in result:
            try:
                return json.loads(decrypt(result["e"]))
            except:
                return result
        return result
    except:
        return resp.text

def test_endpoints(init_data: str):
    endpoints = [
        ("GET",  "/api/user/info"),
        ("GET",  "/api/task/list"),
        ("GET",  "/api/deal/user/dividend/stats"),
        ("GET",  "/api/crypto/user/crypto-assets/list"),
        ("GET",  "/api/deal/user/list"),
        ("GET",  "/api/deal/rum"),
    ]
    for method, path in endpoints:
        try:
            result = api(method, path, init_data)
            print(f"[{method}] {path}")
            print(f"  → {str(result)[:300]}\n")
        except Exception as e:
            print(f"[ERR] {path}: {e}")

# ================================
# MAIN
# ================================
async def run(session_string: str, index: int):
    print(f"\n{'='*40}")
    print(f"[Account {index}] Getting initData...")
    init_data = await get_init_data(session_string)
    if not init_data:
        print(f"[Account {index}] Failed to get initData")
        return
    print(f"[Account {index}] OK\n")
    test_endpoints(init_data)

async def main():
    with open("sessions.txt") as f:
        sessions = [s.strip() for s in f.readlines() if s.strip()]

    for i, session in enumerate(sessions, 1):
        await run(session, i)

if __name__ == "__main__":
    asyncio.run(main())
