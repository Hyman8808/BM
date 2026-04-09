import asyncio
import websockets
import json
import time
import os
import uuid

API_KEY = "42fb064c66034807bbc7cd5e797e901d"
DEVICE_ID = "testdevice000001"
WS_URL = "ws://ws-api.turingapi.com/api/v2" 
CAMERA_ID = 1710
SKILL_CODE = 1000634

async def test_image():
    image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "指尖查词图片", "查字-舍.jpg")
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
                    str(SKILL_CODE): {
                        "cameraId": CAMERA_ID,
                        "zoomScale": 1.0
                    }
                }
            }
        },
        "binarysState": { "openBinarysId": file_uuid }
    }

    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": init_req}))
        
        with open(image_path, "rb") as f:
            content = f.read()
            chunk_size = 8000
            for i in range(0, len(content), chunk_size):
                await ws.send(content[i:i+chunk_size])
        
        finish_req = {"binarysState": {"completeBinarysId": file_uuid}}
        await ws.send(json.dumps({"key": API_KEY, "timestamp": str(ts), "data": finish_req}))
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(msg)
                print(json.dumps(data, ensure_ascii=False, indent=2))
                if data.get("done") is True: break
            except Exception as e:
                print("error:", e)
                break

if __name__ == "__main__":
    asyncio.run(test_image())
