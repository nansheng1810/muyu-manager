"""只读资源看板：系统、管理器和机器人进程树的 CPU/内存。"""

from __future__ import annotations

import os
import shutil
import time
from collections import Counter

import psutil

from . import runner as runner_mod, store


def _process_rows(pid: int | None) -> dict:
    if not pid:
        return {"pid": None, "cpu_percent": 0.0, "memory_mb": 0.0, "processes": 0, "names": {}}
    try:
        root = psutil.Process(int(pid))
        processes = [root, *root.children(recursive=True)]
    except (psutil.Error, ValueError):
        return {"pid": pid, "cpu_percent": 0.0, "memory_mb": 0.0, "processes": 0, "names": {}}
    cpu = 0.0
    memory = 0.0
    names: Counter[str] = Counter()
    for proc in processes:
        try:
            proc.cpu_percent(interval=None)
        except (psutil.Error, ValueError):
            continue
    time.sleep(0.12)
    for proc in processes:
        try:
            cpu += max(0.0, proc.cpu_percent(interval=None))
            memory += max(0, proc.memory_info().rss)
            names[proc.name()] += 1
        except (psutil.Error, ValueError):
            continue
    return {
        "pid": int(pid),
        "cpu_percent": round(cpu, 1),
        "memory_mb": round(memory / 1024 / 1024, 1),
        "processes": len(processes),
        "names": dict(names.most_common(8)),
    }


def collect(instances: list[dict] | None = None) -> dict:
    system_cpu = psutil.cpu_percent(interval=0.15)
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(store.DATA_DIR)
    manager = _process_rows(os.getpid())
    manager["started_at"] = psutil.Process(os.getpid()).create_time()
    rows = []
    for inst in (instances if instances is not None else store.load_instances()):
        status = runner_mod.runner.status(inst)
        row = {
            "id": str(inst.get("id") or ""),
            "name": str(inst.get("name") or inst.get("id") or ""),
            "online": bool(status.get("running")),
            "managed": bool(status.get("managed")),
        }
        row.update(_process_rows(status.get("pid") if status.get("running") else None))
        rows.append(row)
    return {
        "generated_at": time.time(),
        "system": {
            "cpu_percent": round(system_cpu, 1),
            "memory_percent": round(memory.percent, 1),
            "memory_used_gb": round(memory.used / 1024 ** 3, 2),
            "memory_total_gb": round(memory.total / 1024 ** 3, 2),
            "disk_free_gb": round(disk.free / 1024 ** 3, 2),
            "disk_total_gb": round(disk.total / 1024 ** 3, 2),
            "disk_percent_free": round(disk.free / disk.total * 100, 1) if disk.total else 0.0,
        },
        "manager": manager,
        "instances": rows,
    }
