#!/bin/bash
# =====================================================================
# 给 app.htzchina.org 建专属 vhost + 独立 Let's Encrypt 证书
# 目标：
#   1) app.htzchina.org 不再落到默认站点(htzclass.com)，避免被带歪到 183.192.65.101；
#   2) 加 HTTPS 证书，App/微信回调可走 https；
#   3) 完全不碰 htzclass.com 和 8082/9100/8081 的现有反代。
#
# 用法：root 在服务器上执行  bash fix-apache-https.sh
# 幂等：重复执行会覆盖同名 vhost，重跑 certbot 会自动续/复用证书。
# =====================================================================
set -e

DOMAIN="app.htzchina.org"
SITE="/etc/apache2/sites-available/app-htzchina.conf"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"

echo "================ 1. 先建 80 vhost（供 certbot webroot 验证用） ================"
cat > "$SITE" <<'VHOST'
<VirtualHost *:80>
    ServerName app.htzchina.org
    DocumentRoot /var/www/html

    # App 端接口 + 微信扫码回调
    ProxyPass /htz-api-pyservice/ http://127.0.0.1:8082/htz-api-pyservice/
    ProxyPassReverse /htz-api-pyservice/ http://127.0.0.1:8082/htz-api-pyservice/
    # 管理后台
    ProxyPass /admin http://127.0.0.1:8082/admin
    ProxyPassReverse /admin http://127.0.0.1:8082/admin
    # 静态资源（意见反馈图片/视频、后台文件等）
    ProxyPass /static http://127.0.0.1:8082/static
    ProxyPassReverse /static http://127.0.0.1:8082/static
    # 主服务端(9100) / 十年持志(8081)
    ProxyPass /main-api/ http://127.0.0.1:9100/
    ProxyPassReverse /main-api/ http://127.0.0.1:9100/
    ProxyPass /ten-years/ http://127.0.0.1:8081/
    ProxyPassReverse /ten-years/ http://127.0.0.1:8081/

    ErrorLog ${APACHE_LOG_DIR}/app-htzchina-error.log
    CustomLog ${APACHE_LOG_DIR}/app-htzchina-access.log combined
</VirtualHost>
VHOST

a2ensite app-htzchina >/dev/null
apache2ctl configtest
systemctl reload apache2
echo "80 vhost 已启用并 reload"

echo ""
echo "================ 2. 申请 app.htzchina.org 证书 ================"
if [ -d "$CERT_DIR" ]; then
  echo "证书已存在，跳过申请"
else
  certbot certonly --webroot -w /var/www/html -d "$DOMAIN" \
    --non-interactive --agree-tos --register-unsafely-without-email || \
  certbot certonly --webroot -w /var/www/html -d "$DOMAIN" --agree-tos
fi

echo ""
echo "================ 3. 写入完整 vhost（80 + 443）并 reload ================"
cat > "$SITE" <<'VHOST'
<VirtualHost *:80>
    ServerName app.htzchina.org
    DocumentRoot /var/www/html

    ProxyPass /htz-api-pyservice/ http://127.0.0.1:8082/htz-api-pyservice/
    ProxyPassReverse /htz-api-pyservice/ http://127.0.0.1:8082/htz-api-pyservice/
    ProxyPass /admin http://127.0.0.1:8082/admin
    ProxyPassReverse /admin http://127.0.0.1:8082/admin
    # 静态资源（意见反馈图片/视频、后台文件等）
    ProxyPass /static http://127.0.0.1:8082/static
    ProxyPassReverse /static http://127.0.0.1:8082/static
    ProxyPass /main-api/ http://127.0.0.1:9100/
    ProxyPassReverse /main-api/ http://127.0.0.1:9100/
    ProxyPass /ten-years/ http://127.0.0.1:8081/
    ProxyPassReverse /ten-years/ http://127.0.0.1:8081/

    ErrorLog ${APACHE_LOG_DIR}/app-htzchina-error.log
    CustomLog ${APACHE_LOG_DIR}/app-htzchina-access.log combined
</VirtualHost>

<IfModule mod_ssl.c>
<VirtualHost *:443>
    ServerName app.htzchina.org

    ProxyPass /htz-api-pyservice/ http://127.0.0.1:8082/htz-api-pyservice/
    ProxyPassReverse /htz-api-pyservice/ http://127.0.0.1:8082/htz-api-pyservice/
    ProxyPass /admin http://127.0.0.1:8082/admin
    ProxyPassReverse /admin http://127.0.0.1:8082/admin
    # 静态资源（意见反馈图片/视频、后台文件等）
    ProxyPass /static http://127.0.0.1:8082/static
    ProxyPassReverse /static http://127.0.0.1:8082/static
    ProxyPass /main-api/ http://127.0.0.1:9100/
    ProxyPassReverse /main-api/ http://127.0.0.1:9100/
    ProxyPass /ten-years/ http://127.0.0.1:8081/
    ProxyPassReverse /ten-years/ http://127.0.0.1:8081/

    ErrorLog ${APACHE_LOG_DIR}/app-htzchina-error.log
    CustomLog ${APACHE_LOG_DIR}/app-htzchina-access.log combined

    Include /etc/letsencrypt/options-ssl-apache.conf
    SSLCertificateFile /etc/letsencrypt/live/app.htzchina.org/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/app.htzchina.org/privkey.pem
</VirtualHost>
</IfModule>
VHOST

apache2ctl configtest
systemctl reload apache2
echo "完整 vhost 已启用并 reload"

echo ""
echo "================ 4. 验证 ================"
curl -sS -o /dev/null -w "http  %{http_code}\n" --max-time 8 \
  "http://$DOMAIN/htz-api-pyservice/api/v1/page/feature_help" || true
curl -sS -o /dev/null -w "https %{http_code}\n" --max-time 8 \
  "https://$DOMAIN/htz-api-pyservice/api/v1/page/feature_help" || true
echo "--- 证书 ---"
echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null \
  | openssl x509 -noout -subject -ext subjectAltName -dates 2>&1 | head -6

echo ""
echo "完成。后续（在你本地代码里）：把 WX_REDIRECT_URI 改成 https://$DOMAIN/... 再 deploy.sh 部署。"
