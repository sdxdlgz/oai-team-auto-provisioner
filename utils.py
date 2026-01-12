# ==================== 工具函数模块 ====================
# 通用工具函数: CSV 记录、JSON 追踪等

import os
import csv
import json
import time
from datetime import datetime

from config import CSV_FILE, TEAM_TRACKER_FILE, TEAMS
from logger import log

# 尝试导入 CRS_INCLUDE_TEAM_OWNERS，如果不存在则默认 False
try:
    from config import CRS_INCLUDE_TEAM_OWNERS
except ImportError:
    CRS_INCLUDE_TEAM_OWNERS = False


def save_to_csv(email: str, password: str, team_name: str = "", status: str = "success", crs_id: str = ""):
    """保存账号信息到 CSV 文件"""
    file_exists = os.path.exists(CSV_FILE)

    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(['email', 'password', 'team', 'status', 'crs_id', 'timestamp'])

        writer.writerow([
            email,
            password,
            team_name,
            status,
            crs_id,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])

    log.info(f"保存到 {CSV_FILE}", icon="save")


def load_team_tracker() -> dict:
    """加载 Team 追踪记录"""
    if os.path.exists(TEAM_TRACKER_FILE):
        try:
            with open(TEAM_TRACKER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"加载追踪记录失败: {e}")

    return {"teams": {}, "last_updated": None}


def save_team_tracker(tracker: dict):
    """保存 Team 追踪记录"""
    tracker["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        with open(TEAM_TRACKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(tracker, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"保存追踪记录失败: {e}")


def add_account_to_tracker(tracker: dict, team_name: str, email: str, status: str = "invited"):
    """添加账号到追踪记录"""
    if team_name not in tracker["teams"]:
        tracker["teams"][team_name] = []

    for account in tracker["teams"][team_name]:
        if account["email"] == email:
            account["status"] = status
            account["updated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return

    tracker["teams"][team_name].append({
        "email": email,
        "status": status,
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


def update_account_status(tracker: dict, team_name: str, email: str, status: str):
    """更新账号状态"""
    if team_name in tracker["teams"]:
        for account in tracker["teams"][team_name]:
            if account["email"] == email:
                account["status"] = status
                account["updated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                return


def remove_account_from_tracker(tracker: dict, team_name: str, email: str) -> bool:
    """从 tracker 中移除账号"""
    if team_name in tracker["teams"]:
        original_len = len(tracker["teams"][team_name])
        tracker["teams"][team_name] = [
            acc for acc in tracker["teams"][team_name] 
            if acc["email"] != email
        ]
        return len(tracker["teams"][team_name]) < original_len
    return False


def get_team_account_count(tracker: dict, team_name: str) -> int:
    """获取 Team 已记录的账号数量"""
    if team_name in tracker["teams"]:
        return len(tracker["teams"][team_name])
    return 0


def get_incomplete_accounts(tracker: dict, team_name: str) -> list:
    """获取未完成的账号列表 (非 crs_added 状态)"""
    incomplete = []
    if team_name in tracker.get("teams", {}):
        for account in tracker["teams"][team_name]:
            status = account.get("status", "")
            if status != "crs_added":
                incomplete.append({
                    "email": account["email"],
                    "status": status,
                    "password": account.get("password", ""),
                    "role": account.get("role", "member")
                })
    return incomplete


def get_all_incomplete_accounts(tracker: dict) -> dict:
    """获取所有 Team 的未完成账号"""
    result = {}
    for team_name in tracker.get("teams", {}):
        incomplete = get_incomplete_accounts(tracker, team_name)
        if incomplete:
            result[team_name] = incomplete
    return result


def add_account_with_password(tracker: dict, team_name: str, email: str, password: str, status: str = "invited"):
    """添加账号到追踪记录 (带密码)"""
    if team_name not in tracker["teams"]:
        tracker["teams"][team_name] = []

    for account in tracker["teams"][team_name]:
        if account["email"] == email:
            account["status"] = status
            account["password"] = password
            account["updated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return

    tracker["teams"][team_name].append({
        "email": email,
        "password": password,
        "status": status,
        "role": "member",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


def print_summary(results: list):
    """打印执行摘要"""
    log.separator("=", 60)
    log.header("执行摘要")
    log.separator("=", 60)

    success_count = sum(1 for r in results if r.get("status") == "success")
    failed_count = len(results) - success_count

    log.info(f"总计: {len(results)} 个账号")
    log.success(f"成功: {success_count}")
    log.error(f"失败: {failed_count}")

    teams = {}
    for r in results:
        team = r.get("team", "Unknown")
        if team not in teams:
            teams[team] = {"success": 0, "failed": 0, "accounts": []}

        if r.get("status") == "success":
            teams[team]["success"] += 1
        else:
            teams[team]["failed"] += 1

        teams[team]["accounts"].append(r)

    log.info("按 Team 统计:")
    for team_name, data in teams.items():
        log.info(f"{team_name}: 成功 {data['success']}, 失败 {data['failed']}", icon="team")
        for acc in data["accounts"]:
            if acc.get("status") == "success":
                log.success(f"{acc.get('email', 'Unknown')}")
            else:
                log.error(f"{acc.get('email', 'Unknown')}")

    log.separator("=", 60)


def format_duration(seconds: float) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


class Timer:
    """计时器"""

    def __init__(self, name: str = ""):
        self.name = name
        self.start_time = None
        self.end_time = None

    def start(self):
        self.start_time = time.time()
        if self.name:
            log.info(f"{self.name} 开始", icon="time")

    def stop(self):
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        if self.name:
            log.info(f"{self.name} 完成 ({format_duration(duration)})", icon="time")
        return duration

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


def add_team_owners_to_tracker(tracker: dict, password: str) -> int:
    """将 team.json 中的 Team Owner 添加到 tracker

    Args:
        tracker: tracker 字典
        password: 默认密码

    Returns:
        int: 添加的 Owner 数量
    """
    if not CRS_INCLUDE_TEAM_OWNERS:
        return 0

    if not TEAMS:
        return 0

    added_count = 0
    for team in TEAMS:
        team_name = team.get("name", "")
        raw_data = team.get("raw", {})
        email = raw_data.get("user", {}).get("email", "")

        if not team_name or not email:
            continue

        existing = False
        if team_name in tracker.get("teams", {}):
            for acc in tracker["teams"][team_name]:
                if acc.get("email") == email:
                    existing = True
                    break

        if not existing:
            if team_name not in tracker["teams"]:
                tracker["teams"][team_name] = []

            tracker["teams"][team_name].append({
                "email": email,
                "password": password,
                "status": "team_owner",
                "role": "owner",
                "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            log.info(f"Team Owner 添加到 tracker: {email} -> {team_name}")
            added_count += 1

    if added_count > 0:
        log.info(f"已添加 {added_count} 个 Team Owner 到 tracker")

    return added_count
