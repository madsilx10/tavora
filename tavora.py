import asyncio
import json
import time
import base64
import requests
from urllib.parse import parse_qs, unquote
from pyrogram import Client
from pyrogram.raw import functions
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# ================================
# CONFIG  (isi sendiri)
# ================================
API_ID = 0          # <-- isi api_id my.telegram.org lu
API_HASH = ""       # <-- isi api_hash lu

BOT_USERNAME = "TavoraNode_Bot"
APP_URL = "https://tavoranode.vip/"
BASE = "https://tavoranode.vip"
REFERRER_CODE = "ref_MVZ0MIFD"   # dari https://t.me/TavoraNode_Bot?start=ref_MVZ0MIFD

# ================================
# CRYPTO — terverifikasi dari JS bundle situs (entry Bj0p-LvZ.js):
# AES-256-CBC, key=KEY1 (utf8), iv=KEY2 (utf8), PKCS7, base64
# ================================
KEY1 = b"J8gD4uKpT2rV9ZbQ"
KEY2 = b"L1hW7gFqP3kM0VbY"

def encrypt(data):
    if not isinstance(data, str):
        data = json.dumps(data, separators=(',', ':'))
    cipher = AES.new(KEY1, AES.MODE_CBC, KEY2)
    return base64.b64encode(cipher.encrypt(pad(data.encode(), AES.block_size))).decode()

def decrypt(data):
    raw = base64.b64decode(data)
    cipher = AES.new(KEY1, AES.MODE_CBC, KEY2)
    return unpad(cipher.decrypt(raw), AES.block_size).decode()

def unwrap(resp_json):
    """Respons kadang dibungkus {"e": "<enkripsi>"} — buka kalau ada."""
    if isinstance(resp_json, dict) and "e" in resp_json:
        try:
            return json.loads(decrypt(resp_json["e"]))
        except Exception:
            return resp_json
    return resp_json

# ================================
# HEADERS — skema ASLI dari frontend (fungsi rd() di bundle):
#   authorization = encrypt({uid, token, time, device_id, referrer_code})
#   + header "time" (ms, sama dengan di dalam payload) dan "lang"
# initData TIDAK PERNAH masuk header. initData cuma dikirim di body login.
# ================================
def build_headers(uid="", token="", referrer_code=""):
    now_ms = int(time.time() * 1000)
    payload = {
        "uid": uid,
        "token": token,
        "time": now_ms,
        "device_id": "",
        "referrer_code": referrer_code,
    }
    return {
        "authorization": encrypt(payload),
        "time": str(now_ms),
        "lang": "en",
        "Content-Type": "application/json",
        "Referer": "https://tavoranode.vip/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    }

# ================================
# GET INIT DATA (punya lu, sudah benar)
# ================================
async def get_init_data(session_string: str):
    app = Client("session_tmp", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
    async with app:
        peer = await app.resolve_peer(BOT_USERNAME)
        result = await app.invoke(
            functions.messages.RequestWebView(
                peer=peer, bot=peer, platform="android",
                url=APP_URL, from_bot_menu=False,
            )
        )
        full_url = result.url
        fragment = full_url.split("#")[1] if "#" in full_url else full_url.split("?", 1)[1]
        params = parse_qs(fragment)
        return unquote(params.get("tgWebAppData", [""])[0])

def start_param_from(init_data: str) -> str:
    qs = parse_qs(init_data)
    return unquote(qs.get("start_param", [""])[0])

# ================================
# LOGIN — langkah yang HILANG di skrip lama lu.
# POST /api/user/login/tg, body PLAIN JSON (bukan {e:...}).
# Terverifikasi live 2 Nov 2026:
#   body plain + initData palsu  -> {"error":"User verification failed"}  (format diterima, hash ditolak)
#   body {"e":...}               -> {"error":"Please open in the TG client;"} (server nyari field initData, nggak ketemu)
# Sukses -> respons berisi user_info + auth_info (token sesi untuk semua request berikutnya)
# ================================
def login_tg(init_data: str):
    ref = start_param_from(init_data) or REFERRER_CODE
    resp = requests.post(
        BASE + "/api/user/login/tg",
        headers=build_headers(referrer_code=ref),
        json={"initData": init_data, "referrer_code": ref, "turnstileToken": ""},
        timeout=30,
    )
    result = unwrap(resp.json()) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"login gagal: {result['error']}")
    # frontend menyimpan persis dua field ini dari level atas respons
    data = result.get("data", result) if isinstance(result, dict) else {}
    user_info = result.get("user_info") or data.get("user_info") or {}
    auth_info = result.get("auth_info") or data.get("auth_info") or ""
    uid = str(user_info.get("uid", "")) if isinstance(user_info, dict) else ""
    if not auth_info:
        raise RuntimeError(f"login: auth_info kosong, respons mentah: {str(result)[:300]}")
    return uid, auth_info, user_info

# ================================
# API setelah login: GET = query params polos, POST = body JSON polos
# ================================
class Tavora:
    def __init__(self, uid, token):
        self.uid, self.token = uid, token

    def get(self, path, params=None):
        r = requests.get(BASE + "/api" + path, headers=build_headers(self.uid, self.token),
                         params=params, timeout=30)
        return unwrap(r.json())

    def post(self, path, data=None):
        r = requests.post(BASE + "/api" + path, headers=build_headers(self.uid, self.token),
                          json=data or {}, timeout=30)
        return unwrap(r.json())

    # ---- endpoint ASLI (ekstrak dari JS bundle, 2 Nov 2026) ----
    def user_info(self):        return self.get("/user/user/user/info")
    def signin_info(self):      return self.get("/user/user/sign-in/info")
    def signin_create(self):    return self.post("/user/user/sign-in/create")
    def lottery_info(self):     return self.get("/user/user/user-lottery/info")
    def assets_list(self):      return self.get("/crypto/user/crypto-assets/list")
    def assets_info(self):      return self.get("/crypto/user/crypto-assets/info")
    def dividend_stats(self):   return self.get("/deal/user/dividend/stats")
    def dividend_fund(self):    return self.get("/deal/user/dividend/fund")
    def deal_list(self):        return self.get("/deal/user/deal/list")
    def load_list(self, page=1): return self.get("/deal/user/load/list", {"page": page})
    def team_stats(self):       return self.get("/user/user/user-referrer/team-stats")
    def social_share_list(self): return self.get("/social/user/social-share/list")
    def market_tvr(self):       return self.get("/crypto/market/tvr")

def test_endpoints(api: Tavora):
    tests = [
        ("user_info", api.user_info), ("signin_info", api.signin_info),
        ("lottery_info", api.lottery_info), ("assets_list", api.assets_list),
        ("dividend_stats", api.dividend_stats), ("deal_list", api.deal_list),
        ("team_stats", api.team_stats), ("social_share_list", api.social_share_list),
        ("market_tvr", api.market_tvr),
    ]
    for name, fn in tests:
        try:
            print(f"[{name}] -> {str(fn())[:300]}\n")
        except Exception as e:
            print(f"[ERR] {name}: {e}\n")

# ================================
# MAIN
# ================================
async def run(session_string: str, index: int):
    print(f"\n{'='*40}\n[Account {index}] Getting initData...")
    init_data = await get_init_data(session_string)
    if not init_data:
        print(f"[Account {index}] Failed to get initData"); return
    print(f"[Account {index}] initData OK, login...")
    try:
        uid, token, user_info = login_tg(init_data)
    except Exception as e:
        print(f"[Account {index}] {e}"); return
    print(f"[Account {index}] LOGIN OK uid={uid} user={str(user_info)[:150]}\n")
    test_endpoints(Tavora(uid, token))

async def main():
    with open("sessions.txt") as f:
        sessions = [s.strip() for s in f.readlines() if s.strip()]
    for i, session in enumerate(sessions, 1):
        await run(session, i)

if __name__ == "__main__":
    asyncio.run(main())
