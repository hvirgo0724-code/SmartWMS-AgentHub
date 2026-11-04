#!/bin/sh
# 启动前检查数据库：表不存在则执行 seed_data.py 初始化（建库建表 + 演示数据）
set -e

echo "[entrypoint] 等待数据库 ${WMS_DB_HOST:-localhost}:${WMS_DB_PORT:-3306} 就绪..."
i=0
until python -c "
from database import get_conn
with get_conn() as c:
    pass
" 2>/dev/null; do
  i=$((i+1))
  if [ $i -ge 60 ]; then
    echo "[entrypoint] 数据库连接超时（60s），退出"; exit 1
  fi
  sleep 1
done

echo "[entrypoint] 数据库已就绪，检查是否需要初始化..."
NEED_INIT=$(python -c "
from database import query_one
row = query_one(\"SELECT COUNT(*) AS c FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='sys_user'\")
print('yes' if not row or row['c'] == 0 else 'no')
" 2>/dev/null || echo yes)

if [ "$NEED_INIT" = "yes" ]; then
  echo "[entrypoint] 首次启动：执行 seed_data.py 初始化演示数据..."
  python seed_data.py
  echo "[entrypoint] 初始化完成"
else
  echo "[entrypoint] 数据已存在，跳过初始化"
fi

exec "$@"
