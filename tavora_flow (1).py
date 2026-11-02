"""
TAVORA — alur lengkap per akun (sesuai urutan manual di aplikasi):
  1. Buka link ref  -> klik Start di bot      (kirim "/start ref_..." ke @TavoraNode_Bot)
  2. Open Mini App   -> ambil initData (RequestWebView) lalu POST /api/user/login/tg
  3. Buy Node        -> POST /api/deal/user/load/create {"deal_id": ...}
                        (node termurah dari /api/deal/user/deal/list; Node S = id 15, 120 TVR)
                        SKIP kalau akun sudah punya node / saldo TVR kurang.
  4. Daily Check-in  -> POST /api/user/user/sign-in/create (tanpa body)
                        SKIP kalau hari ini (tanggal server) sudah check-in.
  5. Spin Lucky Draw -> POST /api/user/user/user-lottery/create (tanpa body)
                        diulang selama kuota lottery_times > 0 dan belum kena limit harian.

Semua endpoint + skema header terverifikasi dari JS bundle tavoranode.vip (lihat ENDPOINTS.md).
Output TIDAK mencetak initData / token / session string — aman buat di-share buat debug.

Isi API_ID, API_HASH, dan sessions.txt — BOLEH banyak akun, 1 session string Pyrogram per baris:
  sessions.txt
  session1
  session2
  session3

Lalu jalanin:  python tavora_flow.py
Di awal skrip nanya mau jalanin yang mana: (1) 1 akun, (2) semua akun, (3) dari akun X sampai akhir.
Jalan pintas tanpa menu:  python tavora_flow.py all   |   python tavora_flow.py 3   |   python tavora_flow.py from 3
"""
import asyncio
import sys
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
# CONFIG
# ================================
API_ID = 0          # <-- isi
API_HASH = ""       # <-- isi

BOT_USERNAME = "TavoraNode_Bot"
APP_URL = "https://tavoranode.vip/"
BASE = "https://tavoranode.vip"

# Link ref: https://t.me/TavoraNode_Bot?start=ref_MVZ0MIFD
START_PAYLOAD = "ref_MVZ0MIFD"   # payload persis yang dikirim pas klik link + Start
REFERRER_CODE = "ref_MVZ0MIFD"   # fallback referrer_code login kalau initData nggak bawa start_param

BUY_NODE = True          # False = lewati langkah buy node
SPIN_ALL = True          # True = putar semua kuota spin yang tersedia (dibatasi limit harian server)
DELAY_BETWEEN_ACCOUNTS = 15  # detik, antar akun (IP yang sama kena throttle kalau terlalu rapat)
STEP_DELAY = 8           # detik, jeda antar langkah (buy -> check-in -> spin) dalam 1 akun
FREQUENT_RETRIES = 4     # error "Frequent operations" = throttle server: tunggu lalu coba lagi
FREQUENT_WAIT = 15       # detik, dikali nomor percobaan (15, 30, 45, ...)

# ================================
# CRYPTO (dari bundle situs, sama persis)
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
    if isinstance(resp_json, dict) and "e" in resp_json:
        try:
            return json.loads(decrypt(resp_json["e"]))
        except Exception:
            return resp_json
    return resp_json

def build_headers(uid="", token="", referrer_code=""):
    now_ms = int(time.time() * 1000)
    payload = {"uid": uid, "token": token, "time": now_ms, "device_id": "", "referrer_code": referrer_code}
    return {
        "authorization": encrypt(payload),
        "time": str(now_ms),
        "lang": "en",
        "Content-Type": "application/json",
        "Referer": "https://tavoranode.vip/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
    }

# ================================
# API client (setelah login)
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

    def post_retry(self, path, data=None, label="aksi"):
        """POST dengan retry khusus error throttle 'Frequent operations':
        tunggu FREQUENT_WAIT * percobaan detik, sampai FREQUENT_RETRIES kali.
        Error lain langsung dikembalikan tanpa retry."""
        res = None
        for attempt in range(1, FREQUENT_RETRIES + 1):
            res = self.post(path, data)
            if isinstance(res, dict) and "frequent" in str(res.get("error") or "").lower():
                if attempt == FREQUENT_RETRIES:
                    break
                wait = FREQUENT_WAIT * attempt
                print(f"    [{label}] kena 'Frequent operations' — tunggu {wait} detik, coba lagi ({attempt}/{FREQUENT_RETRIES})...")
                time.sleep(wait)
                continue
            break
        return res

    def tvr_balance(self):
        res = self.get("/crypto/user/crypto-assets/list")
        for a in (res.get("assetsList") or []):
            if a.get("token") == "TVR":
                return float(a.get("balance") or 0)
        return 0.0

    def usdt_balance(self):
        # USDT bukan di assetsList (isinya cuma TVR) — dia di user_info.balance (uang akun)
        res = self.get("/user/user/user/info")
        ui = res.get("user_info") or res
        return float(ui.get("balance") or 0)

    def my_nodes(self):
        res = self.get("/deal/user/load/list", {"page": 1})
        return res.get("list") or []

    def cheapest_deal(self):
        res = self.get("/deal/user/deal/list")
        deals = [d for d in (res.get("list") or []) if float(d.get("min_money") or 0) > 0]
        return min(deals, key=lambda d: float(d["min_money"])) if deals else None

# ================================
# Langkah 1+2: Start bot + buka Mini App (initData) + login
# ================================
async def open_mini_app(session_string: str) -> str:
    app = Client("session_tmp", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
    async with app:
        peer = await app.resolve_peer(BOT_USERNAME)
        # 1) klik Start persis kayak buka link ref (nggak fatal kalau gagal / sudah pernah start)
        try:
            await app.send_message(BOT_USERNAME, f"/start {START_PAYLOAD}")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"    (start bot dilewati: {e})")
        # 2) open Mini App (start_param diabaikan server Telegram kalau bot nggak pakai direct-link;
        #    fallback tanpa start_param kalau versi Pyrogram lu nggak kenal argumennya)
        try:
            result = await app.invoke(
                functions.messages.RequestWebView(
                    peer=peer, bot=peer, platform="android",
                    url=APP_URL, from_bot_menu=False, start_param=START_PAYLOAD,
                )
            )
        except TypeError:
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

def login_tg(init_data: str):
    qs = parse_qs(init_data)
    ref = unquote(qs.get("start_param", [""])[0]) or REFERRER_CODE
    resp = requests.post(
        BASE + "/api/user/login/tg",
        headers=build_headers(referrer_code=ref),
        json={"initData": init_data, "referrer_code": ref, "turnstileToken": ""},
        timeout=30,
    )
    result = unwrap(resp.json())
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"login gagal: {result['error']}")
    data = result.get("data", result) if isinstance(result, dict) else {}
    user_info = result.get("user_info") or data.get("user_info") or {}
    auth_info = result.get("auth_info") or data.get("auth_info") or ""
    uid = str(user_info.get("uid", "")) if isinstance(user_info, dict) else ""
    if not auth_info:
        raise RuntimeError(f"login: auth_info kosong: {str(result)[:200]}")
    return uid, auth_info, user_info

# ================================
# Langkah 3: Buy Node
# ================================
def buy_node(api: Tavora):
    owned = api.my_nodes()
    if owned:
        names = ", ".join(str(n.get("deal_name") or n.get("id")) for n in owned)
        print(f"    [buy] SKIP — sudah punya node: {names}")
        return
    deal = api.cheapest_deal()
    if not deal:
        print("    [buy] SKIP — daftar node kosong"); return
    price = float(deal["min_money"])
    balance = api.tvr_balance()
    print(f"    [buy] node termurah: {deal.get('deal_name')} (id {deal.get('id')}) harga {price:g} TVR | saldo {balance:g} TVR")
    if balance < price:
        print("    [buy] SKIP — saldo TVR kurang"); return
    res = api.post_retry("/deal/user/load/create", {"deal_id": deal["id"]}, label="buy")
    if isinstance(res, dict) and res.get("error"):
        print(f"    [buy] GAGAL — {res['error']}"); return
    print(f"    [buy] OK — {res.get('msg') or res}")
    print(f"    [buy] saldo TVR sekarang: {api.tvr_balance():g}")

# ================================
# Langkah 4: Daily Check-in
# Frontend: sudah check-in kalau tanggal hari ini (server) ada di signInList.
# ================================
def daily_checkin(api: Tavora):
    info = api.get("/user/user/sign-in/info")
    server_date = str(info.get("server_time", ""))[:10]  # 'YYYY-MM-DD'
    sign_list = info.get("signInList")
    if isinstance(sign_list, dict) and server_date in sign_list:
        print("    [checkin] SKIP — hari ini sudah check-in"); return
    res = api.post_retry("/user/user/sign-in/create", label="checkin")
    if isinstance(res, dict) and res.get("error"):
        print(f"    [checkin] GAGAL — {res['error']}"); return
    print(f"    [checkin] OK — {res.get('msg') or res}")

# ================================
# Langkah 5: Spin Lucky Draw
# Frontend: boleh spin kalau lottery_times > 0 dan lottery_times_yet < limit_times.
# ================================
def _prize_label(res):
    """Respons spin isinya field 'name' (itu yang ditampilin popup hadiah di aplikasi,
    mis. '0.3 TVR'), kadang plus 'number'/'type'. Gabung semua yang ada, jangan sampai kosong."""
    if not isinstance(res, dict):
        return str(res)
    name = str(res.get("name") or "").strip()
    parts = [name] if name else []
    for key in ("number", "type"):
        v = res.get(key)
        if v not in (None, "") and str(v) not in name:
            parts.append(str(v))
    return " ".join(parts).strip() or str(res)[:200]

def spin_lucky(api: Tavora):
    spun = 0
    prizes = []
    while True:
        info = api.get("/user/user/user-lottery/info").get("info") or {}
        times = int(info.get("lottery_times") or 0)
        yet = int(info.get("lottery_times_yet") or 0)
        limit = int(info.get("limit_times") or 0)
        if times <= 0 or (limit > 0 and yet >= limit):
            print(f"    [spin] berhenti — kuota {times}, sudah dipakai {yet}/{limit or '∞'}")
            break
        res = api.post_retry("/user/user/user-lottery/create", label="spin")
        if isinstance(res, dict) and res.get("error"):
            print(f"    [spin] GAGAL — {res['error']}"); break
        spun += 1
        label = _prize_label(res)
        prizes.append(label)
        print(f"    [spin] #{spun} OK — hadiah: {label}")
        if not SPIN_ALL:
            break
        time.sleep(5)  # jeda antar spin (animasi roda di aplikasi ±3 dtk; ditambahin biar aman dari throttle)
    if prizes:
        print(f"    [spin] rekap {spun}x spin: " + ", ".join(prizes))

# ================================
# MAIN — per akun: start -> open app -> login -> buy -> checkin -> spin
# ================================
async def run(session_string: str, index: int):
    print(f"\n{'='*44}\n[Account {index}] start bot + open mini app...")
    try:
        init_data = await open_mini_app(session_string)
        if not init_data:
            print(f"[Account {index}] GAGAL ambil initData"); return
        uid, token, user_info = login_tg(init_data)
    except Exception as e:
        print(f"[Account {index}] GAGAL login: {e}"); return
    print(f"[Account {index}] LOGIN OK uid={uid} user={user_info.get('user_name')}")
    api = Tavora(uid, token)
    try:
        if BUY_NODE:
            buy_node(api)
            print(f"    ...jeda {STEP_DELAY} detik biar nggak kena throttle server...")
            await asyncio.sleep(STEP_DELAY)
        daily_checkin(api)
        print(f"    ...jeda {STEP_DELAY} detik biar nggak kena throttle server...")
        await asyncio.sleep(STEP_DELAY)
        spin_lucky(api)
    except Exception as e:
        print(f"[Account {index}] ERROR di tengah alur: {e}")
    try:
        print(f"[Account {index}] selesai. Saldo akhir: {api.tvr_balance():g} TVR | {api.usdt_balance():g} USDT")
    except Exception:
        print(f"[Account {index}] selesai. Saldo TVR akhir: {api.tvr_balance():g}")

def _ask_number(prompt, lo, hi):
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        print(f"    masukin angka {lo}-{hi} ya.")

def pick_accounts(sessions):
    """Balikin list [(nomor_asli, session), ...] sesuai pilihan user.
    Nomor asli = nomor baris di sessions.txt, biar label [Account N] nggak geser
    pas jalanin sebagian doang."""
    total = len(sessions)
    all_accounts = list(enumerate(sessions, 1))

    # jalan pintas dari command line, tanpa menu
    args = [a.lower() for a in sys.argv[1:]]
    if args:
        if args[0] == "all":
            return all_accounts
        if args[0] == "from" and len(args) > 1 and args[1].isdigit() and 1 <= int(args[1]) <= total:
            return all_accounts[int(args[1]) - 1:]
        if args[0].isdigit() and 1 <= int(args[0]) <= total:
            return [all_accounts[int(args[0]) - 1]]
        print(f"Argumen nggak dikenal: {' '.join(args)} — balik ke menu interaktif.")

    print(f"\nAda {total} akun di sessions.txt (Akun 1-{total}, sesuai urutan baris).")
    print("Mau jalanin yang mana?")
    print("  1) 1 akun saja")
    print("  2) Semua akun")
    print("  3) Dari akun X sampai akhir")
    try:
        choice = input("Pilih 1/2/3: ").strip()
    except EOFError:
        print("(nggak ada input — jalanin semua akun)")
        return all_accounts
    if choice == "1":
        n = _ask_number(f"    Nomor akun (1-{total}): ", 1, total)
        return [all_accounts[n - 1]]
    if choice == "3":
        n = _ask_number(f"    Mulai dari akun nomor (1-{total}): ", 1, total)
        return all_accounts[n - 1:]
    if choice != "2":
        print("    (pilihan nggak dikenal — jalanin semua akun)")
    return all_accounts

async def main():
    with open("sessions.txt") as f:
        sessions = [s.strip() for s in f.readlines() if s.strip()]
    if not sessions:
        print("sessions.txt kosong — isi dulu, 1 session string per baris.")
        return
    selected = pick_accounts(sessions)
    print(f"\nJalanin {len(selected)} akun: " + ", ".join(f"Akun {i}" for i, _ in selected))
    for pos, (i, session) in enumerate(selected):
        await run(session, i)
        if pos < len(selected) - 1:
            await asyncio.sleep(DELAY_BETWEEN_ACCOUNTS)

if __name__ == "__main__":
    asyncio.run(main())
