FROM python:3.12-slim

# 设置工作目录
WORKDIR /home/zhiying/project

# 安装系统级依赖：必须包含 ffmpeg 以及基础编译环境
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libpq-dev \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 暴露 FastAPI 默认服务的 8011 端口
EXPOSE 8011

# 启动命令
CMD ["uvicorn", "main.py", "--host", "0.0.0.0", "--port", "8011"]
