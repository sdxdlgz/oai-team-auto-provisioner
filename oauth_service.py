# ==================== OAuth 服务模块 ====================
# 实现 OpenAI OAuth 流程，包括 PKCE 生成、授权 URL 构造、Token 交换
# 完全脱离 CRS，直接与 OpenAI 交互

import os
import json
import base64
import hashlib
import secrets
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime, timedelta
from typing import Optional, Tuple
import requests

from logger import log

# ==================== OpenAI OAuth 常量 ====================
OPENAI_AUTH_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
CALLBACK_PORT = 1455


# ==================== PKCE 相关 ====================
class PKCECodes:
    """PKCE 验证码对"""
    def __init__(self, code_verifier: str, code_challenge: str):
        self.code_verifier = code_verifier
        self.code_challenge = code_challenge


def generate_pkce_codes() -> PKCECodes:
    """生成 PKCE 验证码对 (code_verifier + code_challenge)"""
    # 生成 96 字节随机数据，base64 编码后约 128 字符
    random_bytes = secrets.token_bytes(96)
    code_verifier = base64.urlsafe_b64encode(random_bytes).rstrip(b'=').decode('utf-8')

    # 使用 SHA256 生成 code_challenge
    sha256_hash = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_hash).rstrip(b'=').decode('utf-8')

    return PKCECodes(code_verifier, code_challenge)


def generate_state() -> str:
    """生成随机 state 参数"""
    return secrets.token_urlsafe(32)


# ==================== 授权 URL 生成 ====================
def generate_auth_url(pkce_codes: PKCECodes, state: str) -> str:
    """生成 OpenAI OAuth 授权 URL"""
    params = {
        "client_id": OPENAI_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "openid email profile offline_access",
        "state": state,
        "code_challenge": pkce_codes.code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }

    auth_url = f"{OPENAI_AUTH_URL}?{urlencode(params)}"
    return auth_url


# ==================== Token 交换 ====================
def exchange_code_for_tokens(code: str, pkce_codes: PKCECodes) -> Optional[dict]:
    """用授权码换取 tokens"""
    data = {
        "grant_type": "authorization_code",
        "client_id": OPENAI_CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pkce_codes.code_verifier,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    try:
        log.step("向 OpenAI 交换 tokens...")
        response = requests.post(OPENAI_TOKEN_URL, data=data, headers=headers, timeout=30)

        if response.status_code != 200:
            log.error(f"Token 交换失败: {response.status_code} - {response.text}")
            return None

        token_data = response.json()
        log.success("Token 交换成功")
        return token_data

    except Exception as e:
        log.error(f"Token 交换异常: {e}")
        return None


def parse_id_token(id_token: str) -> dict:
    """解析 JWT ID Token 获取用户信息"""
    try:
        # JWT 格式: header.payload.signature
        parts = id_token.split('.')
        if len(parts) != 3:
            return {}

        # 解码 payload (第二部分)
        payload = parts[1]
        # 添加 padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding

        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims

    except Exception as e:
        log.warning(f"解析 ID Token 失败: {e}")
        return {}


def get_account_id_from_claims(claims: dict) -> str:
    """从 JWT claims 中提取 account_id"""
    # 尝试多种可能的字段
    if "https://api.openai.com/auth" in claims:
        auth_info = claims["https://api.openai.com/auth"]
        if "user_id" in auth_info:
            return auth_info["user_id"]

    # 尝试 organizations
    orgs = claims.get("https://api.openai.com/profile", {}).get("organizations", [])
    if orgs and len(orgs) > 0:
        return orgs[0].get("id", "")

    # 尝试 sub
    return claims.get("sub", "")


# ==================== 本地回调服务器 ====================
class CallbackHandler(BaseHTTPRequestHandler):
    """处理 OAuth 回调的 HTTP Handler"""

    authorization_code = None
    received_state = None
    error = None

    def log_message(self, format, *args):
        # 禁用默认日志
        pass

    def do_GET(self):
        """处理 GET 请求"""
        parsed = urlparse(self.path)

        if parsed.path == "/auth/callback":
            query_params = parse_qs(parsed.query)

            # 检查是否有错误
            if "error" in query_params:
                CallbackHandler.error = query_params.get("error", ["unknown"])[0]
                self._send_error_response()
                return

            # 提取授权码
            if "code" in query_params:
                CallbackHandler.authorization_code = query_params["code"][0]
                CallbackHandler.received_state = query_params.get("state", [None])[0]
                self._send_success_response()
            else:
                CallbackHandler.error = "missing_code"
                self._send_error_response()
        else:
            self.send_response(404)
            self.end_headers()

    def _send_success_response(self):
        """发送成功响应页面"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>授权成功</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                       display: flex; justify-content: center; align-items: center; height: 100vh;
                       margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
                .container { text-align: center; background: white; padding: 40px 60px;
                            border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
                h1 { color: #10b981; margin-bottom: 16px; }
                p { color: #6b7280; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>✅ 授权成功</h1>
                <p>您可以关闭此页面，程序将继续处理...</p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))

    def _send_error_response(self):
        """发送错误响应页面"""
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>授权失败</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                       display: flex; justify-content: center; align-items: center; height: 100vh;
                       margin: 0; background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); }}
                .container {{ text-align: center; background: white; padding: 40px 60px;
                            border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }}
                h1 {{ color: #ef4444; margin-bottom: 16px; }}
                p {{ color: #6b7280; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>❌ 授权失败</h1>
                <p>错误: {CallbackHandler.error}</p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))


class OAuthCallbackServer:
    """OAuth 回调服务器"""

    def __init__(self, port: int = CALLBACK_PORT):
        self.port = port
        self.server = None
        self.thread = None

    def start(self) -> bool:
        """启动回调服务器"""
        try:
            # 重置状态
            CallbackHandler.authorization_code = None
            CallbackHandler.received_state = None
            CallbackHandler.error = None

            self.server = HTTPServer(("localhost", self.port), CallbackHandler)
            self.thread = threading.Thread(target=self.server.serve_forever)
            self.thread.daemon = True
            self.thread.start()
            log.success(f"回调服务器已启动: localhost:{self.port}")
            return True

        except OSError as e:
            if "Address already in use" in str(e) or "10048" in str(e):
                log.warning(f"端口 {self.port} 已被占用，尝试关闭...")
                return False
            log.error(f"启动回调服务器失败: {e}")
            return False

    def stop(self):
        """停止回调服务器"""
        if self.server:
            self.server.shutdown()
            log.step("回调服务器已停止")

    def get_authorization_code(self) -> Optional[str]:
        """获取授权码"""
        return CallbackHandler.authorization_code

    def get_error(self) -> Optional[str]:
        """获取错误信息"""
        return CallbackHandler.error


# ==================== 完整 OAuth 流程 ====================
def create_codex_token_storage(token_data: dict, email: str) -> dict:
    """创建 Codex Token 存储格式 (兼容 CLIProxyAPI)"""
    id_token = token_data.get("id_token", "")
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 864000)  # 默认 10 天

    # 解析 ID Token 获取账号信息
    claims = parse_id_token(id_token)
    account_id = get_account_id_from_claims(claims)
    token_email = claims.get("email", email)

    now = datetime.now()
    expire_time = now + timedelta(seconds=expires_in)

    storage = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "email": token_email,
        "type": "codex",
        "expired": expire_time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }

    return storage


def save_token_to_file(storage: dict, output_dir: str = "tokens") -> str:
    """保存 Token 到 JSON 文件"""
    # 确保目录存在
    os.makedirs(output_dir, exist_ok=True)

    email = storage.get("email", "unknown")
    # 清理邮箱中的特殊字符
    safe_email = email.replace("@", "_at_").replace(".", "_")
    filename = f"codex-{email}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(storage, f, indent=2, ensure_ascii=False)

    log.success(f"Token 已保存: {filepath}")
    return filepath


def extract_code_from_url(url: str) -> Optional[str]:
    """从回调 URL 中提取授权码"""
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        if "code" in query_params:
            return query_params["code"][0]
    except Exception:
        pass
    return None


# ==================== 对外接口 ====================
class OAuthSession:
    """OAuth 会话管理"""

    def __init__(self):
        self.pkce_codes = None
        self.state = None
        self.auth_url = None
        self.callback_server = None

    def generate_auth_url(self) -> Tuple[str, str]:
        """生成授权 URL，返回 (auth_url, state)"""
        self.pkce_codes = generate_pkce_codes()
        self.state = generate_state()
        self.auth_url = generate_auth_url(self.pkce_codes, self.state)
        return self.auth_url, self.state

    def start_callback_server(self) -> bool:
        """启动回调服务器"""
        self.callback_server = OAuthCallbackServer()
        return self.callback_server.start()

    def stop_callback_server(self):
        """停止回调服务器"""
        if self.callback_server:
            self.callback_server.stop()

    def exchange_code(self, code: str) -> Optional[dict]:
        """用授权码换取 tokens"""
        if not self.pkce_codes:
            log.error("PKCE codes 未初始化")
            return None
        return exchange_code_for_tokens(code, self.pkce_codes)

    def get_authorization_code(self) -> Optional[str]:
        """从回调服务器获取授权码"""
        if self.callback_server:
            return self.callback_server.get_authorization_code()
        return None
