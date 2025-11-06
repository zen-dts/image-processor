# compress_service.py
# Simple image-compression microservice
# Dependencies: pip install flask requests pillow python-magic

import io
import os
import math
from flask import Flask, request, send_file, jsonify, abort
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
    # open image
    img = Image.open(io.BytesIO(image_bytes))

    # convert to RGB if needed
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # resize if large
    w, h = img.size
    max_side = max(w, h)
    if max_side > MAX_DIM:
        scale = MAX_DIM / float(max_side)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)

    # try saving as JPEG (best compression for photographs)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    out_bytes = out.getvalue()

    # if still too big, reduce quality iteratively
    quality = JPEG_QUALITY
    while len(out_bytes) > MAX_BYTES and quality > 30:
        quality = max(30, int(quality * 0.85))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        out_bytes = out.getvalue()

    return out_bytes


@app.route("/compress", methods=["POST"])
def compress():
    # simple auth
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

    # quick mime check (optional)
    if content_type not in ALLOWED_MIMES:
        # allow processing anyway, but warn
        pass

    # if small enough, just return original
    if len(img_bytes) <= MAX_BYTES:
        # return original image unchanged
        return send_file(io.BytesIO(img_bytes), mimetype=content_type, as_attachment=False,
                         download_name="image"+((".jpg") if content_type.startswith("image/") else ".img"))

    # compress
    try:
        compressed = compress_image_bytes(img_bytes, content_type)
    except Exception as e:
        return jsonify({"error": "compress_failed", "detail": str(e)}), 500

    # final size check
    final_size = len(compressed)
    ratio = round(final_size / max(1, len(img_bytes)), 3)

    # respond with binary image; Make will accept it as file
    return send_file(io.BytesIO(compressed), mimetype="image/jpeg", as_attachment=False,
                     download_name=f"compressed.jpg",
                     headers={"X-Original-Size": str(len(img_bytes)), "X-Final-Size": str(final_size),
                              "X-Ratio": str(ratio)})


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
