"""实例配置快照：保存、对比与回滚 AstrBot 配置 JSON。"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from . import fleet_store, store

SNAP_DIR = store.DATA_DIR / "snapshots"
KEEP = 20
MAX_CHANGES = 500


class SnapshotError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = str(message)
        self.status = int(status)


def _root(inst: dict) -> Path:
    root = Path(str(inst.get("root") or ""))
    if not root.is_dir():
        raise SnapshotError("实例目录不存在，无法读取配置", 404)
    return root


def _config_files(inst: dict) -> list[Path]:
    root = _root(inst)
    data = root / "data"
    files: list[Path] = []
    for name in ("cmd_config.json", "plugins.json", "skills.json"):
        path = data / name
        if path.is_file():
            files.append(path)
    config_dir = data / "config"
    if config_dir.is_dir():
        files.extend(sorted(path for path in config_dir.rglob("*.json") if path.is_file()))
    return files


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _safe_rel(value: str) -> str:
    rel = str(value or "").replace("\\", "/").lstrip("/")
    parts = [part for part in rel.split("/") if part and part != "."]
    if not parts or ".." in parts:
        raise SnapshotError("快照文件路径不合法")
    return "/".join(parts)


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= 300 else text[:297] + "..."


def create(inst: dict, label: str = "manual") -> dict:
    root = _root(inst)
    inst_id = str(inst.get("id") or "")
    files = {}
    total = 0
    for path in _config_files(inst):
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            raise SnapshotError(f"读取配置失败：{path.name}：{exc}") from exc
        files[_rel(root, path)] = content
        total += len(content.encode("utf-8"))
    if not files:
        raise SnapshotError("该实例没有可快照的配置文件")
    snapshot_id = f"cs_{uuid.uuid4().hex[:12]}"
    folder = SNAP_DIR / inst_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{snapshot_id}.json"
    payload = {
        "version": 1,
        "id": snapshot_id,
        "instance_id": inst_id,
        "created": time.time(),
        "label": str(label or "manual")[:40],
        "files": files,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with fleet_store.session() as conn:
        conn.execute(
            "INSERT INTO config_snapshots(id, instance_id, created, label, file_count, bytes, path) "
            "VALUES(?,?,?,?,?,?,?)",
            (snapshot_id, inst_id, payload["created"], payload["label"],
             len(files), total, str(target)),
        )
    _prune(inst_id)
    return {"id": snapshot_id, "created": payload["created"], "label": payload["label"],
            "files": len(files), "bytes": total}


def _prune(inst_id: str) -> None:
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT id, path FROM config_snapshots WHERE instance_id=? ORDER BY created DESC",
            (inst_id,),
        ).fetchall()
        for row in rows[KEEP:]:
            try:
                Path(row["path"]).unlink(missing_ok=True)
            except OSError:
                pass
            conn.execute("DELETE FROM config_snapshots WHERE id=?", (row["id"],))


def list_snapshots(inst: dict) -> list[dict]:
    inst_id = str(inst.get("id") or "")
    with fleet_store.session() as conn:
        rows = conn.execute(
            "SELECT id, created, label, file_count, bytes FROM config_snapshots "
            "WHERE instance_id=? ORDER BY created DESC",
            (inst_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load(inst: dict, snapshot_id: str) -> tuple[dict, dict]:
    inst_id = str(inst.get("id") or "")
    with fleet_store.session() as conn:
        row = conn.execute(
            "SELECT * FROM config_snapshots WHERE id=? AND instance_id=?",
            (snapshot_id, inst_id),
        ).fetchone()
    if row is None:
        raise SnapshotError("快照不存在", 404)
    path = Path(row["path"]).resolve()
    base = SNAP_DIR.resolve()
    if base not in path.parents or not path.is_file():
        raise SnapshotError("快照文件缺失", 404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"快照损坏：{exc}", 500) from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise SnapshotError("快照内容不合法", 500)
    return dict(row), data


def _diff_json(before, after, prefix: str, changes: list[dict]) -> None:
    if len(changes) >= MAX_CHANGES:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                changes.append({"path": path, "kind": "added", "before": None,
                                "after": _short(after[key])})
            elif key not in after:
                changes.append({"path": path, "kind": "removed",
                                "before": _short(before[key]), "after": None})
            else:
                _diff_json(before[key], after[key], path, changes)
        return
    if before != after:
        changes.append({
            "path": prefix or "(root)",
            "kind": "changed",
            "before": _short(before),
            "after": _short(after),
        })


def diff(inst: dict, from_id: str, to_id: str) -> dict:
    _, left = _load(inst, from_id)
    _, right = _load(inst, to_id)
    left_files = {str(k): v for k, v in left.get("files", {}).items()}
    right_files = {str(k): v for k, v in right.get("files", {}).items()}
    added = sorted(set(right_files) - set(left_files))
    removed = sorted(set(left_files) - set(right_files))
    files = []
    changes = 0
    for name in sorted(set(left_files) & set(right_files)):
        if left_files[name] == right_files[name]:
            continue
        file_changes: list[dict] = []
        try:
            before = json.loads(left_files[name])
            after = json.loads(right_files[name])
        except (TypeError, ValueError):
            before, after = left_files[name], right_files[name]
        _diff_json(before, after, "", file_changes)
        if not file_changes:
            file_changes.append({"path": "(文件)", "kind": "changed",
                                 "before": _short(left_files[name]),
                                 "after": _short(right_files[name])})
        changes += len(file_changes)
        files.append({"file": name, "changes": file_changes})
    return {
        "from": from_id,
        "to": to_id,
        "added": added,
        "removed": removed,
        "files": files,
        "changes": changes,
        "truncated": changes >= MAX_CHANGES,
    }


def restore(inst: dict, snapshot_id: str, files: list[str] | None = None,
            confirm: str = "") -> dict:
    if str(confirm or "").upper() != "RESTORE":
        raise SnapshotError("回滚需要 confirm=RESTORE")
    _, data = _load(inst, snapshot_id)
    root = _root(inst)
    available = data.get("files") or {}
    selected = [_safe_rel(item) for item in files] if files else list(available)
    missing = [item for item in selected if item not in available]
    if missing:
        raise SnapshotError(f"快照中不存在这些文件：{', '.join(missing[:5])}")
    rollback = create(inst, label="pre-restore")
    restored = 0
    for rel in selected:
        target = (root / rel).resolve()
        if root.resolve() not in target.parents:
            raise SnapshotError(f"回滚目标越界：{rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".snap-tmp")
        tmp.write_text(str(available[rel]), encoding="utf-8")
        os.replace(tmp, target)
        restored += 1
    return {"restored": restored, "rollback": rollback["id"],
            "files": selected[:20], "snapshot": snapshot_id}


def delete(inst: dict, snapshot_id: str) -> dict:
    _row, _data = _load(inst, snapshot_id)
    inst_id = str(inst.get("id") or "")
    with fleet_store.session() as conn:
        row = conn.execute(
            "SELECT path FROM config_snapshots WHERE id=? AND instance_id=?",
            (snapshot_id, inst_id),
        ).fetchone()
        if row:
            try:
                Path(row["path"]).unlink(missing_ok=True)
            except OSError:
                pass
            conn.execute("DELETE FROM config_snapshots WHERE id=?", (snapshot_id,))
    return {"deleted": snapshot_id}
