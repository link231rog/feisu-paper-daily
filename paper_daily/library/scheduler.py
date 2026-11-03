import json
import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Any, Optional
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_PLIST_PATH = REPO_ROOT / "scripts" / "com.user.paperdaily.plist"
USER_LAUNCHAGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
USER_PLIST_PATH = USER_LAUNCHAGENTS_DIR / "com.user.paperdaily.plist"
N8N_WORKFLOW_PATH = REPO_ROOT / "scripts" / "n8n" / "paper_daily_n8n_workflow.json"
LAUNCHD_LABEL = "com.user.paperdaily"


def parse_schedule_time(time_str: str) -> tuple[int, int]:
    """Parses and validates a time string like '09:00', '9:00', '9', '09:15' into (hour, minute)."""
    raw = str(time_str).strip()
    m = re.match(r"^(\d{1,2})(?::(\d{1,2}))?$", raw)
    if not m:
        raise ValueError(f"Invalid time format '{time_str}'. Expected 'HH:MM' or 'HH' (e.g. '09:00', '9', '18:30').")

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)

    if not (0 <= hour <= 23):
        raise ValueError(f"Invalid hour {hour}. Must be between 0 and 23.")
    if not (0 <= minute <= 59):
        raise ValueError(f"Invalid minute {minute}. Must be between 0 and 59.")

    return hour, minute


def get_launchd_service_info() -> dict[str, Any]:
    """Inspects launchctl list to check service state."""
    try:
        proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
        for line in proc.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 3 and parts[2] == LAUNCHD_LABEL:
                pid = int(parts[0]) if parts[0] != "-" and parts[0].isdigit() else None
                exit_code = int(parts[1]) if parts[1].lstrip("-").isdigit() else None
                return {
                    "loaded": True,
                    "running": pid is not None,
                    "pid": pid,
                    "last_exit_code": exit_code,
                }
    except Exception as exc:
        logger.debug(f"launchctl list inspection error: {exc}")

    return {
        "loaded": False,
        "running": False,
        "pid": None,
        "last_exit_code": None,
    }


def get_schedule_status() -> dict[str, Any]:
    """Retrieves current scheduler configuration and daemon runtime status."""
    service_info = get_launchd_service_info()

    # Read active plist
    target_plist = USER_PLIST_PATH if USER_PLIST_PATH.is_file() else REPO_PLIST_PATH
    hour = None
    minute = None
    time_str = "Not set"

    if target_plist.is_file():
        try:
            with open(target_plist, "rb") as f:
                data = plistlib.load(f)
            cal = data.get("StartCalendarInterval", {})
            if isinstance(cal, dict) and "Hour" in cal:
                hour = int(cal.get("Hour", 9))
                minute = int(cal.get("Minute", 0))
                time_str = f"{hour:02d}:{minute:02d}"
        except Exception as exc:
            logger.debug(f"Failed to read plist: {exc}")

    # Read n8n workflow cron if present
    n8n_cron = None
    if N8N_WORKFLOW_PATH.is_file():
        try:
            workflow = json.loads(N8N_WORKFLOW_PATH.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") == "n8n-nodes-base.scheduleTrigger":
                    intervals = node.get("parameters", {}).get("rule", {}).get("interval", [])
                    if intervals:
                        n8n_cron = intervals[0].get("expression")
        except Exception as exc:
            logger.debug(f"Failed to read n8n workflow: {exc}")

    return {
        "label": LAUNCHD_LABEL,
        "scheduled_time": time_str,
        "hour": hour,
        "minute": minute,
        "loaded": service_info["loaded"],
        "running": service_info["running"],
        "pid": service_info["pid"],
        "last_exit_code": service_info["last_exit_code"],
        "user_plist": str(USER_PLIST_PATH),
        "user_plist_exists": USER_PLIST_PATH.is_file(),
        "repo_plist": str(REPO_PLIST_PATH),
        "n8n_cron": n8n_cron,
        "log_stdout": str(REPO_ROOT / "data" / "logs" / "launchd_stdout.log"),
        "log_stderr": str(REPO_ROOT / "data" / "logs" / "launchd_stderr.log"),
    }


def build_user_launchd_plist(hour: int = 9, minute: int = 0) -> dict[str, Any]:
    """Dynamically builds the launchd plist structure for the current user and repository path."""
    home_dir = str(Path.home())
    repo_dir = str(REPO_ROOT)
    runner_script = str(REPO_ROOT / "scripts" / "run_daily_local.sh")
    stdout_log = str(REPO_ROOT / "data" / "logs" / "launchd_stdout.log")
    stderr_log = str(REPO_ROOT / "data" / "logs" / "launchd_stderr.log")

    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": ["/bin/bash", runner_script],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "WorkingDirectory": repo_dir,
        "StandardOutPath": stdout_log,
        "StandardErrorPath": stderr_log,
        "EnvironmentVariables": {
            "HOME": home_dir,
            "PATH": f"{home_dir}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }


def set_schedule_time(time_str: str) -> dict[str, Any]:
    """Updates the scheduled trigger time across LaunchAgent plist and n8n workflow, reloading launchctl."""
    hour, minute = parse_schedule_time(time_str)
    formatted_time = f"{hour:02d}:{minute:02d}"

    # 1. Update repo template plist keeping clean generic variables
    if REPO_PLIST_PATH.is_file():
        try:
            with open(REPO_PLIST_PATH, "rb") as f:
                template_data = plistlib.load(f)
            template_data["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
            with open(REPO_PLIST_PATH, "wb") as f:
                plistlib.dump(template_data, f, fmt=plistlib.FMT_XML)
            logger.info(f"Updated template plist at {REPO_PLIST_PATH} to {formatted_time}")
        except Exception as t_err:
            logger.debug(f"Template plist update: {t_err}")

    # 2. Generate concrete user LaunchAgent plist for macOS launchd
    user_plist_data = build_user_launchd_plist(hour, minute)
    USER_LAUNCHAGENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_PLIST_PATH, "wb") as f:
        plistlib.dump(user_plist_data, f, fmt=plistlib.FMT_XML)
    logger.info(f"Updated user LaunchAgent at {USER_PLIST_PATH} to {formatted_time}")

    # 3. Update n8n workflow file if present
    if N8N_WORKFLOW_PATH.is_file():
        try:
            workflow = json.loads(N8N_WORKFLOW_PATH.read_text(encoding="utf-8"))
            for node in workflow.get("nodes", []):
                if node.get("type") == "n8n-nodes-base.scheduleTrigger":
                    node["name"] = f"Daily {formatted_time} Trigger"
                    node["parameters"] = {
                        "rule": {
                            "interval": [
                                {
                                    "field": "cronExpression",
                                    "expression": f"{minute} {hour} * * *"
                                }
                            ]
                        }
                    }
            N8N_WORKFLOW_PATH.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"Updated n8n workflow trigger to '{minute} {hour} * * *'")
        except Exception as exc:
            logger.warning(f"Failed to update n8n workflow file: {exc}")

    # 4. Reload launchctl
    reloaded = False
    try:
        # Unload first if already registered
        subprocess.run(["launchctl", "unload", "-w", str(USER_PLIST_PATH)], capture_output=True, check=False)
        # Load with new plist
        load_proc = subprocess.run(["launchctl", "load", "-w", str(USER_PLIST_PATH)], capture_output=True, text=True, check=False)
        if load_proc.returncode == 0:
            reloaded = True
            logger.info("Successfully reloaded launchd service via launchctl.")
        else:
            logger.warning(f"launchctl load warning: {load_proc.stderr.strip()}")
    except Exception as exc:
        logger.warning(f"Failed to reload launchctl: {exc}")

    status = get_schedule_status()
    status["action"] = "set_time"
    status["updated_time"] = formatted_time
    status["reloaded"] = reloaded
    return status


def enable_schedule() -> dict[str, Any]:
    """Generates the LaunchAgent plist for current user/repo and loads it into launchd."""
    hour, minute = 9, 0
    current_status = get_schedule_status()
    if current_status.get("hour") is not None:
        hour = current_status["hour"]
        minute = current_status.get("minute", 0)

    user_plist_data = build_user_launchd_plist(hour, minute)
    USER_LAUNCHAGENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_PLIST_PATH, "wb") as f:
        plistlib.dump(user_plist_data, f, fmt=plistlib.FMT_XML)

    subprocess.run(["launchctl", "unload", "-w", str(USER_PLIST_PATH)], capture_output=True, check=False)
    load_proc = subprocess.run(["launchctl", "load", "-w", str(USER_PLIST_PATH)], capture_output=True, text=True, check=False)
    success = (load_proc.returncode == 0)

    status = get_schedule_status()
    status["action"] = "enable"
    status["success"] = success
    return status


def disable_schedule() -> dict[str, Any]:
    """Unloads the LaunchAgent service from launchd."""
    if USER_PLIST_PATH.is_file():
        unload_proc = subprocess.run(["launchctl", "unload", "-w", str(USER_PLIST_PATH)], capture_output=True, text=True, check=False)
        success = (unload_proc.returncode == 0)
    else:
        success = True

    status = get_schedule_status()
    status["action"] = "disable"
    status["success"] = success
    return status


def format_schedule_status(status: dict[str, Any]) -> str:
    """Formats schedule status into a concise, readable output."""
    loaded_str = "🟢 已启用 (Loaded)" if status.get("loaded") else "⚪ 未启用 (Unloaded)"
    running_str = f"运行中 (PID: {status.get('pid')})" if status.get("running") else "待命中 (Idle)"
    last_exit = status.get("last_exit_code")
    exit_str = "正常 (0)" if last_exit == 0 else f"异常 ({last_exit})" if last_exit is not None else "无近期执行记录"

    lines = [
        "===========================================================",
        "  ⏰ Paper Daily 本地定时调度服务状态 (macOS launchd & n8n)",
        "===========================================================",
        f"  • 调度状态:     {loaded_str} - {running_str}",
        f"  • 定时时间:     每天上午 {status.get('scheduled_time')} (Hour: {status.get('hour')}, Minute: {status.get('minute')})",
        f"  • 最近执行状态: {exit_str}",
        f"  • 服务标识:     {status.get('label')}",
        f"  • 配置文件:     {status.get('user_plist')}",
        f"  • n8n 表达式:   {status.get('n8n_cron') or '未配置'}",
        f"  • 日志输出:     {status.get('log_stdout')}",
        "===========================================================",
    ]
    return "\n".join(lines)
