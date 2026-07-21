import io
import os
from flask import Flask, request, send_file, jsonify
import requests
from PIL import Image

app = Flask(__name__)

# CONFIG
API_KEY = os.environ.get("COMPRESS_API_KEY", "changeme")   # set in env in production
MAX_BYTES = int(os.environ.get("MAX_BYTES", 4 * 1024 * 1024))  # 4 MB default
MAX_DIM = int(os.environ.get("MAX_DIM", 1600))  # largest side in px
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", 86))
MAX_DOWNLOAD_BYTES = int(os.environ.get("MAX_DOWNLOAD_BYTES", 25 * 1024 * 1024))  # 25 MB
MAX_PIXELS = int(os.environ.get("MAX_PIXELS", 40_000_000))  # 40 MP decode ceiling

# Pillow's own decompression-bomb guard only warns by default; on a 512 MB
# instance an oversized decode is fatal, so enforce a hard ceiling instead.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

def fetch_image(url, timeout=15):
    headers = {"User-Agent": "ImageCompressor/1.0"}
    r = requests.get(url, headers=headers, timeout=timeout, stream=True)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type", "").split(";")[0]
    declared = r.headers.get("Content-Length")
    if declared and int(declared) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"source file too large ({declared} bytes, limit {MAX_DOWNLOAD_BYTES})")
    chunks = []
    total = 0
    for chunk in r.iter_content(64 * 1024):
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"source file too large (over {MAX_DOWNLOAD_BYTES} bytes)")
        chunks.append(chunk)
    return b"".join(chunks), content_type

def compress_image_bytes(image_bytes, content_type):
    img = Image.open(io.BytesIO(image_bytes))

    if img.width * img.height > MAX_PIXELS:
        raise ValueError(f"image too large to process ({img.width}x{img.height}, limit {MAX_PIXELS} px)")

    # For JPEGs, decode directly at reduced resolution instead of full size.
    img.draft("RGB", (MAX_DIM, MAX_DIM))

    # Shrink BEFORE flattening transparency: the white-background canvas below
    # must be built at output size, never at source resolution (a full-size
    # RGBA + RGB pair of a large product PNG exceeds the 512 MB instance).
    img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)

    # Convert RGBA or other modes to RGB (JPEG can't handle transparency)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        if img.mode == "P":
            img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        try:
            # Some images have invalid or mismatched alpha masks
            alpha = img.split()[-1]
            if alpha.size != img.size:
                raise ValueError("Invalid alpha channel size")
            background.paste(img, mask=alpha)
        except Exception as err:
            print(f"[WARN] Transparency handling issue: {err}")
            background.paste(img.convert("RGB"))
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    out_bytes = out.getvalue()

    quality = JPEG_QUALITY
    while len(out_bytes) > MAX_BYTES and quality > 30:
        quality = max(30, int(quality * 0.85))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        out_bytes = out.getvalue()

    return out_bytes

@app.route("/compress", methods=["POST"])
def compress():
    key = request.headers.get("X-Api-Key") or request.args.get("api_key")
    if key != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(force=True, silent=True) or {}
    url = payload.get("url") or request.form.get("url") or request.args.get("url")
    if not url:
        return jsonify({"error": "missing url param"}), 400

    try:
        img_bytes, content_type = fetch_image(url)
    except Exception as e:
        return jsonify({"error": "failed to fetch", "detail": str(e)}), 400

    if content_type not in ALLOWED_MIMES:
        pass  # allow processing anyway

    if len(img_bytes) <= MAX_BYTES:
        return send_file(io.BytesIO(img_bytes), mimetype=content_type, as_attachment=False,
                         download_name="image.jpg")

    try:
        compressed = compress_image_bytes(img_bytes, content_type)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "compress_failed", "detail": str(e)}), 400

    final_size = len(compressed)
    ratio = round(final_size / max(1, len(img_bytes)), 3)

    if request.args.get("json") == "true":
        return jsonify({
            "status": "ok",
            "original_kb": round(len(img_bytes) / 1024, 1),
            "compressed_kb": round(final_size / 1024, 1),
            "ratio": ratio,
            "message": "File compressed successfully."
        })

    out = io.BytesIO(compressed)
    out.seek(0)
    response = send_file(out, mimetype="image/jpeg", as_attachment=False, download_name="compressed.jpg")
    response.headers["X-Original-Size"] = str(len(img_bytes))
    response.headers["X-Final-Size"] = str(final_size)
    response.headers["X-Ratio"] = str(ratio)
    response.headers["Content-Disposition"] = "inline; filename=compressed.jpg"

    return response

@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
