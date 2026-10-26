"""Synker Decky backend.

A thin adapter around the bundled `synker` CLI binary (bin/synker, built with
PyInstaller). The frontend reports game launches/exits; this backend runs the
matching sync steps, schedules periodic backups while a game runs and emits
events back to the frontend.
"""

import asyncio
import json
import os
import time

import decky

PERIODIC_CHECK_SECONDS = 30


def _command() -> list[str]:
    binary = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "synker")
    if os.path.isfile(binary):
        return [binary]
    # Development fallback: system Python with synker vendored in py_modules.
    return ["python3", "-m", "synker"]


def _env() -> dict[str, str]:
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin",
        "HOME": decky.DECKY_USER_HOME,
        "SYNKER_HOME": decky.DECKY_USER_HOME,
        "SYNKER_CONFIG_DIR": decky.DECKY_PLUGIN_SETTINGS_DIR,
        "SYNKER_DATA_DIR": decky.DECKY_PLUGIN_RUNTIME_DIR,
        "SYNKER_NO_KEYRING": "1",
        # PyInstaller's library path from the loader must not leak into our binary.
        "LD_LIBRARY_PATH": "",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    py_modules = os.path.join(decky.DECKY_PLUGIN_DIR, "py_modules")
    if os.path.isdir(py_modules):
        env["PYTHONPATH"] = py_modules
    return env


class SynkerError(Exception):
    pass


async def _synker(*args: str, stdin: str | None = None, timeout: float = 900):
    cmd = _command() + ["--json", "--compact", *args]
    decky.logger.info("running: %s", " ".join(cmd[1:]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise SynkerError(f"synker {args[0]} timed out")
    if err:
        decky.logger.info("synker stderr: %s", err.decode(errors="replace").strip()[-2000:])
    text = out.decode(errors="replace").strip()
    data = None
    if text:
        try:
            data = json.loads(text.splitlines()[-1])
        except ValueError:
            raise SynkerError(f"unexpected output from synker: {text[-300:]}")
    if proc.returncode != 0:
        message = data.get("error") if isinstance(data, dict) else None
        raise SynkerError(message or err.decode(errors="replace").strip()[-300:] or "synker failed")
    return data


class Plugin:
    def __init__(self):
        self.lock = asyncio.Lock()
        # appid -> {"name": str, "game_id": str | None, "last": float}
        self.running: dict[int, dict] = {}
        self.ticker: asyncio.Task | None = None
        self.settings_cache: dict | None = None

    async def _run(self, *args: str, **kw):
        async with self.lock:
            return await _synker(*args, **kw)

    async def _emit(self, kind: str, payload: dict) -> None:
        await decky.emit("synker_event", kind, payload)

    # -- settings ----------------------------------------------------------

    async def get_config(self) -> dict:
        self.settings_cache = await self._run("config", "show")
        return self.settings_cache

    async def set_config(self, values: dict) -> dict:
        self.settings_cache = await self._run("config", "set-json", stdin=json.dumps(values))
        return self.settings_cache

    async def set_password(self, password: str) -> dict:
        return await self._run("password", "--stdin", stdin=password + "\n")

    async def test_storage(self) -> dict:
        try:
            return await self._run("storage-test", timeout=60)
        except SynkerError as exc:
            return {"ok": False, "error": str(exc)}

    async def update_manifest(self) -> dict:
        return await self._run("manifest-update", "--force", timeout=1800)

    # -- games -------------------------------------------------------------

    async def scan(self) -> list:
        return await self._run("scan")

    async def status(self) -> list:
        return await self._run("--no-manifest-update", "status")

    async def backup(self, game_id: str) -> list:
        return await self._run("--no-manifest-update", "backup", game_id)

    async def backup_all(self) -> list:
        return await self._run("--no-manifest-update", "backup", "--all", timeout=3600)

    async def list_backups(self, game_id: str) -> list:
        return await self._run("--no-manifest-update", "list", game_id, "--raw-id")

    async def restore(self, game_id: str, backup_id: str = "") -> dict:
        args = ["--no-manifest-update", "restore", game_id]
        if backup_id:
            args += ["--backup", backup_id]
        return await self._run(*args)

    async def undo_restore(self, game_id: str) -> dict:
        return await self._run("--no-manifest-update", "restore", game_id, "--undo")

    async def resolve_conflict(self, game_id: str, policy: str) -> dict:
        return await self._run("--no-manifest-update", "sync", game_id, "--phase", "pre", "--policy", policy)

    # -- game lifecycle (called by the frontend) ---------------------------

    async def game_started(self, appid: int, name: str) -> dict:
        appid = int(appid)
        self.running[appid] = {"name": name, "game_id": None, "last": time.time()}
        try:
            result = await self._run("--no-manifest-update", "sync", "--phase", "pre",
                                     "--appid", str(appid), "--name", name or "")
        except SynkerError as exc:
            if "not found" in str(exc):
                return {"action": "unknown-game"}
            await self._emit("error", {"name": name, "error": str(exc)})
            return {"action": "error", "error": str(exc)}
        self.running[appid]["game_id"] = result.get("game_id")
        await self._emit("started", {"name": name, "result": result})
        return result

    async def game_stopped(self, appid: int) -> dict:
        info = self.running.pop(int(appid), None)
        if not info or not info.get("game_id"):
            return {"action": "none"}
        config = self.settings_cache or await self.get_config()
        if not config.get("backup", {}).get("backup_on_exit", True):
            return {"action": "disabled"}
        try:
            result = await self._run("--no-manifest-update", "sync", info["game_id"], "--phase", "post")
        except SynkerError as exc:
            await self._emit("error", {"name": info["name"], "error": str(exc)})
            return {"action": "error", "error": str(exc)}
        await self._emit("stopped", {"name": info["name"], "result": result})
        return result

    async def running_games(self) -> list:
        return [{"appid": k, **v} for k, v in self.running.items()]

    async def _periodic(self) -> None:
        while True:
            await asyncio.sleep(PERIODIC_CHECK_SECONDS)
            try:
                config = self.settings_cache or await self.get_config()
                minutes = int(config.get("backup", {}).get("periodic_minutes", 0))
                if not minutes:
                    continue
                now = time.time()
                for info in list(self.running.values()):
                    if info.get("game_id") and now - info["last"] >= minutes * 60:
                        info["last"] = now
                        result = await self._run("--no-manifest-update", "sync", info["game_id"],
                                                 "--phase", "post", "--reason", "periodic")
                        await self._emit("periodic", {"name": info["name"], "result": result})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                decky.logger.warning("periodic backup failed: %s", exc)

    # -- lifecycle ---------------------------------------------------------

    async def _main(self):
        self.ticker = asyncio.get_event_loop().create_task(self._periodic())
        try:
            await self.get_config()
            await self._run("manifest-update", timeout=1800)
            await self._run("--no-manifest-update", "queue-flush")
        except Exception as exc:
            decky.logger.warning("startup tasks failed: %s", exc)

    async def _unload(self):
        if self.ticker:
            self.ticker.cancel()

    async def _uninstall(self):
        pass
