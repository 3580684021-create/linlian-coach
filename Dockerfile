FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件并安装 Python 包
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有文件
COPY . .

# 创建临时目录
RUN mkdir -p /tmp/linlian_video_frames

# 暴露端口
EXPOSE 8080

# 启动命令
CMD ["python", "coach_server.py"]
