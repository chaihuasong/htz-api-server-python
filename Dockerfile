FROM registry.cn-hangzhou.aliyuncs.com/library/python:3.11-slim
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

EXPOSE 8082

CMD ["uvicorn", "htz-api-server:app", "--host", "0.0.0.0", "--port", "8082"]