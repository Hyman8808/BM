import requests
import json
import time
import os
import uuid
import binascii
import argparse
import sys
from Crypto.Cipher import AES

# ================= 路径与环境准备 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "绘本图片")
LOG_DIR = os.path.join(BASE_DIR, "log_http_single")
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)

def cleanup_old_logs():
    now = time.time()
    old_logs = [os.path.join(LOG_DIR, fl) for fl in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, fl)) and now - os.path.getmtime(os.path.join(LOG_DIR, fl)) > 86400]
    if old_logs:
        print(f"\n[System] 单条测试也发现 {len(old_logs)} 个过期 HTTP 日志。是否清理？(y/n): ")
        if input().strip().lower() == 'y':
            for f in old_logs: os.remove(f)

def find_images():
    if not os.path.exists(IMAGE_DIR): return None, None
    all_f = sorted([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    cvs = [f for f in all_f if "封面" in f]
    ins = [os.path.join(IMAGE_DIR, f) for f in all_f if "封面" not in f]
    return (os.path.join(IMAGE_DIR, cvs[0]) if cvs else None), (ins[0] if ins else None)

COVER_IMAGE, INNER_IMAGE = find_images()

# ================= 配置与参数处理 =================
def load_config():
    config_path = os.path.join(BASE_DIR, "config_http.json")
    cfg = {
        "API_KEY": "67772b333e2645b684c51a9fc4ba2595",
        "SECRET": "85x6099I6Ql7122S",
        "RAW_DEVICE_ID": "ai11223344556677",
        "HTTP_URL": "http://iot.turingos.cn/mmui/picbook",
        "CAMERA_ID": 796,
        "SKILL_CODE": 1000056
    }
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    
    parser = argparse.ArgumentParser(description="Turing HTTP Picbook Test")
    parser.add_argument("--ak", help="API Key")
    parser.add_argument("--secret", help="Secret Key")
    parser.add_argument("--uid", help="Device ID (Raw)")
    parser.add_argument("--url", help="HTTP URL")
    args, unknown = parser.parse_known_args()

    if args.ak: cfg["API_KEY"] = args.ak
    if args.secret: cfg["SECRET"] = args.secret
    if args.uid: cfg["RAW_DEVICE_ID"] = args.uid
    if args.url: cfg["HTTP_URL"] = args.url
    return cfg

CONFIG = load_config()
API_KEY = CONFIG["API_KEY"]
SECRET = CONFIG["SECRET"]
RAW_DEVICE_ID = CONFIG["RAW_DEVICE_ID"]
HTTP_URL = CONFIG["HTTP_URL"]
CAMERA_ID = CONFIG["CAMERA_ID"]
SKILL_CODE = CONFIG["SKILL_CODE"]

def generate_aiwifi_uid(api_key, secret, raw_deviceId):
    key = secret.encode('utf-8')
    iv = api_key[:16].encode('utf-8')
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(raw_deviceId.encode('utf-8'))
    return encrypted.hex().upper()

DEVICE_ID = generate_aiwifi_uid(API_KEY, SECRET, RAW_DEVICE_ID)

def get_display_width(s): return sum(2 if ord(c) > 127 else 1 for c in str(s))
def truncate_text(text, max_w):
    if get_display_width(text) <= max_w: return text
    curr_w, res = 0, ""
    for char in text:
        w = 2 if ord(char) > 127 else 1
        if curr_w + w + 3 > max_w:
            res += "..."; break
        res += char; curr_w += w
    return res
def pad_text(text, width): return str(text) + " " * max(0, width - get_display_width(text))

class HttpPicBookSingleTester:
    def __init__(self):
        self.results = []
        self.seq = 1

    def save_tx_log(self, name, label, req_params, resp_data):
        fname = f"{self.seq:03d}_{label}_{os.path.splitext(name)[0]}.txt"
        fpath = os.path.join(LOG_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"HTTP URL: {HTTP_URL}\n")
            f.write(f"REQ PARAMS:\n{json.dumps(req_params, indent=2, ensure_ascii=False)}\n\n")
            f.write(f"HTTP RESPONSE:\n{json.dumps(resp_data, indent=2, ensure_ascii=False)}\n")
        return fpath

    def run_test(self):
        cleanup_old_logs()
        if not COVER_IMAGE:
            print("[错误] 未找到封面文件进行初始化！")
            return
            
        print(f"\n[开始] 基于 HTTP 协议的绘本单步测试")
        bid, cm = self.upload_process(COVER_IMAGE, label="COVER")
        if cm: self.results.append(cm)
        if not bid:
            print("[结束] 封面认证失败，bookId 获取失败。")
            self.print_summary()
            return

        if INNER_IMAGE:
            _, im = self.upload_process(INNER_IMAGE, book_id=bid, label="INNER_SINGLE")
            if im: self.results.append(im)
            
        self.print_summary()

    def upload_process(self, filepath, book_id=None, label=""):
        req_params = {
            "ak": API_KEY,
            "uid": DEVICE_ID,
            "token": "", # AI-WIFI 模式首单 Token 置空
            "type": 4, 
            "flag": 2,
            "extra": {
                "imgFlagId": str(uuid.uuid4()).replace("-", ""),
                "innerUrlFlag": 1, 
                "debug": 1, # 开启 debug 显示原图地址和处理图地址
                "cameraId": CAMERA_ID, 
                "type": 5, 
                "typeFlag": 6, 
                "textFlag": 1, 
                "accessModel": 1, 
                "modelOrder": 2, 
                "showZhEnData": True, 
                "showSimilar": True, 
                "languageOrder": 1
            }
        }
        if book_id: req_params["extra"]["bookId"] = book_id

        print(f"[{label}] 正在发起单次 HTTP POST 截屏处理: {os.path.basename(filepath)}")
        t0 = time.time()
        
        try:
            with open(filepath, "rb") as f:
                files = {'speech': (os.path.basename(filepath), f, 'application/octet-stream')}
                data = {'parameters': json.dumps(req_params, ensure_ascii=False)}
                resp = requests.post(HTTP_URL, data=data, files=files, timeout=20)
                resp_json = resp.json()
        except Exception as e:
            resp_json = {"error": str(e)}

        t_fr = time.time()
        total_time = t_fr - t0
        
        res_id, tts_url = None, "N/A"
        if "func" in resp_json:
            func = resp_json["func"]
            if "titleData" in func and "bookId" in func["titleData"]: res_id = func["titleData"]["bookId"]
            elif "innerData" in func and "bookId" in func["innerData"]: res_id = func["innerData"]["bookId"]
        if resp_json.get("nlp") and isinstance(resp_json["nlp"], list): tts_url = resp_json["nlp"][0]
        elif resp_json.get("tts"): tts_url = resp_json["tts"]

        log_path = self.save_tx_log(os.path.basename(filepath), label, req_params, resp_json)
        self.seq += 1
        
        print(f" -> {"封面 OK (bookId获取成功)" if res_id and not book_id else "内页解析 OK" if res_id else "失败"}")

        return res_id, {
            "name": os.path.basename(filepath),
            "resp": round(total_time, 4),
            "asr": 0.0,
            "tts": 0.0,
            "total": round(total_time, 4),
            "log": log_path
        }

    def print_summary(self):
        if not self.results: return
        print("\n[ HTTP 单条 详 细 分 条 结 果 ]")
        border = "╟" + "─" * 6 + "╫" + "─" * 32 + "╫" + "─" * 12 + "╫" + "─" * 14 + "╫" + "─" * 18 + "╫" + "─" * 10 + "╢"
        print(border.replace("╟", "╔").replace("╫", "╦").replace("╢", "╗").replace("─", "═"))
        print(f"║ {pad_text('序号', 4)} ║ {pad_text('图片样本', 30)} ║ {pad_text('FirstResp', 10)} ║ {pad_text('识别时间(识)', 12)} ║ {pad_text('音频返回时间(音)', 16)} ║ {pad_text('Total', 8)} ║")
        print(border)
        for i, r in enumerate(self.results):
            name = truncate_text(r['name'], 30)
            print(f"║ {pad_text(i+1, 4)} ║ {pad_text(name, 30)} ║ {pad_text(r['resp'], 10)} ║ {pad_text(r['asr'], 12)} ║ {pad_text(r['tts'], 16)} ║ {pad_text(r['total'], 8)} ║")
        print(border.replace("╟", "╚").replace("╫", "╩").replace("╢", "╝").replace("─", "═"))

if __name__ == "__main__":
    tester = HttpPicBookSingleTester()
    tester.run_test()
