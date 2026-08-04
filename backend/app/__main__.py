"""
本地便捷启动入口：`python -m app`（等价于原 `python app.py`）。
生产部署仍走 `uvicorn app:app`，此文件仅为本地/调试提供便利。
"""
import os

import uvicorn

from . import app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
