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

ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

def fetch_image(url, timeout=15):
    headers = {"User-Agent": "ImageCompressor/1.0"}
    r = requests.get(url, headers=headers, timeout=timeout, stream=True)
    r.raise_for_status()
    content_type = r.headers.get("Content-Type", "").split(";")[0]
    content = r.content
    return content, content_type

def compress_image_bytes(image_bytes, content_type):
    img = Image.open(io.BytesIO(image_bytes))

    # Convert RGBA or other modes to RGB (JPEG can't handle transparency)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])  # use alpha channel as mask
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too large
    w, h = img.size
    max_side = max(w, h)
    if max_side > MAX_DIM:
        scale = MAX_DIM / float(max_side)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)

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
        return jsonify({"error": "compress_failed", "detail": str(e)}), 500

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
