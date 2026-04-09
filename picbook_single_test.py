import asyncio
import websockets
import json
import hashlib
import time
import base64
import os
import uuid
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# ================= 路径与环境准备 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "绘本图片")
LOG_DIR = os.path.join(BASE_DIR, "log")
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)

def cleanup_old_logs():
    """清理超过 24 小时的日志，需用户确认"""
    if not os.path.exists(LOG_DIR): return
    now = time.time()
    old_files = []
    for f in os.listdir(LOG_DIR):
        fpath = os.path.join(LOG_DIR, f)
        if os.path.isfile(fpath):
            if now - os.path.getmtime(fpath) > 86400: # 24小时
                old_files.append(fpath)
    
    if old_files:
        print(f"\n[System] 发现 {len(old_files)} 个超过 24 小时的旧日志文件。")
        choice = input("是否执行清理？(y/n): ").strip().lower()
        if choice == 'y':
            for f in old_files:
                try: os.remove(f)
                except: pass
            print("[System] 旧日志已清理完毕。\n")
        else:
            print("[System] 已跳过清理。\n")

def find_images():
    if not os.path.exists(IMAGE_DIR): return None, []
    all_f = sorted([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    cvs = [f for f in all_f if "封面" in f]
    cc = os.path.join(IMAGE_DIR, cvs[0]) if cvs else None
    ins = [os.path.join(IMAGE_DIR, f) for f in all_f if "封面" not in f]
    return cc, ins

COVER_IMAGE, INNER_IMAGES = find_images()

# ================= 配置信息 =================
API_KEY = "67772b333e2645b684c51a9fc4ba2595"
SECRET = "85x6099I6Ql7122S"
DEVICE_ID = "testdevice000001"
WS_URL = "wss://ws-api.turingapi.com/api/v2"
CAMERA_ID = 796
SKILL_CODE = 1000056

# ================= 工具函数 =================
def get_display_width(s): return sum(2 if ord(c) > 127 else 1 for c in str(s))
def truncate_text(text, max_w):
    if get_display_width(text) <= max_w: return text
    w, res = 0, ""
    for c in text:
        cw = 2 if ord(c) > 127 else 1
        if w + cw + 3 > max_w: res += "..."; break
        res += c; w += cw
    return res
def pad_text(text, width): return str(text) + " " * max(0, width - get_display_width(text))

class PicBookTester:
    def __init__(self):
        self.results = []
        self.seq = 1

    def save_transaction_log(self, name, label, req_init, req_finish, resps):
        fname = f"{self.seq:02d}_{label}_{os.path.splitext(name)[0]}_{int(time.time())}.txt"
        fpath = os.path.join(LOG_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"=== [TX LOG] {label} | {name} ===\n\n")
            f.write("--- 1. INIT REQUEST ---\n")
            f.write(json.dumps(req_init, ensure_ascii=False, indent=2) + "\n\n")
            f.write("--- 2. FINISH REQUEST ---\n")
            f.write(json.dumps(req_finish, ensure_ascii=False, indent=2) + "\n\n")
            f.write("--- 3. ALL RESPONSES ---\n")
            for i, r in enumerate(resps):
                f.write(f"\n[Response {i+1}]\n")
                f.write(json.dumps(r, ensure_ascii=False, indent=2) + "\n")
        self.seq += 1

    async def upload_recognition(self, ws, image_path, book_id=None, label=""):
        if not image_path or not os.path.exists(image_path): return None
        file_uuid = str(uuid.uuid4()).replace("-", "")
        img_flag = str(uuid.uuid4()).replace("-", "")
        ts = int(time.time() * 1000)
        key, iv = get_MD5_key_iv(ts)
        init_req = {
            "deviceId": DEVICE_ID, "requestType": [1, 2],
            "nlpRequest": {
                "content": [{"data": file_uuid, "type": 1}],
                "clientInfo": {
                    "appState": {"code": SKILL_CODE, "operateState": 1100},
                    "robotSkill": {
                        str(SKILL_CODE): {
                            "imgFlagId": img_flag, "innerUrlFlag": 1, "debug": 0, "cameraId": CAMERA_ID, 
                            "type": 5, "typeFlag": 6, "textFlag": 1, "accessModel": 1, "modelOrder": 2, 
                            "showZhEnData": True, "showSimilar": True, "languageOrder": 1
                        }
                    }
                }
            },
            "binarysState": { "openBinarysId": file_uuid }
        }
        if book_id: init_req["nlpRequest"]["clientInfo"]["robotSkill"][str(SKILL_CODE)]["bookId"] = book_id

        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": encrypt_data(init_req, key, iv)}))
        with open(image_path, "rb") as f: await ws.send(f.read())
        finish_req = {"binarysState": {"completeBinarysId": file_uuid}}
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": encrypt_data(finish_req, key, iv)}))
        t_last = time.time()
        t_fr, t_200, t_tts, res_id, all_resps = None, None, None, None, []
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=12)
                t_now = time.time()
                if t_fr is None: t_fr = t_now
                data = json.loads(msg)
                if "data" in data:
                    dec = decrypt_data(data["data"], key, iv)
                    data.update(dec)
                all_resps.append(data)
                if "nlpResponse" in data:
                    p = data["nlpResponse"].get("intent", {}).get("parameters", {})
                    if "bookId" in p: res_id = p["bookId"]
                    elif "titleData" in p: res_id = p["titleData"].get("bookId")
                    elif "innerData" in p: res_id = p["innerData"].get("bookId")
                    if data.get("code") == 200 and t_200 is None: t_200 = t_now
                    if any(r.get("values", {}).get("ttsUrl") for r in data["nlpResponse"].get("results", [])) and t_tts is None:
                        t_tts = t_now
                if data.get("done") is True: break
            except: break

        m = {"name": os.path.basename(image_path), "resp": 0, "asr": 0, "tts": 0, "total": 0}
        if t_fr:
            m["resp"] = round(t_fr - t_last, 2)
            if t_200:
                m["asr"] = round(t_200 - t_fr, 2)
                if t_tts: m["tts"] = round(t_tts - t_200, 2)
            m["total"] = round(m["resp"] + m["asr"] + m["tts"], 2)
        self.results.append(m)
        self.save_transaction_log(os.path.basename(image_path), label, init_req, finish_req, all_resps)
        return res_id

    def print_summary(self):
        if not self.results: return
        print("\n[ 详 细 分 条 结 果 ]")
        border = "╟" + "─" * 6 + "╫" + "─" * 32 + "╫" + "─" * 12 + "╫" + "─" * 14 + "╫" + "─" * 18 + "╫" + "─" * 10 + "╢"
        print(border.replace("╟", "╔").replace("╫", "╦").replace("╢", "╗").replace("─", "═"))
        print(f"║ {pad_text('序号', 4)} ║ {pad_text('图片样本', 30)} ║ {pad_text('FirstResp', 10)} ║ {pad_text('识别时间(识)', 12)} ║ {pad_text('音频返回时间(音)', 16)} ║ {pad_text('Total', 8)} ║")
        print(border)
        for i, r in enumerate(self.results):
            name = truncate_text(r['name'], 30)
            print(f"║ {pad_text(i+1, 4)} ║ {pad_text(name, 30)} ║ {pad_text(r['resp'], 10)} ║ {pad_text(r['asr'], 12)} ║ {pad_text(r['tts'], 16)} ║ {pad_text(r['total'], 8)} ║")
        print(border.replace("╟", "╚").replace("╫", "╩").replace("╢", "╝").replace("─", "═"))

    async def run_test(self):
        cleanup_old_logs() # 运行前清理
        if not COVER_IMAGE: return
        try:
            async with websockets.connect(WS_URL) as ws:
                bid = await self.upload_recognition(ws, COVER_IMAGE, label="COVER")
                if bid and INNER_IMAGES:
                    await asyncio.sleep(1)
                    await self.upload_recognition(ws, INNER_IMAGES[0], book_id=bid, label="INNER")
        finally:
            self.print_summary()

def get_MD5_key_iv(ts):
    raw = API_KEY + SECRET + str(ts)
    m = hashlib.md5(raw.encode('utf-8')).hexdigest()
    k = m[8:24].encode('utf-8')
    return k, k
def encrypt_data(d, k, v):
    s = json.dumps(d, ensure_ascii=False)
    cipher = AES.new(k, AES.MODE_CBC, v)
    return base64.b64encode(cipher.encrypt(pad(s.encode('utf-8'), 16))).decode('utf-8')
def decrypt_data(e, k, v):
    try:
        cipher = AES.new(k, AES.MODE_CBC, v)
        return json.loads(unpad(cipher.decrypt(base64.b64decode(e)), 16).decode('utf-8'))
    except: return {}

if __name__ == "__main__":
    asyncio.run(PicBookTester().run_test())
