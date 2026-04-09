import os
import sys

try:
    import fitz
except ImportError:
    os.system("pip install PyMuPDF")
    import fitz

doc = fitz.open("指尖查词接口协议V1.0_OpenSocket_20210525.pdf")
with open("pdf_out.txt", "w", encoding="utf-8") as f:
    for page in doc:
        f.write(page.get_text())
print("PDF Extraction Complete")
