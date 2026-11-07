"""一键备份与灾备：zip + manifest + sha256，恢复前自动快照。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from . import dsh, fleet_store, store

BACKUP_DIR = store.DATA_DIR / "backups"
KEEP = 7
MANIFEST = "manifest.json"
VALID_COMPONENTS = {"manager", "instances", "dsh", "login"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_rel(path: Path, base: Path) -> str:
    return str(path.relative_to(base)).replace("\\", "/")


def _manager_entries() -> list[tuple[Path, str, str, str]]:
    entries: list[tuple[Path, str, str, str]] = []
    names = ["settings.json", "instances.json", "dsh_runtime.json", "dsh-runtime-overlay.yml"]
    for name in names:
        path = store.DATA_DIR / name
        if path.exists():
            entries.append((path, f"manager/{name}", "manager", name))
    db_path = fleet_store.DB_PATH
    if db_path.exists():
        fd, name = tempfile.mkstemp(prefix="fleet-ops-", suffix=".sqlite3")
        os.close(fd)
        tmp = Path(name)
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        entries.append((tmp, "manager/fleet_ops.sqlite3", "manager", "fleet_ops.sqlite3"))
    return entries


def _instance_entries(instances: list[dict], include_login: bool) -> list[tuple[Path, str, str, str]]:
    entries: list[tuple[Path, str, str, str]] = []
    for inst in instances:
        inst_id = str(inst.get("id") or "")
        root = Path(str(inst.get("root") or ""))
        if not inst_id or not root.is_dir():
            continue
        data = root / "data"
        candidates = [
            (data / "cmd_config.json", "data/cmd_config.json"),
            (data / "config", "data/config"),
            (data / "plugin_data", "data/plugin_data"),
            (data / "skills", "data/skills"),
        ]
        for db_name in ("data_v4.db", "astrbot.db"):
            db_path = data / db_name
            if not db_path.is_file():
                continue
            fd, temp_name = tempfile.mkstemp(prefix="fleet-ops-", suffix=".sqlite3")
            os.close(fd)
            temp_path = Path(temp_name)
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(temp_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            entries.append((temp_path, f"instances/{inst_id}/data/{db_name}", "instance", f"data/{db_name}"))
        for source, rel in candidates:
            if not source.exists():
                continue
            if source.is_file():
                entries.append((source, f"instances/{inst_id}/{rel}", "instance", rel))
                continue
            for path in source.rglob("*"):
                if not path.is_file():
                    continue
                rel_path = _safe_rel(path, root)
                if not include_login and any(part.startswith("browser-profile") for part in path.parts):
                    continue
                entries.append((path, f"instances/{inst_id}/{rel_path}", "instance", rel_path))
    return entries


def _dsh_entries() -> list[tuple[Path, str, str, str]]:
    entries: list[tuple[Path, str, str, str]] = []
    try:
        home = dsh.resolve_home()
    except Exception:  # noqa: BLE001
        return entries
    profile = home / "profiles" / dsh.PROFILE
    candidates = [profile / "package.json", profile / "cordis.patch.yml", profile / "settings.yaml", home / "settings.yaml"]
    for source in candidates:
        if source.is_file():
            entries.append((source, f"dsh/{_safe_rel(source, home)}", "dsh", _safe_rel(source, home)))
    skills = home / "skills"
    if skills.is_dir():
        for path in skills.rglob("*"):
            if path.is_file():
                rel = _safe_rel(path, home)
                entries.append((path, f"dsh/{rel}", "dsh", rel))
    return entries


def _collect(components: set[str], include_login: bool,
             instances: list[dict] | None = None) -> list[tuple[Path, str, str, str]]:
    entries: list[tuple[Path, str, str, str]] = []
    if "manager" in components:
        entries.extend(_manager_entries())
    if "instances" in components:
        entries.extend(_instance_entries(instances if instances is not None else store.load_instances(), include_login))
    if "dsh" in components:
        entries.extend(_dsh_entries())
    return entries


def create(components: list[str] | None = None, include_login: bool = False,
           label: str = "manual", instances: list[dict] | None = None) -> dict:
    selected = {c for c in (components or ["manager", "instances", "dsh"]) if c in VALID_COMPONENTS}
    if not selected:
        selected = {"manager"}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(ch for ch in str(label or "manual") if ch.isalnum() or ch in "-_")[:24] or "manual"
    target = BACKUP_DIR / f"fleet-backup-{stamp}-{safe_label}.zip"
    entries = _collect(selected, include_login, instances)
    manifest = {
        "version": 1,
        "created": time.time(),
        "components": sorted(selected),
        "include_login": bool(include_login),
        "files": [],
    }
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source, arcname, scope, dest in entries:
            archive.write(source, arcname)
            manifest["files"].append({
                "arcname": arcname,
                "scope": scope,
                "dest": dest,
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            })
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
    for source, _arcname, _scope, _dest in entries:
        if source.parent == Path(tempfile.gettempdir()) and source.name.startswith("fleet-ops-"):
            source.unlink(missing_ok=True)
    digest = _sha256(target)
    (target.with_suffix(target.suffix + ".sha256")).write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    _record(target, manifest, digest)
    _prune()
    return {"path": str(target), "bytes": target.stat().st_size, "sha256": digest,
            "files": len(manifest["files"]), "components": manifest["components"]}


def _record(target: Path, manifest: dict, digest: str) -> None:
    try:
        with fleet_store.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO backups(id, created, path, bytes, sha256, components_json, status) "
                "VALUES(?,?,?,?,?,?,?)",
                (target.stem, manifest["created"], str(target), target.stat().st_size, digest,
                 json.dumps(manifest["components"], ensure_ascii=False), "ok"),
            )
    except Exception:  # noqa: BLE001
        pass


def _prune() -> None:
    files = sorted(BACKUP_DIR.glob("fleet-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[KEEP:]:
        try:
            path.unlink()
            path.with_suffix(path.suffix + ".sha256").unlink(missing_ok=True)
        except OSError:
            pass


def list_backups() -> list[dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(BACKUP_DIR.glob("fleet-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        sha_file = path.with_suffix(path.suffix + ".sha256")
        sha = ""
        if sha_file.exists():
            sha = sha_file.read_text(encoding="utf-8").split()[0]
        items.append({
            "name": path.name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "created": path.stat().st_mtime,
            "sha256": sha,
        })
    return items


def _safe_backup_path(value: str) -> Path:
    path = Path(value).resolve()
    base = BACKUP_DIR.resolve()
    if base not in path.parents and path != base:
        raise ValueError("备份路径不在备份目录内")
    if path.suffix != ".zip" or not path.is_file():
        raise ValueError("备份文件不存在")
    return path


def verify(path_value: str) -> dict:
    path = _safe_backup_path(path_value)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            bad = []
            for item in manifest.get("files", []):
                try:
                    data = archive.read(item["arcname"])
                except KeyError:
                    bad.append(item["arcname"])
                    continue
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    bad.append(item["arcname"])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "path": str(path)}
    return {"ok": not bad, "path": str(path), "files": len(manifest.get("files", [])),
            "bad": bad[:20], "created": manifest.get("created"), "components": manifest.get("components", [])}


def rehearse(path_value: str) -> dict:
    """把备份解压到临时目录并校验，不触碰运行中的配置。"""
    path = _safe_backup_path(path_value)
    check = verify(path_value)
    if not check.get("ok"):
        raise ValueError(f"备份校验失败：{check.get('error') or check.get('bad')}")
    started = time.perf_counter()
    staging = Path(tempfile.mkdtemp(prefix="fleet-restore-drill-"))
    written = 0
    bytes_written = 0
    json_checked = 0
    json_bad = []
    sqlite_result = None
    warnings = []
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            for item in manifest.get("files", []):
                arcname = str(item.get("arcname") or "")
                target = (staging / arcname).resolve()
                if staging.resolve() not in target.parents and target != staging.resolve():
                    raise ValueError(f"演练解压越界：{arcname}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(arcname) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
                written += 1
                bytes_written += target.stat().st_size
                if target.suffix.lower() == ".json":
                    json_checked += 1
                    try:
                        json.loads(target.read_text(encoding="utf-8-sig"))
                    except (OSError, ValueError) as exc:
                        json_bad.append({"file": arcname, "error": str(exc)[:160]})
                if target.name == "fleet_ops.sqlite3":
                    try:
                        conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
                        try:
                            row = conn.execute("PRAGMA integrity_check").fetchone()
                            sqlite_result = str(row[0] if row else "unknown")
                        finally:
                            conn.close()
                    except sqlite3.Error as exc:
                        sqlite_result = f"error: {exc}"
        if json_bad:
            warnings.append(f"{len(json_bad)} 个 JSON 文件无法解析")
        if sqlite_result and sqlite_result != "ok":
            warnings.append("fleet_ops.sqlite3 完整性检查未通过")
        return {
            "ok": not json_bad and (sqlite_result in (None, "ok")),
            "path": str(path),
            "name": path.name,
            "files": written,
            "bytes": bytes_written,
            "json_checked": json_checked,
            "json_bad": json_bad[:20],
            "sqlite": sqlite_result,
            "warnings": warnings,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _base_for(scope: str, dest: str, instances: list[dict]) -> Path | None:
    if scope == "manager":
        return store.DATA_DIR
    if scope == "dsh":
        try:
            return dsh.resolve_home()
        except Exception:  # noqa: BLE001
            return None
    if scope in {"instance", "login"}:
        inst_id = dest.split("/", 1)[0] if dest.startswith("instances/") else ""
        for inst in instances:
            if str(inst.get("id")) == inst_id:
                return Path(str(inst.get("root") or ""))
        return None
    return None


def restore(path_value: str, confirm: str = "", instances: list[dict] | None = None) -> dict:
    if str(confirm or "").upper() != "RESTORE":
        raise ValueError("恢复需要 confirm=RESTORE")
    check = verify(path_value)
    if not check.get("ok"):
        raise ValueError(f"备份校验失败：{check.get('error') or check.get('bad')}")
    path = _safe_backup_path(path_value)
    insts = instances if instances is not None else store.load_instances()
    rollback = create(["manager", "instances", "dsh"], include_login=False, label="pre-restore", instances=insts)
    restored = 0
    staging = BACKUP_DIR / f"staging-{int(time.time())}"
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
        for item in manifest.get("files", []):
            arcname = item["arcname"]
            dest_rel = item["dest"]
            scope = item["scope"]
            if scope == "manager":
                base = store.DATA_DIR
            elif scope == "dsh":
                base = _base_for("dsh", dest_rel, insts)
            else:
                parts = arcname.split("/", 3)
                inst_id = parts[1] if len(parts) > 2 else ""
                inst = next((i for i in insts if str(i.get("id")) == inst_id), None)
                base = Path(str(inst.get("root") or "")) if inst else None
                dest_rel = "/".join(parts[2:])
            if base is None:
                continue
            target = (base / dest_rel).resolve()
            if base.resolve() not in target.parents and target != base.resolve():
                raise ValueError(f"恢复目标越界：{dest_rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".restore-tmp")
            with archive.open(arcname) as src, tmp.open("wb") as out:
                shutil.copyfileobj(src, out)
            os.replace(tmp, target)
            restored += 1
    shutil.rmtree(staging, ignore_errors=True)
    return {"restored": restored, "rollback": rollback, "source": str(path)}
