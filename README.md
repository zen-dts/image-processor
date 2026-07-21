# image-processor

A lightweight image compression service (Flask + Pillow). Give it an image
URL, it returns a JPEG capped at 1600 px / 4 MB — built so vision models
don't get fed multi-megabyte product photos.

Runs on Render (free tier) at `https://imgcompress-cc9w.onrender.com`,
auto-deployed from `main`. In production use by the Rabalux Product
Description Flow (make.com). Capability manifest: [atoms.json](atoms.json).

## API

- `POST /compress` — header `X-Api-Key`, body/form/query `url=<image url>`.
  Returns the compressed JPEG; add `?json=true` for size stats instead.
  Errors come back as JSON with status 400/401.
- `GET /health` — returns `ok`.

## Memory safety (2026-07-21 fix)

The service lives in a 512 MB instance, so:

- downloads are streamed with a 25 MB cap,
- decode is refused above 40 megapixels (`Image.MAX_IMAGE_PIXELS` enforced),
- images are shrunk to output size BEFORE transparency flattening, so the
  white-background canvas is never built at source resolution,
- gunicorn recycles its worker every ~50 requests (`gunicorn.conf.py`).

Config via env: `COMPRESS_API_KEY`, `MAX_BYTES`, `MAX_DIM`, `JPEG_QUALITY`,
`MAX_DOWNLOAD_BYTES`, `MAX_PIXELS`.
