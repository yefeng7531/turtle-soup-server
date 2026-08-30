#!/usr/bin/env bash
# 一键部署 / 更新：bash deploy.sh
set -e
cd "$(dirname "$0")"
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d --build
else
  docker compose up -d --build
fi
echo ""
echo "✅ 部署完成！访问：http://服务器IP:8000"
echo "   下一步：打开「设置」页 → 设置访问口令 → 填写 API Key"
