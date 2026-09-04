"""HTTP API and single-page UI for the save library.

The server owns a saves folder and a :class:`~on_savior_ui.store.MetadataStore`;
everything the browser does goes through ``/api``. Listing never opens a save
zip, so the index stays fast over the network — the detail endpoint is the only
one that pays that cost, and only for the save being inspected.

Writes are gated twice: the client asks, and the server must have been started
with the matching permission (``allow_delete`` for deletion and auto-rotate,
``archive_dir`` for archiving). The browser is told which are available so it
can hide what it cannot do.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ..catalog import Library, SaveRef
from ..manage import ManageError, archive, delete, rename
from ..rotate import PrunePlan, plan
from ..saves import Save, find_saves_dir
from ..store import JsonStore, MetadataStore, RetentionPolicy, SaveMeta

STATIC = Path(__file__).parent / "static"


@dataclass
class ServerConfig:
    saves_dir: Path
    store: MetadataStore
    allow_delete: bool = False
    trash_dir: Path | None = None
    archive_dir: Path | None = None
    auto_rotate: bool = False
    rotate_interval: float = 300.0
    link_reseeded: bool = True

    def capabilities(self) -> dict:
        return {
            "delete": self.allow_delete,
            "rename": True,
            "archive": self.archive_dir is not None,
            "auto_rotate": self.auto_rotate and self.allow_delete,
            "trash": self.trash_dir is not None,
            "archive_dir": str(self.archive_dir) if self.archive_dir else None,
            "trash_dir": str(self.trash_dir) if self.trash_dir else None,
        }


# A save is written once and never touched again, so its parsed contents can be
# cached against the archive's size and mtime for as long as the server runs.
_DETAIL_CACHE: dict[str, tuple[tuple[float, int], dict]] = {}
_DETAIL_CACHE_MAX = 24


def _stamp(ref: SaveRef) -> tuple[float, int] | None:
    try:
        st = ref.zip_path.stat()
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


def _cached_detail(ref: SaveRef) -> dict | None:
    hit = _DETAIL_CACHE.get(ref.key)
    return hit[1] if hit and hit[0] == _stamp(ref) else None


def _store_detail(ref: SaveRef, payload: dict) -> None:
    stamp = _stamp(ref)
    if stamp is None:
        return
    if len(_DETAIL_CACHE) >= _DETAIL_CACHE_MAX:
        _DETAIL_CACHE.pop(next(iter(_DETAIL_CACHE)))
    _DETAIL_CACHE[ref.key] = (stamp, payload)


def _library(cfg: ServerConfig) -> Library:
    return Library.load(cfg.saves_dir, link_reseeded=cfg.link_reseeded)


def _find(lib: Library, key: str) -> SaveRef:
    ref = lib.by_key(key)
    if ref is None:
        raise HTTPException(404, f"no save with key {key}")
    return ref


def _payload(cfg: ServerConfig, lib: Library) -> dict:
    data = lib.as_dict()
    meta = cfg.store.all_save_meta()
    for row in data["saves"]:
        m = meta.get(row["key"], SaveMeta())
        row["tags"] = m.tags
        row["note"] = m.note
        row["starred"] = m.starred
    policies = cfg.store.all_policies()
    for group in data["continuities"]:
        pol = policies.get(group["id"], RetentionPolicy())
        group["policy"] = pol.__dict__.copy()
        if pol.label:
            group["label"] = pol.label
    data["tags"] = cfg.store.known_tags()
    data["capabilities"] = cfg.capabilities()
    return data


def _rotate_plan(cfg: ServerConfig, lib: Library, group_id: str) -> PrunePlan:
    group = lib.group_by_id(group_id)
    if group is None:
        raise HTTPException(404, f"no continuity with id {group_id}")
    return plan(group, cfg.store.policy(group_id), cfg.store.all_save_meta())


def _apply_plan(cfg: ServerConfig, lib: Library, prune: PrunePlan) -> list[dict]:
    removed = []
    for decision in prune.remove:
        ref = lib.by_key(decision.key)
        if ref is None:
            continue
        result = delete(lib.root, ref, cfg.trash_dir)
        cfg.store.drop_save_meta(decision.key)
        removed.append(result.as_dict())
    return removed


def _sweeper(cfg: ServerConfig):
    """Background loop applying every enabled retention policy."""

    async def sweep() -> None:
        while True:
            try:
                lib = await asyncio.to_thread(_library, cfg)
                for group_id, policy in cfg.store.all_policies().items():
                    if not policy.enabled or lib.group_by_id(group_id) is None:
                        continue
                    prune = _rotate_plan(cfg, lib, group_id)
                    if prune.remove:
                        await asyncio.to_thread(_apply_plan, cfg, lib, prune)
                        lib = await asyncio.to_thread(_library, cfg)
            except Exception as exc:  # never let the sweep kill the server
                print(f"auto-rotate sweep failed: {exc}")
            await asyncio.sleep(cfg.rotate_interval)

    return sweep


def create_app(cfg: ServerConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if cfg.auto_rotate and cfg.allow_delete:
            task = asyncio.create_task(_sweeper(cfg)())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()

    app = FastAPI(
        title="on-savior-ui save library", docs_url="/api/docs", lifespan=lifespan
    )
    app.state.cfg = cfg

    # -- read ------------------------------------------------------------
    @app.get("/api/library")
    def get_library() -> dict:
        return _payload(cfg, _library(cfg))

    @app.get("/api/saves/{key}/detail")
    def get_detail(key: str) -> dict:
        ref = _find(_library(cfg), key)
        cached = _cached_detail(ref)
        if cached is not None:
            return cached
        save = Save(ref.folder)
        try:
            metrics = save.metrics()
            player = save.player
            everyone = save.people()
            # Only the player's own ship is listed: a late save knows hundreds of
            # people across every station, which is noise in a save browser.
            aboard = [p for p in everyone if not player or p.ship == player.ship]
            crew = [
                {
                    "name": p.name,
                    "ship": p.ship,
                    "is_player": bool(player and p.id == player.id),
                    "skills": p.skills,
                    "traits": sorted(
                        n for n, c in p.conditions.items()
                        if n.startswith("Is") and c.duration == 1.0
                    ),
                }
                for p in aboard
            ]
        except Exception as exc:  # a truncated or in-progress save
            raise HTTPException(422, f"could not read {ref.name}: {exc}") from exc
        payload = {
            "key": key,
            "metrics": metrics,
            "crew": crew,
            "people_known": len(everyone),
            "ledger": save.ledger[-40:],
        }
        _store_detail(ref, payload)
        return payload

    @app.get("/api/saves/{key}/{kind}.png")
    def get_image(key: str, kind: str) -> FileResponse:
        if kind not in ("screenshot", "portrait"):
            raise HTTPException(404, "no such image")
        path = _find(_library(cfg), key).asset(kind)
        if path is None:
            raise HTTPException(404, f"{kind} missing")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/saves/{key}/download")
    def get_download(key: str) -> FileResponse:
        ref = _find(_library(cfg), key)
        if not ref.zip_path.is_file():
            raise HTTPException(404, "save archive missing")
        return FileResponse(
            ref.zip_path, media_type="application/zip", filename=ref.zip_path.name
        )

    # -- annotate --------------------------------------------------------
    @app.patch("/api/saves/{key}")
    def patch_save(key: str, body: dict = Body(default_factory=dict)) -> dict:
        _find(_library(cfg), key)
        meta = cfg.store.save_meta(key)
        if "tags" in body:
            meta.tags = sorted({str(t).strip() for t in body["tags"] if str(t).strip()})
        if "note" in body:
            meta.note = str(body["note"])
        if "starred" in body:
            meta.starred = bool(body["starred"])
        cfg.store.put_save_meta(key, meta)
        return {"key": key, "tags": meta.tags, "note": meta.note, "starred": meta.starred}

    # -- manage ----------------------------------------------------------
    @app.post("/api/saves/{key}/rename")
    def post_rename(key: str, body: dict = Body(...)) -> dict:
        lib = _library(cfg)
        ref = _find(lib, key)
        try:
            updated = rename(lib.root, ref, str(body.get("name", "")))
        except ManageError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"key": updated.key, "name": updated.name}

    @app.post("/api/saves/{key}/archive")
    def post_archive(key: str) -> dict:
        if cfg.archive_dir is None:
            raise HTTPException(403, "server was started without --archive-dir")
        lib = _library(cfg)
        ref = _find(lib, key)
        try:
            target = archive(lib.root, ref, cfg.archive_dir)
        except (ManageError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"key": key, "archived_to": str(target)}

    @app.delete("/api/saves/{key}")
    def del_save(key: str) -> dict:
        if not cfg.allow_delete:
            raise HTTPException(403, "server was started without --allow-delete")
        lib = _library(cfg)
        ref = _find(lib, key)
        try:
            result = delete(lib.root, ref, cfg.trash_dir)
        except (ManageError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        cfg.store.drop_save_meta(key)
        return result.as_dict()

    # -- retention -------------------------------------------------------
    @app.put("/api/continuities/{group_id}/policy")
    def put_policy(group_id: str, body: dict = Body(default_factory=dict)) -> dict:
        lib = _library(cfg)
        if lib.group_by_id(group_id) is None:
            raise HTTPException(404, f"no continuity with id {group_id}")
        policy = RetentionPolicy.from_dict({**cfg.store.policy(group_id).__dict__, **body})
        cfg.store.put_policy(group_id, policy)
        return policy.__dict__

    @app.post("/api/continuities/{group_id}/rotate")
    def post_rotate(group_id: str, apply: bool = Query(False)) -> dict:
        lib = _library(cfg)
        prune = _rotate_plan(cfg, lib, group_id)
        result = prune.as_dict()
        result["applied"] = False
        if apply:
            if not cfg.allow_delete:
                raise HTTPException(403, "server was started without --allow-delete")
            result["removed"] = _apply_plan(cfg, lib, prune)
            result["applied"] = True
        return result

    # -- static ----------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/app.js")
    def script() -> FileResponse:
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def style() -> FileResponse:
        return FileResponse(STATIC / "style.css", media_type="text/css")

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True, "saves_dir": str(cfg.saves_dir)})

    return app


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    saves_dir: str | os.PathLike | None = None,
    store_path: str | os.PathLike | None = None,
    allow_delete: bool = False,
    trash_dir: str | os.PathLike | None = None,
    archive_dir: str | os.PathLike | None = None,
    auto_rotate: bool = False,
    rotate_interval: float = 300.0,
    link_reseeded: bool = True,
) -> None:
    import uvicorn

    cfg = ServerConfig(
        saves_dir=find_saves_dir(saves_dir),
        store=JsonStore(store_path),
        allow_delete=allow_delete,
        trash_dir=Path(trash_dir) if trash_dir else None,
        archive_dir=Path(archive_dir) if archive_dir else None,
        auto_rotate=auto_rotate,
        rotate_interval=rotate_interval,
        link_reseeded=link_reseeded,
    )
    print(f"saves:   {cfg.saves_dir}")
    print(f"store:   {getattr(cfg.store, 'path', cfg.store)}")
    print(f"serving: http://{host}:{port}")
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")


__all__ = ["ServerConfig", "create_app", "serve"]
