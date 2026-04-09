import asyncio
import websockets
import json
import time
import os
import uuid
import argparse
import sys

# ================= 路径与环境准备 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "指尖查词图片")
LOG_DIR = os.path.join(BASE_DIR, "log_fingertip")
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)

# ================= 配置与参数处理 =================
def load_config():
    config_path = os.path.join(BASE_DIR, "config_fingertip.json")
    cfg = {
        "API_KEY": "42fb064c66034807bbc7cd5e797e901d",
        "SECRET": "Q5FJi32fvrMWL56o",
        "DEVICE_ID": "testdevice000001",
        "WS_URL": "wss://ws-api.turingapi.com/api/v2",
        "CAMERA_ID": 1710,
        "SKILL_CODE": 1000634
    }
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    
    parser = argparse.ArgumentParser(description="Turing Fingertip Single Test")
    parser.add_argument("--ak", help="API Key")
    parser.add_argument("--secret", help="Secret Key")
    parser.add_argument("--uid", help="Device ID")
    parser.add_argument("--url", help="WebSocket URL")
    args, unknown = parser.parse_known_args()

    if args.ak: cfg["API_KEY"] = args.ak
    if args.secret: cfg["SECRET"] = args.secret
    if args.uid: cfg["DEVICE_ID"] = args.uid
    if args.url: cfg["WS_URL"] = args.url
    return cfg

CONFIG = load_config()
API_KEY = CONFIG["API_KEY"]
SECRET = CONFIG["SECRET"]
DEVICE_ID = CONFIG["DEVICE_ID"]
WS_URL = CONFIG["WS_URL"]
CAMERA_ID = CONFIG["CAMERA_ID"]
SKILL_CODE = CONFIG["SKILL_CODE"]

# ================= 工具函数 =================
def pad_text(text, width):
    s = str(text)
    w = sum(2 if ord(c) > 127 else 1 for c in s)
    return s + " " * max(0, width - w)

class FingertipTester:
    def __init__(self):
        self.results = []
        self.seq = 1

    async def upload_recognition(self, ws, image_path, label=""):
        if not image_path or not os.path.exists(image_path): 
            print(f"文件不存在: {image_path}")
            return
            
        file_uuid = str(uuid.uuid4()).replace("-", "")
        ts = int(time.time() * 1000)
        
        # 指尖查词协议: OpenSocket 模式，通常第一步是检测指尖 (1100)，第二步是裁切识别 (2100)
        # 这里的测试 demo 采用直接请求识别 (2100) 的逻辑，假设图片是已经准备好的裁切图或指尖明显的图
        init_req = {
            "deviceId": DEVICE_ID,
            "requestType": [1, 2],
            "nlpRequest": {
                "content": [{"data": file_uuid, "type": 1}],
                "clientInfo": {
                    "appState": {"code": SKILL_CODE, "operateState": 2100},
                    "robotSkill": {
                        str(SKILL_CODE): {
                            "cameraId": CAMERA_ID,
                            "zoomScale": 1.0  # 裁切图比例设为 1
                        }
                    }
                }
            },
            "binarysState": { "openBinarysId": file_uuid }
        }

        # 发送初始化
        await ws.send(json.dumps({
            "key": API_KEY,
            "timestamp": str(ts),
            "data": init_req
        }))

        # 发送图片数据 (分片发送)
        with open(image_path, "rb") as f:
            content = f.read()
            chunk_size = 8000
            for i in range(0, len(content), chunk_size):
                await ws.send(content[i:i+chunk_size])

        # 发送结束包
        finish_req = {"binarysState": {"completeBinarysId": file_uuid}}
        await ws.send(json.dumps({
            "key": API_KEY,
            "timestamp": str(ts),
            "data": finish_req
        }))

        t_start = time.time()
        all_resps = []
        final_result = "N/A"
        t_first = None

        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                if t_first is None: t_first = time.time()
                data = json.loads(msg)
                all_resps.append(data)
                
                # 解析识别结果
                if "nlpResponse" in data:
                    intent = data["nlpResponse"].get("intent", {})
                    params = intent.get("parameters", {})
                    if "content" in params:
                        final_result = params["content"]
                    elif "ocrRes" in params:
                        ocr = params["ocrRes"].get("content", [])
                        if ocr: final_result = "|".join(ocr)
                
                if data.get("done") is True:
                    break
            except Exception as e:
                # print(f"接收超时或错误: {e}")
                break

        # 保存日志
        log_name = f"fingertip_{self.seq:02d}_{os.path.basename(image_path)}.json"
        with open(os.path.join(LOG_DIR, log_name), "w", encoding="utf-8") as lf:
            json.dump(all_resps, lf, ensure_ascii=False, indent=2)

        duration = round(t_first - t_start, 3) if t_first else 0
        total_time = round(time.time() - t_start, 3)

        print(f"| {pad_text(os.path.basename(image_path), 30)} | {pad_text(duration, 12)} | {pad_text(final_result, 30)} |")
        
        self.seq += 1
        return all_resps

async def main():
    tester = FingertipTester()
    print("\n" + "="*80)
    print(f"| {pad_text('测试图片', 30)} | {pad_text('首包用时(s)', 12)} | {pad_text('识别结果 (OCR/Result)', 30)} |")
    print("-" * 80)
    
    images = [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    if not images:
        print("指尖查词图片目录下没有图片。")
        return

    async with websockets.connect(WS_URL) as ws:
        # 这里演示测试第一张图片
        image_to_test = os.path.join(IMAGE_DIR, images[0])
        await tester.upload_recognition(ws, image_to_test)

    print("="*80 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
