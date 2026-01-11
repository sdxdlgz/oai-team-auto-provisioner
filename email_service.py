# ==================== 邮箱服务模块 ====================
# 处理邮箱创建、验证码获取等功能 (支持多种邮箱系统)

import re
import time
import random
import string
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    EMAIL_API_BASE,
    EMAIL_API_AUTH,
    EMAIL_ROLE,
    DEFAULT_PASSWORD,
    REQUEST_TIMEOUT,
    VERIFICATION_CODE_INTERVAL,
    VERIFICATION_CODE_MAX_RETRIES,
    get_random_domain,
    EMAIL_PROVIDER,
    GPTMAIL_API_BASE,
    GPTMAIL_API_KEY,
    GPTMAIL_PREFIX,
    GPTMAIL_DOMAINS,
    get_random_gptmail_domain,
)
from logger import log


def create_session_with_retry():
    """创建带重试机制的 HTTP Session"""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# 全局 HTTP Session
http_session = create_session_with_retry()


# ==================== GPTMail 临时邮箱服务 ====================
class GPTMailService:
    """GPTMail 临时邮箱服务"""

    def __init__(self, api_base: str = None, api_key: str = None):
        self.api_base = api_base or GPTMAIL_API_BASE
        self.api_key = api_key or GPTMAIL_API_KEY
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def generate_email(self, prefix: str = None, domain: str = None) -> tuple[str, str]:
        """生成临时邮箱地址

        Args:
            prefix: 邮箱前缀 (可选)
            domain: 域名 (可选)

        Returns:
            tuple: (email, error) - 邮箱地址和错误信息
        """
        url = f"{self.api_base}/api/generate-email"

        try:
            if prefix or domain:
                payload = {}
                if prefix:
                    payload["prefix"] = prefix
                if domain:
                    payload["domain"] = domain
                response = http_session.post(url, headers=self.headers, json=payload, timeout=REQUEST_TIMEOUT)
            else:
                response = http_session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)

            data = response.json()

            if data.get("success"):
                email = data.get("data", {}).get("email", "")
                log.success(f"GPTMail 生成邮箱: {email}")
                return email, None
            else:
                error = data.get("error", "Unknown error")
                log.error(f"GPTMail 生成邮箱失败: {error}")
                return None, error

        except Exception as e:
            log.error(f"GPTMail 生成邮箱异常: {e}")
            return None, str(e)

    def get_emails(self, email: str) -> tuple[list, str]:
        """获取邮箱的邮件列表

        Args:
            email: 邮箱地址

        Returns:
            tuple: (emails, error) - 邮件列表和错误信息
        """
        url = f"{self.api_base}/api/emails"
        params = {"email": email}

        try:
            response = http_session.get(url, headers=self.headers, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if data.get("success"):
                emails = data.get("data", {}).get("emails", [])
                return emails, None
            else:
                error = data.get("error", "Unknown error")
                return [], error

        except Exception as e:
            log.warning(f"GPTMail 获取邮件列表异常: {e}")
            return [], str(e)

    def get_email_detail(self, email_id: str) -> tuple[dict, str]:
        """获取单封邮件详情

        Args:
            email_id: 邮件ID

        Returns:
            tuple: (email_detail, error) - 邮件详情和错误信息
        """
        url = f"{self.api_base}/api/email/{email_id}"

        try:
            response = http_session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if data.get("success"):
                return data.get("data", {}), None
            else:
                error = data.get("error", "Unknown error")
                return {}, error

        except Exception as e:
            log.warning(f"GPTMail 获取邮件详情异常: {e}")
            return {}, str(e)

    def delete_email(self, email_id: str) -> tuple[bool, str]:
        """删除单封邮件

        Args:
            email_id: 邮件ID

        Returns:
            tuple: (success, error)
        """
        url = f"{self.api_base}/api/email/{email_id}"

        try:
            response = http_session.delete(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if data.get("success"):
                return True, None
            else:
                return False, data.get("error", "Unknown error")

        except Exception as e:
            return False, str(e)

    def clear_inbox(self, email: str) -> tuple[int, str]:
        """清空邮箱

        Args:
            email: 邮箱地址

        Returns:
            tuple: (deleted_count, error)
        """
        url = f"{self.api_base}/api/emails/clear"
        params = {"email": email}

        try:
            response = http_session.delete(url, headers=self.headers, params=params, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if data.get("success"):
                count = data.get("data", {}).get("count", 0)
                return count, None
            else:
                return 0, data.get("error", "Unknown error")

        except Exception as e:
            return 0, str(e)

    def get_verification_code(self, email: str, max_retries: int = None, interval: int = None) -> tuple[str, str, str]:
        """从邮箱获取验证码

        Args:
            email: 邮箱地址
            max_retries: 最大重试次数
            interval: 轮询间隔 (秒)

        Returns:
            tuple: (code, error, email_time) - 验证码、错误信息、邮件时间
        """
        if max_retries is None:
            max_retries = VERIFICATION_CODE_MAX_RETRIES
        if interval is None:
            interval = VERIFICATION_CODE_INTERVAL

        log.info(f"GPTMail 等待验证码邮件: {email}", icon="email")
        progress_shown = False

        for i in range(max_retries):
            try:
                emails, error = self.get_emails(email)

                if emails:
                    latest_email = emails[0]
                    subject = latest_email.get("subject", "")
                    content = latest_email.get("content", "")
                    email_time_str = latest_email.get("created_at", "")

                    # 尝试从主题中提取验证码
                    code = self._extract_code(subject)
                    if code:
                        if progress_shown:
                            log.progress_clear()
                        log.success(f"GPTMail 验证码获取成功: {code}")
                        return code, None, email_time_str

                    # 尝试从内容中提取验证码
                    code = self._extract_code(content)
                    if code:
                        if progress_shown:
                            log.progress_clear()
                        log.success(f"GPTMail 验证码获取成功: {code}")
                        return code, None, email_time_str

            except Exception as e:
                if progress_shown:
                    log.progress_clear()
                    progress_shown = False
                log.warning(f"GPTMail 获取邮件异常: {e}")

            if i < max_retries - 1:
                elapsed = (i + 1) * interval
                log.progress_inline(f"[等待中... {elapsed}s]")
                progress_shown = True
                time.sleep(interval)

        if progress_shown:
            log.progress_clear()
        log.error("GPTMail 验证码获取失败 (超时)")
        return None, "未能获取验证码", None

    def _extract_code(self, text: str) -> str:
        """从文本中提取验证码"""
        if not text:
            return None

        # 尝试多种模式
        patterns = [
            r"代码为\s*(\d{6})",
            r"code is\s*(\d{6})",
            r"verification code[:\s]*(\d{6})",
            r"验证码[：:\s]*(\d{6})",
            r"(\d{6})",  # 最后尝试直接匹配6位数字
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None


# 全局 GPTMail 服务实例
gptmail_service = GPTMailService()


# ==================== 原有 Cloud Mail 邮箱服务 ====================


def generate_random_email() -> str:
    """生成随机邮箱地址: {random_str}oaiteam@{random_domain}"""
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    domain = get_random_domain()
    email = f"{random_str}oaiteam@{domain}"
    log.success(f"生成邮箱: {email}")
    return email


def create_email_user(email: str, password: str = None, role_name: str = None) -> tuple[bool, str]:
    """在邮箱平台创建用户 (与 main.py 一致)

    Args:
        email: 邮箱地址
        password: 密码，默认使用 DEFAULT_PASSWORD
        role_name: 角色名，默认使用 EMAIL_ROLE

    Returns:
        tuple: (success, message)
    """
    if password is None:
        password = DEFAULT_PASSWORD
    if role_name is None:
        role_name = EMAIL_ROLE

    url = f"{EMAIL_API_BASE}/addUser"
    headers = {
        "Authorization": EMAIL_API_AUTH,
        "Content-Type": "application/json"
    }
    payload = {
        "list": [{"email": email, "password": password, "roleName": role_name}]
    }

    try:
        log.info(f"创建邮箱用户: {email}", icon="email")
        response = http_session.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
        success = data.get("code") == 200
        msg = data.get("message", "Unknown error")

        if success:
            log.success("邮箱创建成功")
        else:
            log.warning(f"邮箱创建失败: {msg}")

        return success, msg
    except Exception as e:
        log.error(f"邮箱创建异常: {e}")
        return False, str(e)


def get_verification_code(email: str, max_retries: int = None, interval: int = None) -> tuple[str, str, str]:
    """从邮箱获取验证码

    Args:
        email: 邮箱地址
        max_retries: 最大重试次数
        interval: 轮询间隔 (秒)

    Returns:
        tuple: (code, error, email_time) - 验证码、错误信息、邮件时间
    """
    if max_retries is None:
        max_retries = VERIFICATION_CODE_MAX_RETRIES
    if interval is None:
        interval = VERIFICATION_CODE_INTERVAL

    url = f"{EMAIL_API_BASE}/emailList"
    headers = {
        "Authorization": EMAIL_API_AUTH,
        "Content-Type": "application/json"
    }
    payload = {"toEmail": email}

    log.info(f"等待验证码邮件: {email}", icon="email")
    progress_shown = False  # 追踪是否已显示进度指示器

    for i in range(max_retries):
        try:
            response = http_session.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            data = response.json()

            if data.get("code") == 200:
                emails = data.get("data", [])
                if emails:
                    latest_email = emails[0]
                    subject = latest_email.get("subject", "")
                    email_time_str = latest_email.get("createTime", "")

                    # 尝试从主题中提取验证码
                    match = re.search(r"代码为\s*(\d{6})", subject)
                    if match:
                        code = match.group(1)
                        if progress_shown:
                            log.progress_clear()
                        log.success(f"验证码获取成功: {code}")
                        return code, None, email_time_str

                    # 尝试其他模式
                    match = re.search(r"code is\s*(\d{6})", subject, re.IGNORECASE)
                    if match:
                        code = match.group(1)
                        if progress_shown:
                            log.progress_clear()
                        log.success(f"验证码获取成功: {code}")
                        return code, None, email_time_str

                    # 尝试直接匹配 6 位数字
                    match = re.search(r"(\d{6})", subject)
                    if match:
                        code = match.group(1)
                        if progress_shown:
                            log.progress_clear()
                        log.success(f"验证码获取成功: {code}")
                        return code, None, email_time_str

        except Exception as e:
            if progress_shown:
                log.progress_clear()
                progress_shown = False
            log.warning(f"获取邮件异常: {e}")

        if i < max_retries - 1:
            elapsed = (i + 1) * interval
            log.progress_inline(f"[等待中... {elapsed}s]")
            progress_shown = True
            time.sleep(interval)

    if progress_shown:
        log.progress_clear()
    log.error("验证码获取失败 (超时)")
    return None, "未能获取验证码", None


def fetch_email_content(email: str) -> list:
    """获取邮箱中的邮件列表

    Args:
        email: 邮箱地址

    Returns:
        list: 邮件列表
    """
    url = f"{EMAIL_API_BASE}/emailList"
    headers = {
        "Authorization": EMAIL_API_AUTH,
        "Content-Type": "application/json"
    }
    payload = {"toEmail": email}

    try:
        response = http_session.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()

        if data.get("code") == 200:
            return data.get("data", [])
    except Exception as e:
        log.warning(f"获取邮件列表异常: {e}")

    return []


def batch_create_emails(count: int = 4) -> list:
    """批量创建邮箱

    Args:
        count: 创建数量

    Returns:
        list: [{"email": "...", "password": "..."}, ...]
    """
    accounts = []

    for i in range(count):
        email = generate_random_email()
        password = DEFAULT_PASSWORD

        success, msg = create_email_user(email, password)

        if success or "已存在" in msg:
            accounts.append({
                "email": email,
                "password": password
            })
        else:
            log.warning(f"跳过邮箱 {email}: {msg}")

    log.info(f"邮箱创建完成: {len(accounts)}/{count}", icon="email")
    return accounts


# ==================== 统一邮箱接口 (根据配置自动选择) ====================

def unified_generate_email() -> str:
    """统一生成邮箱地址接口 (根据 EMAIL_PROVIDER 配置自动选择)

    Returns:
        str: 邮箱地址
    """
    if EMAIL_PROVIDER == "gptmail":
        # 生成随机前缀 + oaiteam 后缀，确保不重复
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        prefix = f"{random_str}-oaiteam"
        domain = get_random_gptmail_domain() or None
        email, error = gptmail_service.generate_email(prefix=prefix, domain=domain)
        if email:
            return email
        log.warning(f"GPTMail 生成失败，回退到 Cloud Mail: {error}")

    # 默认使用 Cloud Mail 系统
    return generate_random_email()


def unified_create_email() -> tuple[str, str]:
    """统一创建邮箱接口 (根据 EMAIL_PROVIDER 配置自动选择)

    Returns:
        tuple: (email, password)
    """
    if EMAIL_PROVIDER == "gptmail":
        # 生成随机前缀 + oaiteam 后缀，确保不重复
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        prefix = f"{random_str}-oaiteam"
        domain = get_random_gptmail_domain() or None
        email, error = gptmail_service.generate_email(prefix=prefix, domain=domain)
        if email:
            # GPTMail 不需要密码，但为了接口一致性返回默认密码
            return email, DEFAULT_PASSWORD
        log.warning(f"GPTMail 生成失败，回退到 Cloud Mail: {error}")

    # 默认使用 Cloud Mail 系统
    email = generate_random_email()
    success, msg = create_email_user(email, DEFAULT_PASSWORD)
    if success or "已存在" in msg:
        return email, DEFAULT_PASSWORD
    return None, None


def unified_get_verification_code(email: str, max_retries: int = None, interval: int = None) -> tuple[str, str, str]:
    """统一获取验证码接口 (根据 EMAIL_PROVIDER 配置自动选择)

    Args:
        email: 邮箱地址
        max_retries: 最大重试次数
        interval: 轮询间隔 (秒)

    Returns:
        tuple: (code, error, email_time) - 验证码、错误信息、邮件时间
    """
    if EMAIL_PROVIDER == "gptmail":
        return gptmail_service.get_verification_code(email, max_retries, interval)

    # 默认使用 Cloud Mail 系统
    return get_verification_code(email, max_retries, interval)


def unified_fetch_emails(email: str) -> list:
    """统一获取邮件列表接口 (根据 EMAIL_PROVIDER 配置自动选择)

    Args:
        email: 邮箱地址

    Returns:
        list: 邮件列表
    """
    if EMAIL_PROVIDER == "gptmail":
        emails, error = gptmail_service.get_emails(email)
        return emails

    # 默认使用 Cloud Mail 系统
    return fetch_email_content(email)
