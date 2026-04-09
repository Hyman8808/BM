import os
import struct

def get_image_size(file_path):
    size = os.path.getsize(file_path)
    with open(file_path, 'rb') as f:
        data = f.read(25)
        if data[:4] == b'\x89PNG':
            w, h = struct.unpack('>LL', data[16:24])
        elif data[:2] == b'\xff\xd8':
            f.seek(0)
            size = 0
            last_pos = 0
            while True:
                marker, = struct.unpack('>H', f.read(2))
                if marker == 0xffd8: continue
                if marker == 0xffd9 or marker == 0xffda: break
                (length,) = struct.unpack('>H', f.read(2))
                if 0xffc0 <= marker <= 0xffc3:
                    f.read(1)
                    h, w = struct.unpack('>HH', f.read(4))
                    return w, h
                f.read(length - 2)
        else:
            return None, None
    return None, None

IMAGE_DIR = r"e:\工作文档\华为家庭存储\工作文档\AI\绘本协议\绘本图片"
for f in os.listdir(IMAGE_DIR):
    path = os.path.join(IMAGE_DIR, f)
    if os.path.isfile(path) and f.lower().endswith('.jpg'):
        w, h = get_image_size(path)
        print(f"{f}: {w}x{h}")
