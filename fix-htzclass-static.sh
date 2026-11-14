#!/bin/bash
# =====================================================================
# 修复 htzclass.com 后台 /static 反代缺失
#
# 现象：htzclass.com/admin 打开「用量统计」，下半部分（30天趋势、每日设备数、
#       用量详细记录、机型分布）不显示，只有顶部统计卡。
# 根因：admin.html 引用的 /static/admin-tables.js 在 htzclass.com 上是 404，
#       因为 htzclass.com 的 vhost 只反代了 /admin 和 /htz-api-pyservice/，
#       没有 /static（app.htzchina.org 的 vhost 有这一条，所以那边正常）。
#
# 用法：root 在服务器上执行  bash fix-htzclass-static.sh
# 幂等：已存在 /static 反代时自动跳过。
# =====================================================================
set -e

python3 - <<'PY'
import re, glob, subprocess, sys

proxy = (
    "    ProxyPass /static http://127.0.0.1:8082/static\n"
    "    ProxyPassReverse /static http://127.0.0.1:8082/static\n"
)

# 1) 定位 htzclass.com 的 vhost：优先找 ServerName/ServerAlias 命中 htzclass.com 的，
#    找不到再回退到默认站点 000-default.conf。
files = []
for f in sorted(glob.glob("/etc/apache2/sites-enabled/*.conf")):
    try:
        txt = open(f).read()
    except OSError:
        continue
    if re.search(r"ServerName\s+htzclass\.com|ServerAlias\s+\S*htzclass\.com", txt, re.I):
        files.append(f)
if not files:
    default = "/etc/apache2/sites-enabled/000-default.conf"
    if glob.glob(default):
        files.append(default)

if not files:
    sys.exit("没找到 htzclass.com 的 vhost，请手动确认 /etc/apache2/sites-enabled/ 下的文件")

# 锚点：紧跟已有的 ProxyPass /admin → 8082 之后插入 /static 反代，
# 这样 :80 和 :443 两个 <VirtualHost> 块都会命中。
anchor = re.compile(r"^(\s*)ProxyPass\s+/admin\s+http://127\.0\.0\.1:8082/admin\s*$", re.M)

changed = False
for f in files:
    txt = open(f).read()
    if "ProxyPass /static http://127.0.0.1:8082/static" in txt:
        print(f"跳过（已有 /static 反代）：{f}")
        continue
    new_txt, n = anchor.subn(lambda m: m.group(0) + "\n" + proxy, txt)
    if n == 0:
        print(f"警告：{f} 里没找到 `ProxyPass /admin http://127.0.0.1:8082/admin` 锚点，")
        print(f"请手动在该文件的 <VirtualHost> 块内加这两行：\n{proxy}")
        continue
    open(f, "w").write(new_txt)
    changed = True
    print(f"已追加 /static 反代（命中 {n} 处）：{f}")

if not changed:
    sys.exit(0)

subprocess.run(["apache2ctl", "configtest"], check=True)
subprocess.run(["systemctl", "reload", "apache2"], check=True)
print("Apache 已 reload")
PY

echo ""
echo "验证："
curl -sS -o /dev/null -w "htzclass.com/static/admin-tables.js -> %{http_code} %{content_type}\n" \
  --max-time 8 "https://htzclass.com/static/admin-tables.js"
