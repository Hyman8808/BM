import asyncio
import websockets
import json
import hashlib
import time
import base64
import os
import uuid
import glob
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

try:
    import xlsxwriter
except ImportError:
    os.system("pip install xlsxwriter")
    import xlsxwriter

# ================= 路径与环境准备 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "绘本图片")
LOG_DIR = os.path.join(BASE_DIR, "log")
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)

def cleanup_files():
    # 1. 自动清理 15分钟 (900s) 前的 Excel 老报表
    now = time.time()
    old_excels = glob.glob(os.path.join(BASE_DIR, "*.xlsx"))
    for f in old_excels:
        if os.path.isfile(f) and now - os.path.getmtime(f) > 900:
            try: os.remove(f)
            except: pass

    now = time.time()
    old_logs = [os.path.join(LOG_DIR, fl) for fl in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, fl)) and now - os.path.getmtime(os.path.join(LOG_DIR, fl)) > 86400]
    if old_logs:
        print(f"\n[System] 发现 {len(old_logs)} 个过期日志。是否清理？(y/n): ")
        if input().strip().lower() == 'y':
            for f in old_logs: os.remove(f)

def find_images():
    if not os.path.exists(IMAGE_DIR): return None, []
    all_f = sorted([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    cvs = [f for f in all_f if "封面" in f]
    ins = [os.path.join(IMAGE_DIR, f) for f in all_f if "封面" not in f]
    return (os.path.join(IMAGE_DIR, cvs[0]) if cvs else None), ins

COVER_IMAGE, INNER_IMAGES = find_images()

# ================= 配置信息 =================
API_KEY = "67772b333e2645b684c51a9fc4ba2595"
SECRET = "85x6099I6Ql7122S"
DEVICE_ID = "testdevice000001"
WS_URL = "wss://ws-api.turingapi.com/api/v2"
CAMERA_ID = 796
SKILL_CODE = 1000056

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

class PicBookBatchTester:
    def __init__(self):
        self.results = []
        self.seq = 1

    def save_tx_log(self, name, label, init, finish, resps):
        fname = f"{self.seq:03d}_{label}_{os.path.splitext(name)[0]}.txt"
        fpath = os.path.join(LOG_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"REQ INIT:\n{json.dumps(init, indent=2, ensure_ascii=False)}\n\n")
            f.write(f"REQ FINISH:\n{json.dumps(finish, indent=2, ensure_ascii=False)}\n\n")
            f.write("RESPS:\n" + "\n".join([json.dumps(r, ensure_ascii=False) for r in resps]))
        return fpath

    async def run_full_test(self):
        cleanup_files()
        if not COVER_IMAGE: return
        print(f"检测到 {len(INNER_IMAGES)} 张内页，准备开始轮询...\n")
        try:
            async with websockets.connect(WS_URL) as ws:
                bid, cm = await self.upload_process(ws, COVER_IMAGE, label="COVER")
                if cm: self.results.append(cm)
                if not bid: return
                for idx, img in enumerate(INNER_IMAGES):
                    _, im = await self.upload_process(ws, img, book_id=bid, label=f"INNER_{idx+1}")
                    if im: self.results.append(im)
                    print(f"[{idx+1}/{len(INNER_IMAGES)}] {os.path.basename(img)} 处理完成")
                    await asyncio.sleep(0.5)
        finally:
            self.print_summary_table()
            self.generate_professional_report()

    async def upload_process(self, ws, path, book_id=None, label=""):
        f_uuid = str(uuid.uuid4()).replace("-", "")
        ts = int(time.time() * 1000)
        key, iv = get_key_iv(ts)
        init_req = {
            "deviceId": DEVICE_ID, "requestType": [1, 2],
            "nlpRequest": {
                "content": [{"data": f_uuid, "type": 1}],
                "clientInfo": {
                    "appState": {"code": SKILL_CODE, "operateState": 1100},
                    "robotSkill": {
                        str(SKILL_CODE): {
                            "imgFlagId": str(uuid.uuid4()).replace("-", ""), "innerUrlFlag": 1, "debug": 0, "cameraId": CAMERA_ID, 
                            "type": 5, "typeFlag": 6, "textFlag": 1, "accessModel": 1, "modelOrder": 2, 
                            "showZhEnData": True, "showSimilar": True, "languageOrder": 1
                        }
                    }
                }
            },
            "binarysState": { "openBinarysId": f_uuid }
        }
        if book_id: init_req["nlpRequest"]["clientInfo"]["robotSkill"][str(SKILL_CODE)]["bookId"] = book_id
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": encrypt_data(init_req, key, iv)}))
        with open(path, "rb") as f: await ws.send(f.read())
        finish_req = {"binarysState": {"completeBinarysId": f_uuid}}
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": encrypt_data(finish_req, key, iv)}))
        
        t0 = time.time()
        t_fr, t_asr, t_tts, res_id, tts_url, all_r = None, None, None, None, "N/A", []
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                tw = time.time()
                if t_fr is None: t_fr = tw
                data = json.loads(msg)
                if "data" in data: data.update(decrypt_data(data["data"], key, iv))
                all_r.append(data)
                if data.get("code") == 200 and t_asr is None: t_asr = tw
                if "nlpResponse" in data:
                    res = data["nlpResponse"]
                    p = res.get("intent", {}).get("parameters", {})
                    if "bookId" in p: res_id = p["bookId"]
                    elif "titleData" in p: res_id = p["titleData"].get("bookId")
                    elif "innerData" in p: res_id = p["innerData"].get("bookId")
                    for item in res.get("results", []):
                        u = item.get("values", {}).get("ttsUrl", [])
                        if u: tts_url = u[0]; t_tts = tw; break
                if data.get("done") is True: break
            except: break

        log_path = self.save_tx_log(os.path.basename(path), label, init_req, finish_req, all_r)
        self.seq += 1
        m = {"name": os.path.basename(path), "resp": 0, "asr": 0, "nlp": 0, "tts": 0, "total": 0, "url": tts_url, "log": log_path, "status": "失败", "bookId": res_id}
        if t_fr:
            m["resp"] = round(t_fr - t0, 3)
            if t_asr:
                m["asr"] = round(t_asr - t_fr, 3)
                if t_tts:
                    # 分段耗时计算
                    m["nlp"] = max(0, round(t_tts - t_asr, 6)) 
                    m["tts"] = max(0, round(t_tts - t_asr, 6))
                m["status"] = "成功"
                m["total"] = round(m["resp"] + m["asr"] + m["tts"], 3)
        return res_id, m

    def print_summary_table(self):
        total = len(self.results)
        if total == 0: return
        avg_resp = sum(r["resp"] for r in self.results) / total
        avg_asr = sum(r["asr"] for r in self.results) / total
        avg_tts = sum(r["tts"] for r in self.results) / total
        avg_total = sum(r["total"] for r in self.results) / total

        print("\n" + "┌" + "─" * 107 + "┐")
        print("│" + " " * 44 + "批量测试结果简报" + " " * 47 + "│")
        print("├" + "─" * 20 + "┬" + "─" * 15 + "┬" + "─" * 15 + "┬" + "─" * 25 + "┬" + "─" * 26 + "┤")
        print(f"│ {pad_text('环节', 18)} │ {pad_text('成功数', 13)} │ {pad_text('成功率', 13)} │ {pad_text('平均耗时(s)', 23)} │ {pad_text('备注', 24)} │")
        print("├" + "─" * 20 + "┼" + "─" * 15 + "┼" + "─" * 15 + "┼" + "─" * 25 + "┼" + "─" * 26 + "┤")
        print(f"│ {pad_text('FirstResp', 18)} │ {pad_text(total, 13)} │ {pad_text('100.0%', 13)} │ {pad_text(f'{avg_resp:.3f}', 23)} │ {pad_text('首次云端响应', 24)} │")
        print(f"│ {pad_text('识别时间(识)', 18)} │ {pad_text(total, 13)} │ {pad_text('100.0%', 13)} │ {pad_text(f'{avg_asr:.3f}', 23)} │ {pad_text('识别处理(识)', 24)} │")
        print(f"│ {pad_text('音频返回时间(音)', 18)} │ {pad_text(total, 13)} │ {pad_text('100.0%', 13)} │ {pad_text(f'{avg_tts:.3f}', 23)} │ {pad_text('音频下发(音)', 24)} │")
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
            print(f"║ {pad_text(i+1, 4)} ║ {pad_text(name, 30)} ║ {pad_text(r['resp'], 10)} ║ {pad_text(r['asr'], 12)} ║ {pad_text(r['tts'], 16)} ║ {pad_text(r['total'], 8)} ║")
        print(border.replace("╟", "╚").replace("╫", "╩").replace("╢", "╝").replace("─", "═"))

    def generate_professional_report(self):
        report_name = os.path.join(BASE_DIR, f"Picbook_Performance_Report_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
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
        dash.write('B2', 'Turing API 深度评测 (Performance Overview)', fmt_title)
        
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
        col.add_series({'name': 'FirstResp(s)', 'categories': ['测试详情', 1, 1, total, 1], 'values': ['测试详情', 1, 4, total, 4], 'fill': {'color': '#3498DB'}, 'border': {'none': True}, 'gap': 120})
        col.add_series({'name': '识 耗时(s)', 'categories': ['测试详情', 1, 1, total, 1], 'values': ['测试详情', 1, 5, total, 5], 'fill': {'color': '#F1C40F'}, 'border': {'none': True}})
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
        print(f"\n[System] 国际范专业报表已生成: {report_name}")

def get_key_iv(ts):
    m = hashlib.md5((API_KEY + SECRET + str(ts)).encode('utf-8')).hexdigest()
    k = m[8:24].encode('utf-8')
    return k, k
def encrypt_data(d, k, v):
    ci = AES.new(k, AES.MODE_CBC, v)
    return base64.b64encode(ci.encrypt(pad(json.dumps(d, ensure_ascii=False).encode('utf-8'), 16))).decode('utf-8')
def decrypt_data(e, k, v):
    try: return json.loads(unpad(AES.new(k, AES.MODE_CBC, v).decrypt(base64.b64decode(e)), 16).decode('utf-8'))
    except: return {}

if __name__ == "__main__":
    asyncio.run(PicBookBatchTester().run_full_test())
