#!/bin/bash
SERVER="root@39.105.174.143"
REMOTE_PATH="/root/htz-api-server-python"
LOCAL_PATH="$(cd "$(dirname "$0")" && pwd)"

echo "上传文件..."
ssh "$SERVER" "mkdir -p $REMOTE_PATH/defaults"
scp "$LOCAL_PATH/db.py" "$LOCAL_PATH/htz-api-server.py" "$LOCAL_PATH/request.py" "$LOCAL_PATH/static/admin.html" "$LOCAL_PATH/admin_secret.json" "$SERVER:$REMOTE_PATH/"
scp "$LOCAL_PATH/defaults/feature_help.md" "$SERVER:$REMOTE_PATH/defaults/feature_help.md"

echo "同步容器代码..."
ssh "$SERVER" "docker exec htz_server mkdir -p /app/defaults && docker cp $REMOTE_PATH/db.py htz_server:/app/db.py && docker cp $REMOTE_PATH/htz-api-server.py htz_server:/app/htz-api-server.py && docker cp $REMOTE_PATH/request.py htz_server:/app/request.py && docker cp $REMOTE_PATH/admin.html htz_server:/app/static/admin.html && docker cp $REMOTE_PATH/admin_secret.json htz_server:/app/admin_secret.json && docker cp $REMOTE_PATH/defaults/feature_help.md htz_server:/app/defaults/feature_help.md"

echo "重启服务..."
ssh "$SERVER" "docker restart htz_server"

echo "部署完成"