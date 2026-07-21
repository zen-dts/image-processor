# Loaded automatically by gunicorn from the working directory; no change to
# the Render start command needed. Recycles the worker periodically so slow
# leaks/fragmentation never accumulate to the 512 MB instance limit.
max_requests = 50
max_requests_jitter = 10
