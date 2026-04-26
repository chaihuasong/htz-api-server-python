#!/bin/bash
SERVER="root@39.105.174.143"
REMOTE_PATH="/root/htz-api-server-python"
LOCAL_PATH="$(cd "$(dirname "$0")" && pwd)"

echo "上传文件..."
scp -r "$LOCAL_PATH/db.py" "$LOCAL_PATH/htz-api-server.py" "$LOCAL_PATH/request.py" "$LOCAL_PATH/static" "$SERVER:$REMOTE_PATH/"

echo "同步容器代码..."
ssh "$SERVER" "docker cp $REMOTE_PATH/db.py htz_server:/app/db.py && docker cp $REMOTE_PATH/htz-api-server.py htz_server:/app/htz-api-server.py && docker cp $REMOTE_PATH/request.py htz_server:/app/request.py"

echo "重启服务..."
ssh "$SERVER" "docker restart htz_server"

echo "部署完成"