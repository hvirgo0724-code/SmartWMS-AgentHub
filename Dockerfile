# 智能仓储管理系统 - 后端镜像
# 构建上下文为项目根目录（见 docker-compose.yml 的 context 设置）
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用镜像层缓存）；构建时可指定国内源加速：
# docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip config set global.index-url ${PIP_INDEX_URL}

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# 后端代码（/app = BASE_DIR，其上级的 frontend 即 FRONTEND_DIR）
COPY backend/ ./

# 前端静态资源（main.py 通过 /static 挂载，含登录背景视频）
COPY frontend/ /frontend

# 启动脚本：首次启动自动初始化数据库并灌入演示数据
COPY backend/docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
