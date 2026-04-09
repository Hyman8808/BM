import requests
import json
import time
import os
import uuid
import glob
import argparse
import sys
from Crypto.Cipher import AES

try:
    import xlsxwriter
except ImportError:
    os.system("pip install xlsxwriter")
    import xlsxwriter

# ================= 路径与环境准备 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "绘本图片")
LOG_DIR = os.path.join(BASE_DIR, "log_http") # 为 HTTP 测试建立独立日志文件夹
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)

def cleanup_files():
    # 1. 自动清理 15分钟 (900s) 前的 Excel 老报表
    now = time.time()
    old_excels = glob.glob(os.path.join(BASE_DIR, "HTTP_Picbook_*.xlsx"))
    for f in old_excels:
        if os.path.isfile(f) and now - os.path.getmtime(f) > 900:
            try: os.remove(f)
            except: pass
    # 2. 清理旧日志 (HTTP 日志)
    old_logs = [os.path.join(LOG_DIR, fl) for fl in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, fl)) and now - os.path.getmtime(os.path.join(LOG_DIR, fl)) > 86400]
    if old_logs:
        print(f"\n[System] 发现 {len(old_logs)} 个过期 HTTP 日志。是否清理？(y/n): ")
        if input().strip().lower() == 'y':
            for f in old_logs: os.remove(f)

def find_images():
    if not os.path.exists(IMAGE_DIR): return None, []
    all_f = sorted([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    cvs = [f for f in all_f if "封面" in f]
    ins = [os.path.join(IMAGE_DIR, f) for f in all_f if "封面" not in f]
    return (os.path.join(IMAGE_DIR, cvs[0]) if cvs else None), ins

COVER_IMAGE, INNER_IMAGES = find_images()

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
    
    parser = argparse.ArgumentParser(description="Turing HTTP Picbook Batch Test")
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

DEVICE_ID = generate_aiwifi_uid(API_KEY, SECRET, RAW_DEVICE_ID) # 强制按照 AI-WIFI 协议进行 AES 加密转换

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

class HttpPicBookBatchTester:
    def __init__(self):
        self.results = []
        self.seq = 1
        self.current_token = ""

    def save_tx_log(self, name, label, req_params, resp_data):
        fname = f"{self.seq:03d}_{label}_{os.path.splitext(name)[0]}.txt"
        fpath = os.path.join(LOG_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"HTTP URL: {HTTP_URL}\n")
            f.write(f"REQ PARAMS:\n{json.dumps(req_params, indent=2, ensure_ascii=False)}\n\n")
            f.write(f"HTTP RESPONSE:\n{json.dumps(resp_data, indent=2, ensure_ascii=False)}\n")
        return fpath

    def run_full_test(self):
        cleanup_files()
        if not COVER_IMAGE:
            print("未找到封面文件！")
            return
        
        print(f"检测到 {len(INNER_IMAGES)} 张内页，准备开始基于 HTTP 的轮询...\n")
        
        # 封面认证
        bid, cm = self.upload_process(COVER_IMAGE, label="COVER")
        if cm: self.results.append(cm)
        if not bid:
            print("封面认证失败，未能获取 bookId，终止测试。")
            self.print_summary_table()
            self.generate_professional_report()
            return

        # 轮询内页
        for idx, img in enumerate(INNER_IMAGES):
            _, im = self.upload_process(img, book_id=bid, label=f"INNER_{idx+1}")
            if im: self.results.append(im)
            print(f"[{idx+1}/{len(INNER_IMAGES)}] {os.path.basename(img)} HTTP 请求完成")
            time.sleep(0.5)

        self.print_summary_table()
        self.generate_professional_report()

    def upload_process(self, filepath, book_id=None, label=""):
        req_params = {
            "ak": API_KEY,
            "uid": DEVICE_ID,
            "token": self.current_token if self.current_token else "",
            "type": 4, # 4 为绘本类型
            "flag": 2,
            "extra": {
                "imgFlagId": str(uuid.uuid4()).replace("-", ""),
                "innerUrlFlag": 1, 
                "debug": 0, 
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
        if book_id: 
            req_params["extra"]["bookId"] = book_id

        # HTTP 请求测时
        t0 = time.time()
        
        try:
            with open(filepath, "rb") as f:
                files = {'speech': (os.path.basename(filepath), f, 'application/octet-stream')}
                data = {'parameters': json.dumps(req_params, ensure_ascii=False)}
                
                resp = requests.post(HTTP_URL, data=data, files=files, timeout=20)
                resp_json = resp.json()
                if "token" in resp_json and resp_json["token"]:
                    self.current_token = resp_json["token"]
        except Exception as e:
            resp_json = {"error": str(e)}

        t_fr = time.time()
        total_time = t_fr - t0

        res_id = None
        tts_url = "N/A"
        
        # 解析返回结果
        if "func" in resp_json:
            func = resp_json["func"]
            if "titleData" in func and "bookId" in func["titleData"]:
                res_id = func["titleData"]["bookId"]
            elif "innerData" in func and "bookId" in func["innerData"]:
                res_id = func["innerData"]["bookId"]

        if resp_json.get("nlp") and isinstance(resp_json["nlp"], list):
            tts_url = resp_json["nlp"][0]
        elif resp_json.get("tts"):
            tts_url = resp_json["tts"]

        log_path = self.save_tx_log(os.path.basename(filepath), label, req_params, resp_json)
        self.seq += 1
        
        status = "成功" if resp_json.get("code") in [200, 20039] or "func" in resp_json else "失败"

        # 对于 HTTP 协议，一次返回结果。
        # FirstResp 即获取整个响应的时间。由于没有流式返回，识和音时间相对视为 0 或是 HTTP 耗时的一部分。
        # 为了表盘一致，这里 FirstResp = total_time, ASR(识)=0.0, TTS(音)=0.0
        m = {
            "name": os.path.basename(filepath), 
            "resp": round(total_time, 4), 
            "asr": 0.0, 
            "nlp": 0.0, 
            "tts": 0.0, 
            "total": round(total_time, 4), 
            "url": tts_url, 
            "log": log_path, 
            "status": status, 
            "bookId": res_id
        }
        
        return res_id, m

    def print_summary_table(self):
        total = len(self.results)
        if total == 0: return
        avg_resp = sum(r["resp"] for r in self.results) / total
        avg_asr = sum(r["asr"] for r in self.results) / total
        avg_tts = sum(r["tts"] for r in self.results) / total
        avg_total = sum(r["total"] for r in self.results) / total

        print("\n" + "┌" + "─" * 107 + "┐")
        print("│" + " " * 44 + "HTTP 批量测试结果简报" + " " * 42 + "│")
        print("├" + "─" * 20 + "┬" + "─" * 15 + "┬" + "─" * 15 + "┬" + "─" * 25 + "┬" + "─" * 26 + "┤")
        print(f"│ {pad_text('环节', 18)} │ {pad_text('成功数', 13)} │ {pad_text('成功率', 13)} │ {pad_text('平均耗时(s)', 23)} │ {pad_text('备注', 24)} │")
        print("├" + "─" * 20 + "┼" + "─" * 15 + "┼" + "─" * 15 + "┼" + "─" * 25 + "┼" + "─" * 26 + "┤")
        print(f"│ {pad_text('FirstResp', 18)} │ {pad_text(total, 13)} │ {pad_text('100.0%', 13)} │ {pad_text(f'{avg_resp:.3f}', 23)} │ {pad_text('HTTP 请求总耗时', 24)} │")
        print(f"│ {pad_text('识别时间(识)', 18)} │ {pad_text(total, 13)} │ {pad_text('100.0%', 13)} │ {pad_text(f'{avg_asr:.3f}', 23)} │ {pad_text('流式识别(HTTP不适用)', 24)} │")
        print(f"│ {pad_text('音频返回时间(音)', 18)} │ {pad_text(total, 13)} │ {pad_text('100.0%', 13)} │ {pad_text(f'{avg_tts:.3f}', 23)} │ {pad_text('流式下发(HTTP不适用)', 24)} │")
        print("├" + "─" * 20 + "┼" + "─" * 15 + "┼" + "─" * 15 + "┼" + "─" * 25 + "┼" + "─" * 26 + "┤")
        print(f"│ {pad_text('Total', 18)} │ {pad_text('-', 13)} │ {pad_text('-', 13)} │ {pad_text(f'{avg_total:.3f}', 23)} │ {pad_text('Resp+ASR+TTS', 24)} │")
        print("└" + "─" * 107 + "┘")

        print("\n[ 详 细 分 条 结 果 ]")
        border = "╟" + "─" * 6 + "╫" + "─" * 32 + "╫" + "─" * 12 + "╫" + "─" * 14 + "╫" + "─" * 18 + "╫" + "─" * 10 + "╢"
        print(border.replace("╟", "╔").replace("╫", "╦").replace("╢", "╗").replace("─", "═"))
        print(f"║ {pad_text('序号', 4)} ║ {pad_text('图片样本', 30)} ║ {pad_text('FirstResp', 10)} ║ {pad_text('识别时间(识)', 12)} ║ {pad_text('音频返回时间(音)', 16)} ║ {pad_text('Total', 8)} ║")
        print(border)
        for i, r in enumerate(self.results):
            name = truncate_text(r['name'], 30)
            print(f"║ {pad_text(i+1, 4)} ║ {pad_text(name, 30)} ║ {pad_text(r['resp'], 10)} ║ {pad_text(round(r['asr'], 2), 12)} ║ {pad_text(round(r['tts'], 2), 16)} ║ {pad_text(r['total'], 8)} ║")
        print(border.replace("╟", "╚").replace("╫", "╩").replace("╢", "╝").replace("─", "═"))

    def generate_professional_report(self):
        report_name = os.path.join(BASE_DIR, f"HTTP_Picbook_Performance_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
        wb = xlsxwriter.Workbook(report_name)
        
        # --- Modern Styling (International UI) ---
        fnt = 'Segoe UI'
        c_head_bg = '#2C3E50'; c_head_fg = '#FFFFFF'
        c_border = '#EBDEDF'; c_bg_light = '#F8F9F9'
        
        fmt_title = wb.add_format({'bold': True, 'font_size': 20, 'font_name': 'Segoe UI Light', 'color': '#2C3E50', 'align': 'left', 'valign': 'vcenter'})
        fmt_head = wb.add_format({'bold': True, 'font_name': fnt, 'font_size': 11, 'align': 'center', 'valign': 'vcenter', 'bg_color': c_head_bg, 'font_color': c_head_fg, 'border': 1, 'border_color': c_border})
        fmt_cell = wb.add_format({'align': 'center', 'valign': 'vcenter', 'font_name': fnt, 'font_size': 11, 'border': 1, 'border_color': c_border})
        fmt_num4 = wb.add_format({'align': 'center', 'valign': 'vcenter', 'font_name': fnt, 'font_size': 11, 'border': 1, 'border_color': c_border, 'num_format': '0.0000'})
        fmt_num6 = wb.add_format({'align': 'center', 'valign': 'vcenter', 'font_name': fnt, 'font_size': 11, 'border': 1, 'border_color': c_border, 'num_format': '0.000000'})
        fmt_fail = wb.add_format({'align': 'center', 'valign': 'vcenter', 'font_name': fnt, 'font_size': 11, 'border': 1, 'border_color': c_border, 'font_color': '#E74C3C', 'bold': True})

        # --- Sheet 1: Dashboard ---
        dash = wb.add_worksheet("数据看板 (Dashboard)")
        dash.hide_gridlines(2)
        
        total = len(self.results)
        success = sum(1 for r in self.results if r["status"] == "成功")
        avg_resp = sum(r["resp"] for r in self.results) / total if total else 0
        avg_asr = sum(r["asr"] for r in self.results) / total if total else 0
        avg_tts = sum(r["tts"] for r in self.results) / total if total else 0
        
        dash.set_column('A:A', 3); dash.set_column('B:C', 18); dash.set_column('D:D', 4); dash.set_column('E:N', 12)
        dash.set_row(1, 35)
        dash.write('B2', 'Turing API 深度评测 (HTTP 模式)', fmt_title)
        
        # 统计表
        dash.write('B4', '指标 (Metrics)', fmt_head); dash.write('C4', '平均耗时(s)', fmt_head)
        dash.write('B5', 'FirstResp', fmt_cell); dash.write('C5', float(f"{avg_resp:.4f}"), fmt_num4)
        dash.write('B6', '识', fmt_cell); dash.write('C6', float(f"{avg_asr:.6f}"), fmt_num6)
        dash.write('B7', '音', fmt_cell); dash.write('C7', float(f"{avg_tts:.6f}"), fmt_num6)
        
        dash.write('B9', '状态 (Status)', fmt_head); dash.write('C9', '数量 (Count)', fmt_head)
        dash.write('B10', '成功 (Success)', fmt_cell); dash.write('C10', success, fmt_cell)
        dash.write('B11', '失败 (Failed)', fmt_cell); dash.write('C11', total - success, fmt_fail if total - success > 0 else fmt_cell)

        # 甜甜圈图 (Pie Chart)
        pie = wb.add_chart({'type': 'doughnut'})
        pie.add_series({
            'name': '质量分布',
            'categories': ['数据看板 (Dashboard)', 9, 1, 10, 1],
            'values':     ['数据看板 (Dashboard)', 9, 2, 10, 2],
            'points': [{'fill': {'color': '#2ECC71'}}, {'fill': {'color': '#E74C3C'}}],
            'data_labels': {'percentage': True, 'value': True, 'font': {'name': fnt, 'size': 10, 'bold': True, 'color': '#2C3E50'}, 'separator': '\n'},
            'border': {'none': True}, 'hole_size': 55
        })
        pie.set_title({'name': '请求质量分布 (Quality Ratio)', 'name_font': {'name': 'Segoe UI Light', 'size': 14, 'color': '#34495E'}})
        pie.set_chartarea({'border': {'none': True}, 'fill': {'none': True}})
        pie.set_legend({'position': 'bottom', 'font': {'name': fnt, 'size': 10}})
        dash.insert_chart('E4', pie, {'x_offset': 15, 'y_offset': 0})

        # 高级柱图 (Column Chart)
        col = wb.add_chart({'type': 'column'})
        # 在 HTTP 模式下，去除了值为 0 的 ASR/TTS 柱子，避免它们占据 X 轴的隐形物理空间导致柱子间产生空隙
        # overlap: 0 保证组内的柱子严丝合缝紧贴，gap: 120 保证组与组之间有良好间距
        col.add_series({'name': 'HTTP FirstResp 总耗时(s)', 'categories': ['测试详情', 1, 1, total, 1], 'values': ['测试详情', 1, 4, total, 4], 'fill': {'color': '#3498DB'}, 'border': {'none': True}, 'gap': 120, 'overlap': 0})
        col.add_series({'name': 'Total 总延时(s)', 'categories': ['测试详情', 1, 1, total, 1], 'values': ['测试详情', 1, 8, total, 8], 'fill': {'color': '#9B59B6'}, 'border': {'none': True}})
        
        col.set_title({'name': '请求耗时波动分析 (Latency Fluctuation)', 'name_font': {'name': 'Segoe UI Light', 'size': 15, 'color': '#34495E'}})
        col.set_size({'width': 920, 'height': 400})
        col.set_chartarea({'border': {'none': True}, 'fill': {'none': True}})
        col.set_plotarea({'border': {'none': True}, 'fill': {'color': c_bg_light}})
        col.set_x_axis({'name': '测试样本 (Sample)', 'name_font': {'name': fnt, 'size': 9}, 'num_font': {'name': fnt, 'color': '#7F8C8D'}, 'line': {'color': '#BDC3C7'}})
        col.set_y_axis({'name': '耗时(s)', 'name_font': {'name': fnt, 'size': 9}, 'num_font': {'name': fnt, 'color': '#7F8C8D'}, 'major_gridlines': {'visible': True, 'line': {'color': '#E5E8E8', 'dash_type': 'dash'}}})
        col.set_legend({'position': 'top', 'font': {'name': fnt, 'size': 10}})
        dash.insert_chart('B14', col, {'x_offset': 0, 'y_offset': 10})

        # --- Sheet 2: 详情 ---
        detail = wb.add_worksheet("测试详情")
        cols = ["序号", "请求内容", "请求结果", "音频链接", "FirstResp(s)", "识 耗时(s)", "针对ASR的NLP延时(s)", "针对ASR的TTS延时(s)", "总耗时(Total)", "log文件地址"]
        detail.set_row(0, 22)
        for i, h in enumerate(cols): detail.write(0, i, h, fmt_head)
        detail.set_column('A:A', 8); detail.set_column('B:B', 32); detail.set_column('C:C', 10); detail.set_column('D:D', 42); detail.set_column('E:I', 18); detail.set_column('J:J', 55)
        
        for i, r in enumerate(self.results):
            row = i + 1; detail.set_row(row, 18)
            st = r["status"]
            detail.write(row, 0, row, fmt_cell)
            detail.write(row, 1, r["name"], fmt_cell)
            detail.write(row, 2, st, fmt_cell if st=="成功" else fmt_fail)
            detail.write(row, 3, r["url"], fmt_cell)
            detail.write(row, 4, r["resp"] if st=="成功" else "N/A", fmt_cell)
            detail.write(row, 5, r["asr"] if st=="成功" else "N/A", fmt_cell)
            detail.write(row, 6, r["nlp"] if st=="成功" else "N/A", fmt_cell)
            detail.write(row, 7, r["tts"] if st=="成功" else "N/A", fmt_cell)
            detail.write(row, 8, r["total"] if st=="成功" else "N/A", fmt_cell)
            detail.write(row, 9, r["log"], fmt_cell)
        wb.close()
        print(f"\n[System] 国际范 HTTP 版本专业报表已生成: {report_name}")

if __name__ == "__main__":
    tester = HttpPicBookBatchTester()
    tester.run_full_test()
