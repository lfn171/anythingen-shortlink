# Anythingen Shortlink

一个 Flask + SQLite 短链接管理系统，面向 `https://anythingen.com`。

## 功能

- 后台登录 `/login`
- 管理后台 `/admin`
- 手动新增、编辑、删除、启用/停用短链
- 可设置过期时间
- 搜索、分页、访问次数、最后访问时间
- 自定义短码或自动随机短码
- REST API + `X-API-Key` 鉴权
- 默认只允许跳转到 `pan.quark.cn`、`pan.baidu.com`
- Gunicorn + systemd + Nginx 生产部署

## 一、Ubuntu 22.04 安装

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx sqlite3 unzip certbot python3-certbot-nginx
sudo mkdir -p /opt/anythingen-shortlink
```

把项目文件放到 `/opt/anythingen-shortlink` 后：

```bash
cd /opt/anythingen-shortlink
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env
```

生成两个随机密钥：

```bash
openssl rand -hex 32
openssl rand -hex 32
```

编辑：

```bash
nano /opt/anythingen-shortlink/.env
```

示例：

```env
BASE_URL=https://anythingen.com
SECRET_KEY=第一串随机值
API_KEY=第二串随机值
ADMIN_USERNAME=admin
ADMIN_PASSWORD=设置一个初始后台密码
ALLOWED_DOMAINS=pan.quark.cn,pan.baidu.com
SESSION_COOKIE_SECURE=1
```

注意：`ADMIN_PASSWORD` 只在数据库第一次初始化时写入密码哈希。之后请在后台“修改密码”。如果数据库已经存在，修改 `.env` 中的 `ADMIN_PASSWORD` 不会覆盖当前后台密码。

## 二、先本机测试

临时测试 HTTPS Cookie 时，可先执行：

```bash
cd /opt/anythingen-shortlink
set -a
source .env
set +a
SESSION_COOKIE_SECURE=0 ./venv/bin/python app.py
```

访问 `http://服务器IP:5000` 只适合临时测试。生产环境请使用下面的 Nginx + HTTPS。

## 三、systemd

```bash
sudo chown -R www-data:www-data /opt/anythingen-shortlink
sudo cp /opt/anythingen-shortlink/deploy/shortlink.service /etc/systemd/system/shortlink.service
sudo systemctl daemon-reload
sudo systemctl enable --now shortlink
sudo systemctl status shortlink
```

测试：

```bash
curl http://127.0.0.1:5000/health
```

## 四、Nginx

```bash
sudo cp /opt/anythingen-shortlink/deploy/anythingen.com.nginx /etc/nginx/sites-available/anythingen.com
sudo ln -s /etc/nginx/sites-available/anythingen.com /etc/nginx/sites-enabled/anythingen.com
sudo nginx -t
sudo systemctl reload nginx
```

请先确保域名 A 记录已经指向服务器公网 IP。

配置 HTTPS：

```bash
sudo certbot --nginx -d anythingen.com -d www.anythingen.com
```

然后访问：

- `https://anythingen.com/login`
- `https://anythingen.com/admin`

## API

### 创建

```bash
curl -X POST https://anythingen.com/api/links \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: 你的API_KEY' \
  -d '{"target_url":"https://pan.quark.cn/s/9aa07374413b","note":"2026一级造价"}'
```

可自定义短码：

```json
{
  "target_url": "https://pan.quark.cn/s/9aa07374413b",
  "code": "zaojia2026",
  "note": "2026一级造价",
  "enabled": true,
  "expires_at": "2026-12-31T23:59"
}
```

### 获取全部

```bash
curl https://anythingen.com/api/links -H 'X-API-Key: 你的API_KEY'
```

### 获取单个

```bash
curl https://anythingen.com/api/links/zaojia2026 -H 'X-API-Key: 你的API_KEY'
```

### 修改

```bash
curl -X PATCH https://anythingen.com/api/links/zaojia2026 \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: 你的API_KEY' \
  -d '{"target_url":"https://pan.quark.cn/s/新的分享ID"}'
```

### 删除

```bash
curl -X DELETE https://anythingen.com/api/links/zaojia2026 \
  -H 'X-API-Key: 你的API_KEY'
```

## Python 调用

见 `client_example.py`。

## 安全提示

1. 不要把 `.env`、API Key、后台密码提交到公开仓库。
2. 默认只允许指定网盘域名，防止系统被滥用成任意开放重定向服务。
3. 生产环境应启用 HTTPS，并保持 `SESSION_COOKIE_SECURE=1`。
4. 若后续开放多人管理，建议增加 CSRF 防护、账户表和权限体系。
