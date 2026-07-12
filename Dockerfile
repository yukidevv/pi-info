# ラズパイ (arm64/armv7) でもそのままビルドできる slim イメージ
FROM python:3.12-slim

# psutil はビルド済み wheel が提供されるため追加のビルドツールは不要
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8001

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

WORKDIR /app/backend

EXPOSE 8001

# HOST/PORT 環境変数で待ち受け先を切り替え可能（shell 形式で展開）
CMD uvicorn app:app --host ${HOST:-0.0.0.0} --port ${PORT:-8001}
