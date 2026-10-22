"""SQLite + 文件目录存储。单用户本地，元数据入库、二进制走文件。"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "app.db"
        self.projects_dir = self.data_dir / "projects"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY, value TEXT
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    canvas_w INTEGER NOT NULL, canvas_h INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
                    filename TEXT NOT NULL, path TEXT NOT NULL,
                    width INTEGER, height INTEGER, sha256 TEXT, thumb_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS layers (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, type TEXT NOT NULL,
                    name TEXT NOT NULL, z INTEGER NOT NULL DEFAULT 0,
                    x REAL DEFAULT 0, y REAL DEFAULT 0, w REAL DEFAULT 0, h REAL DEFAULT 0,
                    opacity REAL NOT NULL DEFAULT 1.0,
                    visible INTEGER NOT NULL DEFAULT 1,
                    locked INTEGER NOT NULL DEFAULT 0,
                    blend TEXT NOT NULL DEFAULT 'normal',
                    content TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, params TEXT NOT NULL,
                    status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT 'loading_model',
                    result_asset_ids TEXT NOT NULL DEFAULT '[]',
                    error TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    layers TEXT NOT NULL, created_at TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'auto'
                );
                """
            )
            layer_columns = {row["name"] for row in c.execute("PRAGMA table_info(layers)")}
            if "rotation" not in layer_columns:
                c.execute("ALTER TABLE layers ADD COLUMN rotation REAL NOT NULL DEFAULT 0")
            c.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # ---------- 项目 ----------
    def create_project(self, name: str, canvas_w: int, canvas_h: int) -> Dict[str, Any]:
        pid = new_id("p")
        now = now_iso()
        # 同目录重名自动加 -1
        name = self._unique_project_name(name)
        with self._conn() as c:
            c.execute(
                "INSERT INTO projects(id, name, canvas_w, canvas_h, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                (pid, name, canvas_w, canvas_h, now, now),
            )
        return self.get_project(pid)

    def _unique_project_name(self, name: str, exclude_pid: Optional[str] = None) -> str:
        with self._conn() as c:
            existing = {
                row["name"]
                for row in c.execute(
                    "SELECT id, name FROM projects"
                ).fetchall()
                if row["id"] != exclude_pid
            }
        candidate = name
        i = 1
        while candidate in existing:
            candidate = f"{name}-{i}"
            i += 1
        return candidate

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self._project_from_row(r) for r in rows]

    def get_project(self, pid: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return self._project_from_row(row) if row else None

    def update_project(self, pid: str, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            cur = c.execute("SELECT * FROM projects WHERE id=?", (pid,))
            row = cur.fetchone()
            if not row:
                return None
            new_name = self._unique_project_name(name, pid) if name else row["name"]
            c.execute(
                "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                (new_name, now_iso(), pid),
            )
        return self.get_project(pid)

    def delete_project(self, pid: str) -> bool:
        with self._conn() as c:
            c.execute("DELETE FROM generations WHERE project_id=?", (pid,))
            c.execute("DELETE FROM layers WHERE project_id=?", (pid,))
            c.execute("DELETE FROM assets WHERE project_id=?", (pid,))
            cur = c.execute("DELETE FROM projects WHERE id=?", (pid,))
        # 连同文件
        import shutil

        shutil.rmtree(self.projects_dir / pid, ignore_errors=True)
        return cur.rowcount > 0

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "canvas": {"w": row["canvas_w"], "h": row["canvas_h"]},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ---------- 素材 ----------
    def write_asset_file(self, project_id: str, asset_id: str, data: bytes, suffix: str) -> str:
        adir = self.projects_dir / project_id / "assets"
        adir.mkdir(parents=True, exist_ok=True)
        path = adir / f"{asset_id}{suffix}"
        path.write_bytes(data)
        return str(path)

    def write_thumb(self, project_id: str, asset_id: str, data: bytes) -> str:
        adir = self.projects_dir / project_id / "assets"
        adir.mkdir(parents=True, exist_ok=True)
        path = adir / f"{asset_id}.thumb.png"
        path.write_bytes(data)
        return str(path)

    def add_asset(
        self,
        project_id: str,
        kind: str,
        filename: str,
        path: str,
        width: Optional[int],
        height: Optional[int],
        sha256: Optional[str],
        thumb_path: Optional[str] = None,
        asset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        aid = asset_id or new_id("a")
        with self._conn() as c:
            c.execute(
                "INSERT INTO assets(id, project_id, kind, filename, path, width, height, sha256, thumb_path, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (aid, project_id, kind, filename, path, width, height, sha256, thumb_path, now_iso()),
            )
        return self.get_asset(aid)

    def get_asset(self, aid: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
        return self._asset_from_row(row) if row else None

    def list_assets(self, project_id: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM assets WHERE project_id=? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._asset_from_row(r) for r in rows]

    def delete_asset(self, aid: str) -> bool:
        asset = self.get_asset(aid)
        if not asset:
            return False
        with self._conn() as c:
            c.execute("DELETE FROM assets WHERE id=?", (aid,))
        import os

        for p in (asset["path"], asset["thumb_path"]):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return True

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "kind": row["kind"],
            "filename": row["filename"],
            "path": row["path"],
            "width": row["width"],
            "height": row["height"],
            "sha256": row["sha256"],
            "thumb_path": row["thumb_path"],
            "created_at": row["created_at"],
        }

    # ---------- 图层 ----------
    def replace_layers(self, project_id: str, layers: List[Dict[str, Any]]) -> None:
        saved_at = now_iso()
        snapshot_layers = []
        with self._conn() as c:
            c.execute("DELETE FROM layers WHERE project_id=?", (project_id,))
            for layer in layers:
                created_at = layer.get("created_at") or saved_at
                updated_at = layer.get("updated_at") or saved_at
                c.execute(
                    "INSERT INTO layers(id, project_id, type, name, z, x, y, w, h, rotation, opacity, visible, locked, blend, content, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        layer["id"],
                        project_id,
                        layer["type"],
                        layer.get("name", ""),
                        layer.get("z", 0),
                        layer.get("x", 0),
                        layer.get("y", 0),
                        layer.get("w", 0),
                        layer.get("h", 0),
                        layer.get("rotation", 0),
                        layer.get("opacity", 1.0),
                        1 if layer.get("visible", True) else 0,
                        1 if layer.get("locked", False) else 0,
                        layer.get("blend", "normal"),
                        json.dumps(layer.get("content", {}), ensure_ascii=False),
                        created_at,
                        updated_at,
                    ),
                )
                snapshot_layers.append(
                    {
                        **layer,
                        "project_id": project_id,
                        "name": layer.get("name", ""),
                        "z": layer.get("z", 0),
                        "x": layer.get("x", 0),
                        "y": layer.get("y", 0),
                        "w": layer.get("w", 0),
                        "h": layer.get("h", 0),
                        "rotation": layer.get("rotation", 0),
                        "opacity": layer.get("opacity", 1.0),
                        "visible": layer.get("visible", True),
                        "locked": layer.get("locked", False),
                        "blend": layer.get("blend", "normal"),
                        "content": layer.get("content", {}),
                        "created_at": created_at,
                        "updated_at": updated_at,
                    }
                )
            c.execute(
                "UPDATE projects SET updated_at=? WHERE id=?",
                (saved_at, project_id),
            )
            c.execute(
                "INSERT INTO snapshots(id, project_id, layers, created_at, reason) VALUES(?,?,?,?,?)",
                (
                    new_id("s"),
                    project_id,
                    json.dumps(snapshot_layers, ensure_ascii=False),
                    saved_at,
                    "auto",
                ),
            )
            c.execute(
                "DELETE FROM snapshots WHERE project_id=? AND id NOT IN "
                "(SELECT id FROM snapshots WHERE project_id=? ORDER BY created_at DESC LIMIT 20)",
                (project_id, project_id),
            )

    def latest_valid_snapshot(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, layers, created_at, reason FROM snapshots "
                "WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
                (project_id,),
            ).fetchall()
        for row in rows:
            try:
                layers = json.loads(row["layers"])
                if not isinstance(layers, list):
                    continue
                valid = True
                for layer in layers:
                    layer.setdefault("rotation", 0)
                    if layer.get("type") != "image":
                        continue
                    asset_id = (layer.get("content") or {}).get("asset_id")
                    if not asset_id:
                        continue
                    asset = self.get_asset(asset_id)
                    if asset is None or not Path(asset["path"]).is_file():
                        valid = False
                        break
                if valid:
                    return {
                        "id": row["id"],
                        "layers": layers,
                        "created_at": row["created_at"],
                        "reason": row["reason"],
                    }
            except (TypeError, ValueError, KeyError):
                continue
        return None

    def get_layers(self, project_id: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM layers WHERE project_id=? ORDER BY z ASC", (project_id,)
            ).fetchall()
        return [self._layer_from_row(r) for r in rows]

    @staticmethod
    def _layer_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "type": row["type"],
            "name": row["name"],
            "z": row["z"],
            "x": row["x"],
            "y": row["y"],
            "w": row["w"],
            "h": row["h"],
            "rotation": row["rotation"],
            "opacity": row["opacity"],
            "visible": bool(row["visible"]),
            "locked": bool(row["locked"]),
            "blend": row["blend"],
            "content": json.loads(row["content"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ---------- 任务 ----------
    def create_generation(self, project_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        gid = new_id("g")
        with self._conn() as c:
            c.execute(
                "INSERT INTO generations(id, project_id, params, status, created_at) VALUES(?,?,?,?,?)",
                (gid, project_id, json.dumps(params, ensure_ascii=False), "queued", now_iso()),
            )
        return self.get_generation(gid)

    def update_generation(self, gid: str, **fields: Any) -> None:
        self._update_generation(gid, None, **fields)

    def update_generation_if_status(
        self, gid: str, expected_statuses: tuple[str, ...], **fields: Any
    ) -> bool:
        if not expected_statuses:
            return False
        return self._update_generation(gid, expected_statuses, **fields)

    def _update_generation(
        self, gid: str, expected_statuses: Optional[tuple[str, ...]], **fields: Any
    ) -> bool:
        allowed = {
            "status", "progress", "stage", "result_asset_ids", "error",
            "started_at", "finished_at",
        }
        sets = []
        values = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "result_asset_ids":
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k}=?")
            values.append(v)
        if not sets:
            return False
        values.append(gid)
        where = "id=?"
        if expected_statuses is not None:
            where += f" AND status IN ({','.join('?' for _ in expected_statuses)})"
            values.extend(expected_statuses)
        with self._conn() as c:
            cursor = c.execute(f"UPDATE generations SET {', '.join(sets)} WHERE {where}", values)
        return cursor.rowcount > 0

    def get_generation(self, gid: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM generations WHERE id=?", (gid,)).fetchone()
        return self._generation_from_row(row) if row else None

    def list_generations(self, project_id: str) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM generations WHERE project_id=? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._generation_from_row(r) for r in rows]

    def list_generations_by_status(self, statuses: List[str]) -> List[Dict[str, Any]]:
        placeholders = ",".join("?" * len(statuses))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM generations WHERE status IN ({placeholders}) ORDER BY created_at ASC",
                statuses,
            ).fetchall()
        return [self._generation_from_row(r) for r in rows]

    @staticmethod
    def _generation_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "params": json.loads(row["params"]),
            "status": row["status"],
            "progress": row["progress"],
            "stage": row["stage"],
            "result_asset_ids": json.loads(row["result_asset_ids"] or "[]"),
            "error": row["error"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
