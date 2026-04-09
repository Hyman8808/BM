import asyncio
import websockets
import json
import time
import os
import uuid
import glob
import argparse
import sys

try:
    import xlsxwriter
except ImportError:
    os.system("pip install xlsxwriter")
    import xlsxwriter

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
    
    parser = argparse.ArgumentParser(description="Turing Fingertip Batch Test")
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

class FingertipBatchTester:
    def __init__(self):
        self.results = []
        self.seq = 1

    def save_transaction_log(self, name, all_resps):
        fname = f"TX_{self.seq:03d}_{os.path.splitext(name)[0]}.json"
        fpath = os.path.join(LOG_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(all_resps, f, ensure_ascii=False, indent=2)
        return fpath

    async def run_batch_test(self):
        print(f"\n[System] 开始指尖查词批量测试...")
        images = sorted([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        if not images:
            print("未找到测试图片。")
            return

        async with websockets.connect(WS_URL) as ws:
            for img_name in images:
                image_path = os.path.join(IMAGE_DIR, img_name)
                print(f"正在测试 [{self.seq}/{len(images)}]: {img_name} ...", end="\r")
                await self.test_single_image(ws, image_path)
                await asyncio.sleep(0.5)

        self.print_summary_table()
        self.generate_professional_report()

    async def test_single_image(self, ws, image_path):
        file_uuid = str(uuid.uuid4()).replace("-", "")
        ts = int(time.time() * 1000)
        
        init_req = {
            "deviceId": DEVICE_ID,
            "requestType": [1, 2],
            "nlpRequest": {
                "content": [{"data": file_uuid, "type": 1}],
                "clientInfo": {
                    "appState": {"code": SKILL_CODE, "operateState": 2100},
                    "robotSkill": {
                        str(SKILL_CODE): {"cameraId": CAMERA_ID, "zoomScale": 1.0}
                    }
                }
            },
            "binarysState": { "openBinarysId": file_uuid }
        }

        t_start = time.time()
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": init_req}))
        
        with open(image_path, "rb") as f:
            content = f.read()
            chunk_size = 8000
            for i in range(0, len(content), chunk_size):
                await ws.send(content[i:i+chunk_size])

        finish_req = {"binarysState": {"completeBinarysId": file_uuid}}
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": finish_req}))
        
        all_resps = []
        t_first = None
        ocr_result = "N/A"
        status = "失败"

        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                if t_first is None: t_first = time.time()
                data = json.loads(msg)
                all_resps.append(data)
                
                if "nlpResponse" in data:
                    intent = data["nlpResponse"].get("intent", {})
                    params = intent.get("parameters", {})
                    if "ocrRes" in params:
                        res = params["ocrRes"].get("content", [])
                        if res: ocr_result = "|".join(res); status = "成功"
                    if "result" in params:
                        info = params["result"].get("info", {})
                        if "word" in info: ocr_result = info["word"]; status = "成功"
                
                if data.get("done") is True: break
            except: break

        duration = round(t_first - t_start, 4) if t_first else 0
        total_time = round(time.time() - t_start, 4)
        log_path = self.save_transaction_log(os.path.basename(image_path), all_resps)

        self.results.append({
            "name": os.path.basename(image_path),
            "resp": duration,
            "total": total_time,
            "ocr": ocr_result,
            "status": status,
            "log": log_path
        })
        self.seq += 1

    def print_summary_table(self):
        print("\n" + "="*95)
        print(f"║ {pad_text('序号', 4)} ║ {pad_text('图片样本', 30)} ║ {pad_text('首包(s)', 10)} ║ {pad_text('总计(s)', 10)} ║ {pad_text('识别结果', 25)} ║")
        print("-" * 95)
        for i, r in enumerate(self.results):
            name = truncate_text(r['name'], 30)
            res = truncate_text(r['ocr'], 25)
            print(f"║ {pad_text(i+1, 4)} ║ {pad_text(name, 30)} ║ {pad_text(r['resp'], 10)} ║ {pad_text(r['total'], 10)} ║ {pad_text(res, 25)} ║")
        print("="*95 + "\n")

    def generate_professional_report(self):
        report_name = os.path.join(BASE_DIR, f"Fingertip_Performance_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
        wb = xlsxwriter.Workbook(report_name)
        fnt = 'Segoe UI'; c_head_bg = '#2C3E50'; c_head_fg = '#FFFFFF'; c_border = '#EBDEDF'
        
        fmt_title = wb.add_format({'bold': True, 'font_size': 20, 'font_name': 'Segoe UI Light', 'color': '#2C3E50'})
        fmt_head = wb.add_format({'bold': True, 'font_name': fnt, 'bg_color': c_head_bg, 'font_color': c_head_fg, 'border': 1, 'align': 'center'})
        fmt_cell = wb.add_format({'font_name': fnt, 'border': 1, 'align': 'center'})
        fmt_fail = wb.add_format({'font_name': fnt, 'border': 1, 'align': 'center', 'font_color': '#E74C3C', 'bold': True})

        dash = wb.add_worksheet("数据看板")
        dash.set_column('B:C', 20); dash.write('B2', '指尖查词 性能与质量报告', fmt_title)
        
        # 统计
        dash.write('B4', '指标', fmt_head); dash.write('C4', '值', fmt_head)
        dash.write('B5', '总测试数', fmt_cell); dash.write('C5', len(self.results), fmt_cell)
        success = sum(1 for r in self.results if r["status"] == "成功")
        dash.write('B6', '成功识别', fmt_cell); dash.write('C6', success, fmt_cell)
        avg_resp = sum(r["resp"] for r in self.results) / len(self.results) if self.results else 0
        dash.write('B7', '平均首包(s)', fmt_cell); dash.write('C7', round(avg_resp, 4), fmt_cell)

        # 详情页
        detail = wb.add_worksheet("测试详情")
        headers = ["序号", "图片名称", "状态", "首包耗时(s)", "总耗时(s)", "识别内容", "日志路径"]
        for j, h in enumerate(headers): detail.write(0, j, h, fmt_head)
        detail.set_column('B:B', 30); detail.set_column('F:F', 40); detail.set_column('G:G', 60)
        
        for i, r in enumerate(self.results):
            row = i + 1
            detail.write(row, 0, i+1, fmt_cell)
            detail.write(row, 1, r["name"], fmt_cell)
            detail.write(row, 2, r["status"], fmt_cell if r["status"]=="成功" else fmt_fail)
            detail.write(row, 3, r["resp"], fmt_cell)
            detail.write(row, 4, r["total"], fmt_cell)
            detail.write(row, 5, r["ocr"], fmt_cell)
            detail.write(row, 6, r["log"], fmt_cell)

        # 图表
        col_chart = wb.add_chart({'type': 'column'})
        col_chart.add_series({
            'name': '首包耗时(s)',
            'categories': ['测试详情', 1, 1, len(self.results), 1],
            'values': ['测试详情', 1, 3, len(self.results), 3],
            'fill': {'color': '#3498DB'}, 'gap': 120, 'overlap': 0
        })
        col_chart.set_title({'name': '请求耗时波动 (Fingertip Latency)'})
        dash.insert_chart('E4', col_chart)

        wb.close()
        print(f"[System] 专业报表已生成: {report_name}")

if __name__ == "__main__":
    asyncio.run(FingertipBatchTester().run_batch_test())
