#!/usr/bin/env bash
set -e

# 切到脚本所在目录（保证相对路径正确）
cd "$(dirname "$0")"

# 可选：激活虚拟环境
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# 启动 tg downloader
exec python3 media_downloader.py
