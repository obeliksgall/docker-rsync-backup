import os
import sys
import json
import time
import signal
import subprocess
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

# Globalne flagi sterujące stanem aplikacji
running_processes = {}
exiting = False
scheduler = None

def log(message, level="INFO", task_name="SYSTEM"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] [{task_name}] {message}"
    print(log_line, flush=True)
    
    # Zapis logów do dedykowanych plików
    log_dir = "/app/logs"
    os.makedirs(log_dir, exist_ok=True)
    filename = "app.log" if task_name == "SYSTEM" else f"task_{task_name.replace(' ', '_')}.log"
    with open(os.path.join(log_dir, filename), "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

def send_discord(webhook_url, content, task_name, level="INFO"):
    if not webhook_url or "discord.com" not in webhook_url:
        return
    colors = {"INFO": 5814783, "SUCCESS": 3066993, "ERROR": 15158332, "WARNING": 16743168}
    embed = {
        "title": f"Task: {task_name}",
        "description": content,
        "color": colors.get(level, 5814783),
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        log(f"Failed to send Discord notification: {e}", "ERROR")

def run_rsync_task(task, general_config):
    global exiting
    task_name = task["name"]
    
    if exiting:
        log("System is shutting down. Task skipped.", "WARNING", task_name)
        return

    # 1. Walidacja obecności punktów montowania (Healthcheck)
    if not os.path.exists(task["source"]) or not os.path.exists(task["dest"]):
        msg = f"Validation failed! Source '{task['source']}' or Destination '{task['dest']}' does not exist."
        log(msg, "ERROR", task_name)
        if general_config.get("notification_level") in ["all", "errors_only"]:
            send_discord(general_config.get("discord_webhook_url"), msg, task_name, "ERROR")
        return

    # 2. Blokowanie jednoczesnego wykonania tej samej konfiguracji (Locking)
    lock_file = f"/tmp/task_{task_name.replace(' ', '_')}.lock"
    if os.path.exists(lock_file):
        log("Task is already running. Skipping this execution.", "WARNING", task_name)
        return
        
    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    log("Starting rsync job...", "INFO", task_name)
    if general_config.get("notification_level") == "all":
        send_discord(general_config.get("discord_webhook_url"), "Job started.", task_name, "INFO")

    # 3. Formowanie komendy rsync
    rsync_cmd = ["rsync", "-avh", "--stats"]
    
    if task["type"] == "mirror":
        rsync_cmd.append("--delete")
    elif task["type"] == "incremental":
        pass 
    elif task["type"] == "move":
        rsync_cmd.append("--remove-source-files")

    for exc in task.get("exclude", []):
        rsync_cmd.append(f"--exclude={exc}")

    if task.get("extra_rsync_flags"):
        rsync_cmd.extend(task["extra_rsync_flags"].split())

    src = task["source"] if task["source"].endswith("/") else task["source"] + "/"
    rsync_cmd.extend([src, task["dest"]])

    # 4. Wywołanie procesu
    try:
        process = subprocess.Popen(rsync_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        running_processes[task_name] = process
        stdout, stderr = process.communicate()
    except Exception as e:
        stdout, stderr = "", str(e)
    finally:
        running_processes.pop(task_name, None)
        if os.path.exists(lock_file):
            os.remove(lock_file)

    # 5. Interpretacja rezultatu operacji
    if exiting:
        log("Task interrupted by system shutdown.", "WARNING", task_name)
        send_discord(general_config.get("discord_webhook_url"), "Job interrupted by container shutdown.", task_name, "WARNING")
        return

    if process.returncode != 0:
        log(f"Rsync failed with exit code {process.returncode}. Error: {stderr}", "ERROR", task_name)
        if general_config.get("notification_level") in ["all", "errors_only"]:
            send_discord(general_config.get("discord_webhook_url"), f"Job failed!\nError: {stderr[:500]}", task_name, "ERROR")
    else:
        stats = {"files_transferred": "0", "bytes_transferred": "0"}
        for line in stdout.splitlines():
            if "Number of regular files transferred:" in line:
                stats["files_transferred"] = line.split(":")[-1].strip()
            if "Total transferred file size:" in line:
                stats["bytes_transferred"] = line.split(":")[-1].strip()
                
        success_msg = f"Job finished successfully.\nTransferred files: {stats['files_transferred']}\nTotal size: {stats['bytes_transferred']}"
        log(success_msg.replace("\n", " | "), "SUCCESS", task_name)
        
        if general_config.get("notification_level") == "all":
            send_discord(general_config.get("discord_webhook_url"), success_msg, task_name, "SUCCESS")

def load_config():
    try:
        with open("/app/config/config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Error reading configuration file: {e}", "ERROR")
        return None

def ensure_config_exists(config_path):
    if not os.path.exists(config_path):
        log("Configuration file not found! Creating a template config.json...", "WARNING")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        template = {
            "general": {
                "discord_webhook_url": "YOUR_DISCORD_WEBHOOK_HERE",
                "notification_level": "all",
                "config_check_interval_seconds": 10,
                "default_scheduler": "0 2 * * *",
                "max_concurrent_tasks": 1
            },
            "tasks": [
                {
                    "name": "Example Task",
                    "enabled": False,
                    "type": "incremental",
                    "source": "/source/example",
                    "dest": "/dest/example",
                    "scheduler": "*/5 * * * *",
                    "exclude": ["@Recycle", "@eaDir", ".DS_Store", "Thumbs.db"],
                    "extra_rsync_flags": ""
                }
            ]
        }
        
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
            log("Template config.json created successfully. Please adjust it.", "INFO")
        except Exception as e:
            log(f"Failed to create template configuration file: {e}", "ERROR")

def handle_shutdown(signum, frame):
    global exiting
    log("Received shutdown signal. Stopping active tasks gracefully...", "WARNING")
    exiting = True
    
    if scheduler:
        scheduler.shutdown(wait=False)
        
    for name, proc in list(running_processes.items()):
        log(f"Terminating rsync process for task: {name}", "WARNING")
        proc.terminate()
        
    sys.exit(0)

def main():
    global scheduler
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    config_path = "/app/config/config.json"
    
    # Weryfikacja obecności pliku konfiguracyjnego przed startem logiki biznesowej
    ensure_config_exists(config_path)

    log("Starting Docker Backup Service...", "INFO")
    
    current_config = None
    last_config_mtime = 0
    
    # Inicjalne wczytanie konfiguracji w celu ustalenia liczby workerów
    config_loaded = load_config()
    max_workers = 1
    if config_loaded:
        current_config = config_loaded
        max_workers = current_config.get("general", {}).get("max_concurrent_tasks", 1)
        log(f"Setting maximum concurrent tasks limit to: {max_workers}", "INFO")

    # Uruchomienie zarządcy zadań z dynamicznym limitem zasobów
    executors = {'default': ThreadPoolExecutor(max_workers=max_workers)}
    scheduler = BackgroundScheduler(executors=executors)
    scheduler.start()
    
    # Pierwsza rejestracja zadań
    if current_config:
        last_config_mtime = os.path.getmtime(config_path) if os.path.exists(config_path) else time.time()
        register_tasks(current_config)

    while not exiting:
        try:
            if os.path.exists(config_path):
                mtime = os.path.getmtime(config_path)
                if mtime > last_config_mtime:
                    log("Configuration change detected. Reloading tasks...", "INFO")
                    new_config = load_config()
                    if new_config:
                        current_config = new_config
                        last_config_mtime = mtime
                        
                        # Sprawdzenie czy zmienił się parametr max_concurrent_tasks
                        new_max = current_config.get("general", {}).get("max_concurrent_tasks", 1)
                        if new_max != max_workers:
                            max_workers = new_max
                            log(f"Updating concurrent tasks limit to: {max_workers}. Restarting scheduler...", "WARNING")
                            scheduler.shutdown()
                            executors = {'default': ThreadPoolExecutor(max_workers=max_workers)}
                            scheduler = BackgroundScheduler(executors=executors)
                            scheduler.start()

                        register_tasks(current_config)
            
            interval = current_config.get("general", {}).get("config_check_interval_seconds", 30) if current_config else 10
            time.sleep(interval)
        except Exception as e:
            log(f"Main loop error: {e}", "ERROR")
            time.sleep(10)

def register_tasks(config):
    scheduler.remove_all_jobs()
    gen = config.get("general", {})
    
    for task in config.get("tasks", []):
        if not task.get("enabled", True):
            continue
        
        cron_expr = task.get("scheduler") or gen.get("default_scheduler", "0 2 * * *")
        cron_parts = cron_expr.split()
        if len(cron_parts) == 5:
            scheduler.add_job(
                run_rsync_task,
                'cron',
                minute=cron_parts[0],
                hour=cron_parts[1],
                day=cron_parts[2],
                month=cron_parts[3],
                day_of_week=cron_parts[4],
                args=[task, gen],
                id=task["name"],
                misfire_grace_time=None,
                coalesce=True
            )
            log(f"Scheduled task '{task['name']}' with cron: {cron_expr}")

if __name__ == "__main__":
    main()