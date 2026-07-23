import os
import zipfile

MAGISK_DIR = r"E:\Ank\magisk-module"
OUT_ZIP = r"E:\Ank\dist\ank-magisk.zip"

os.makedirs(os.path.dirname(OUT_ZIP), exist_ok=True)

with zipfile.ZipFile(OUT_ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for root, dirs, files in os.walk(MAGISK_DIR):
        for f in files:
            abs_path = os.path.join(root, f)
            arc_name = os.path.relpath(abs_path, MAGISK_DIR).replace("\\", "/")
            # Skip __pycache__, .pyc, etc.
            if '__pycache__' in arc_name or f.endswith('.pyc'):
                continue
            if f.endswith('.sh'):
                with open(abs_path, 'rb') as fh:
                    data = fh.read()
                data = data.replace(b'\r\n', b'\n')
                zf.writestr(arc_name, data)
            else:
                zf.write(abs_path, arc_name)
            print(f"  {arc_name}")

print(f"\nDone: {os.path.getsize(OUT_ZIP) / 1024 / 1024:.1f} MB")
