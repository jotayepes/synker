"""Command line interface. Every command accepts --json for machine-readable output."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import subprocess
import sys
import threading
from typing import Any

from synker import __version__, autostart, secrets
from synker import config as config_mod
from synker.detect.scanner import Game, Scanner
from synker.engine import EMPTY, Engine
from synker.manifest import fetch
from synker.storage import StorageError, open_storage


class CliError(Exception):
    pass


# -- helpers -------------------------------------------------------------------


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


class Context:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.cfg = config_mod.load()
        self._scanner: Scanner | None = None

    @property
    def scanner(self) -> Scanner:
        if self._scanner is None:
            index = fetch.load_index(self.cfg.manifest_url, auto_update=not self.args.no_manifest_update)
            self._scanner = Scanner(self.cfg, index)
        return self._scanner

    def engine(self) -> Engine:
        if not self.cfg.is_storage_configured():
            raise CliError("no backup storage configured; run `synker setup` first")
        return Engine(self.cfg)

    def game(self, ref: str | None = None) -> Game:
        args = self.args
        ref = ref or getattr(args, "game", None)
        appid = getattr(args, "appid", None)
        name = getattr(args, "name", None)
        if not (ref or appid or name):
            raise CliError("specify a game (id, title or Steam appid)")
        game = self.scanner.find(ref, appid=appid, name=name)
        if not game:
            raise CliError(f"game not found: {ref or name or appid}")
        return game

    def games(self, refs: list[str], all_games: bool) -> list[Game]:
        if refs:
            return [self.game(r) for r in refs]
        if not all_games:
            raise CliError("specify one or more games, or --all")
        return [g for g in self.scanner.scan() if not g.ignored and not g.cloud_covered]


def _print(args: argparse.Namespace, data: Any, human=None) -> None:
    if args.json:
        print(json.dumps(data, indent=None if args.compact else 2, default=str))
    elif human:
        human(data)
    else:
        print(json.dumps(data, indent=2, default=str))


# -- commands ------------------------------------------------------------------


def cmd_setup(ctx: Context) -> Any:
    cfg = ctx.cfg
    print("Synker setup. Press Enter to keep the value in brackets.\n")

    def ask(prompt: str, current: str) -> str:
        value = input(f"{prompt} [{current}]: ").strip()
        return value or current

    cfg.device_name = ask("Name of this device", cfg.device_name)
    cfg.storage.type = ask("Storage type (smb/local)", cfg.storage.type)
    if cfg.storage.type == "smb":
        smb = cfg.storage.smb
        smb.host = ask("NAS host or IP", smb.host)
        smb.share = ask("Share name", smb.share)
        smb.path = ask("Folder inside the share", smb.path)
        smb.username = ask("User (empty for guest)", smb.username)
        smb.domain = ask("Domain/workgroup (usually empty)", smb.domain)
        if smb.username:
            pw = getpass.getpass("Password (empty to keep the stored one): ")
            if pw:
                where = secrets.set_password(secrets.smb_account(smb.host, smb.username), pw)
                print(f"Password stored in the {where}.")
    else:
        cfg.storage.path = ask("Backup folder", cfg.storage.path)
    cfg.validate()
    path = config_mod.save(cfg)
    print(f"\nSaved {path}")
    try:
        with open_storage(cfg) as storage:
            print(f"Storage OK: {storage.test()['location']}")
    except (StorageError, OSError) as exc:
        print(f"Warning: storage test failed: {exc}")
    return {"config": str(path)}


def cmd_config(ctx: Context) -> Any:
    a = ctx.args
    if a.config_action == "path":
        return {"path": str(config_mod.config_path())}
    if a.config_action == "set":
        ctx.cfg.set_value(a.key, a.value)
        config_mod.save(ctx.cfg)
    elif a.config_action == "set-json":
        data = json.loads(sys.stdin.read())
        for key, value in data.items():
            ctx.cfg.set_value(key, value)
        config_mod.save(ctx.cfg)
    return ctx.cfg.to_dict()


def cmd_password(ctx: Context) -> Any:
    smb = ctx.cfg.storage.smb
    if not smb.host:
        raise CliError("configure storage.smb.host first")
    pw = sys.stdin.readline().rstrip("\n") if ctx.args.stdin else getpass.getpass("SMB password: ")
    where = secrets.set_password(secrets.smb_account(smb.host, smb.username), pw)
    return {"stored_in": where}


def cmd_storage_test(ctx: Context) -> Any:
    if not ctx.cfg.is_storage_configured():
        raise CliError("no backup storage configured; run `synker setup` first")
    try:
        with open_storage(ctx.cfg) as storage:
            return storage.test()
    except (StorageError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def cmd_manifest(ctx: Context) -> Any:
    result = fetch.update(ctx.cfg.manifest_url, force=ctx.args.force)
    return vars(result)


def cmd_scan(ctx: Context) -> Any:
    games = ctx.scanner.scan(full=not ctx.args.quick)
    if not ctx.args.all:
        games = [g for g in games if not g.ignored and not g.cloud_covered]
    return [g.to_dict(with_files=True) for g in games]


def _print_scan(data: list[dict]) -> None:
    for g in data:
        flags = []
        if g["cloud_covered"]:
            flags.append("store cloud")
        if g["ignored"]:
            flags.append("ignored")
        extra = f" ({', '.join(flags)})" if flags else ""
        print(f"{g['title']}  [{g['id']}, {g['source']}]  {len(g['files'])} files, {_human_size(g['size'])}{extra}")
        if ctx_verbose:
            for f in g["files"]:
                print(f"    {f['path']}")
    print(f"\n{len(data)} games")


ctx_verbose = False


def cmd_status(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        games = ctx.games(ctx.args.games, all_games=not ctx.args.games)
        statuses = [engine.status(g) for g in games]
        if not ctx.args.games:
            # Installed games without saves locally or on the NAS are just noise in the overview.
            statuses = [s for s in statuses if s["state"] != EMPTY]
        return statuses
    finally:
        engine.close()


def _print_status(data: list[dict]) -> None:
    for s in data:
        latest = s.get("latest") or {}
        when = latest.get("created_iso", "-")
        print(f"{s['game']['title']:<40} {s['state']:<13} local {s['local_files']} files  latest {when}")


def cmd_backup(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        refs = ctx.args.games
        if not refs and (ctx.args.appid or ctx.args.name):
            games = [ctx.game()]
        else:
            games = ctx.games(refs, ctx.args.all)
        return [engine.backup(g, reason=ctx.args.reason, force=ctx.args.force) for g in games]
    finally:
        engine.close()


def cmd_restore(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        game = ctx.game()
        if ctx.args.undo:
            return engine.undo_restore(game)
        return engine.restore(game, ctx.args.backup, dry_run=ctx.args.dry_run)
    finally:
        engine.close()


def cmd_list(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        game_id = ctx.args.game
        if not ctx.args.raw_id:
            game_id = ctx.game().id
        return engine.list_backups(game_id)
    finally:
        engine.close()


def _print_list(data: list[dict]) -> None:
    for b in data:
        lock = " [locked]" if b.get("locked") else ""
        print(f"{b['id']}  {b['created_iso']}  {b['device']:<16} {b['reason']:<12} {b['files']} files "
              f"{_human_size(b['size'])}{lock}")


def cmd_lock(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        entry = engine.repo().set_locked(ctx.game().id, ctx.args.backup, not ctx.args.unlock)
        return entry.to_dict()
    finally:
        engine.close()


def cmd_sync(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        game = ctx.game()
        if ctx.args.phase == "pre":
            return engine.pre_launch(game, policy=ctx.args.policy)
        return engine.post_exit(game, reason=ctx.args.reason)
    finally:
        engine.close()


def cmd_run(ctx: Context) -> int:
    """Wrapper for Steam launch options: synker run --appid 123 -- %command%"""
    command = ctx.args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise CliError("no command to run")
    log = logging.getLogger("synker.run")
    game = None
    try:
        game = ctx.game()
    except CliError as exc:
        log.warning("%s; running without sync", exc)
    stop = threading.Event()
    if game and ctx.cfg.is_storage_configured():
        engine = Engine(ctx.cfg)
        try:
            log.info("pre-launch: %s", engine.pre_launch(game))
        except Exception as exc:
            log.error("pre-launch sync failed: %s", exc)
        finally:
            engine.close()

        minutes = ctx.cfg.backup.periodic_minutes

        def periodic() -> None:
            while minutes and not stop.wait(minutes * 60):
                e = Engine(ctx.cfg)
                try:
                    e.post_exit(game, reason="periodic")
                except Exception as exc:
                    log.error("periodic backup failed: %s", exc)
                finally:
                    e.close()

        threading.Thread(target=periodic, daemon=True).start()
    code = subprocess.call(command)
    stop.set()
    if game and ctx.cfg.is_storage_configured():
        engine = Engine(ctx.cfg)
        try:
            log.info("post-exit: %s", engine.post_exit(game))
        except Exception as exc:
            log.error("post-exit backup failed: %s", exc)
        finally:
            engine.close()
    return code


def cmd_add(ctx: Context) -> Any:
    cfg = ctx.cfg
    cfg.custom_games = [g for g in cfg.custom_games if g.name != ctx.args.title]
    cfg.custom_games.append(config_mod.CustomGame(ctx.args.title, ctx.args.path, ctx.args.process or []))
    config_mod.save(cfg)
    return {"added": ctx.args.title}


def cmd_remove(ctx: Context) -> Any:
    before = len(ctx.cfg.custom_games)
    ctx.cfg.custom_games = [g for g in ctx.cfg.custom_games if g.name != ctx.args.title]
    if len(ctx.cfg.custom_games) == before:
        raise CliError(f"no custom game named {ctx.args.title!r}")
    config_mod.save(ctx.cfg)
    return {"removed": ctx.args.title}


def cmd_ignore(ctx: Context) -> Any:
    ignored = [x for x in ctx.cfg.ignored_games if x.casefold() != ctx.args.game.casefold()]
    if not ctx.args.undo:
        ignored.append(ctx.args.game)
    ctx.cfg.ignored_games = ignored
    config_mod.save(ctx.cfg)
    return {"ignored_games": ignored}


def cmd_queue(ctx: Context) -> Any:
    engine = ctx.engine()
    try:
        return engine.flush_queue()
    finally:
        engine.close()


def cmd_daemon(ctx: Context) -> Any:
    action = ctx.args.daemon_action
    if action == "install":
        return {"installed": autostart.install()}
    if action == "uninstall":
        return {"removed": autostart.uninstall()}
    from synker.daemon import Daemon

    daemon = Daemon(ctx.cfg, poll_seconds=ctx.args.poll)
    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stop()
    return {"stopped": True}


# -- parser --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synker", description="Automatic game save backup to a NAS or folder.")
    p.add_argument("--version", action="version", version=f"synker {__version__}")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--compact", action="store_true", help="single-line JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--no-manifest-update", action="store_true", help="do not check for a newer manifest")
    sub = p.add_subparsers(dest="command_name", required=True)

    def game_args(sp, positional: bool = True) -> None:
        if positional:
            sp.add_argument("game", nargs="?", help="game id, title or Steam appid")
        sp.add_argument("--appid", type=int, help="Steam appid (also non-Steam shortcuts)")
        sp.add_argument("--name", help="game name, used when the appid is unknown")

    sp = sub.add_parser("setup", help="interactive first-time configuration")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("config", help="show or change settings")
    csub = sp.add_subparsers(dest="config_action")
    csub.add_parser("show")
    csub.add_parser("path")
    cset = csub.add_parser("set", help="e.g. `synker config set storage.smb.host nas.local`")
    cset.add_argument("key")
    cset.add_argument("value")
    csub.add_parser("set-json", help="read {key: value} pairs as JSON from stdin")
    sp.set_defaults(func=cmd_config, config_action="show")

    sp = sub.add_parser("password", help="store the SMB password")
    sp.add_argument("--stdin", action="store_true", help="read it from standard input")
    sp.set_defaults(func=cmd_password)

    sp = sub.add_parser("storage-test", help="check that the backup storage is reachable and writable")
    sp.set_defaults(func=cmd_storage_test)

    sp = sub.add_parser("manifest-update", help="download the latest ludusavi manifest")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_manifest)

    sp = sub.add_parser("scan", help="list detected games and their save files")
    sp.add_argument("--all", action="store_true", help="include ignored games and games with store cloud saves")
    sp.add_argument("--quick", action="store_true", help="only games from launchers, emulators and custom games")
    sp.set_defaults(func=cmd_scan, human=_print_scan)

    sp = sub.add_parser("status", help="sync state of games against the NAS")
    sp.add_argument("games", nargs="*")
    sp.set_defaults(func=cmd_status, human=_print_status)

    sp = sub.add_parser("backup", help="back up games now")
    sp.add_argument("games", nargs="*")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--appid", type=int)
    sp.add_argument("--name")
    sp.add_argument("--reason", default="manual")
    sp.add_argument("--force", action="store_true", help="back up even if nothing changed")
    sp.set_defaults(func=cmd_backup)

    sp = sub.add_parser("restore", help="restore a backup (the latest by default)")
    game_args(sp)
    sp.add_argument("--backup", help="backup id (see `synker list`)")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--undo", action="store_true", help="undo the last restore from the local snapshot")
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("list", help="list the backups of a game")
    game_args(sp)
    sp.add_argument("--raw-id", action="store_true", help="treat GAME as a storage id without scanning")
    sp.set_defaults(func=cmd_list, human=_print_list)

    sp = sub.add_parser("lock", help="protect a backup from retention")
    game_args(sp)
    sp.add_argument("--backup", required=True)
    sp.add_argument("--unlock", action="store_true")
    sp.set_defaults(func=cmd_lock)

    sp = sub.add_parser("sync", help="run the launch (pre) or exit (post) sync step for a game")
    game_args(sp)
    sp.add_argument("--phase", choices=("pre", "post"), required=True)
    sp.add_argument("--policy", choices=config_mod.CONFLICT_POLICIES)
    sp.add_argument("--reason", default="exit")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("run", help="wrap a game command: restore before, back up after")
    game_args(sp, positional=False)
    sp.add_argument("--game")
    sp.add_argument("command", nargs=argparse.REMAINDER)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("add", help="add a custom game")
    sp.add_argument("title")
    sp.add_argument("--path", action="append", required=True, help="file, folder or glob; placeholders allowed")
    sp.add_argument("--process", action="append", help="process name used to detect that it runs")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("remove", help="remove a custom game")
    sp.add_argument("title")
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("ignore", help="never back up a game")
    sp.add_argument("game")
    sp.add_argument("--undo", action="store_true")
    sp.set_defaults(func=cmd_ignore)

    sp = sub.add_parser("queue-flush", help="upload backups queued while the NAS was unreachable")
    sp.set_defaults(func=cmd_queue)

    sp = sub.add_parser("daemon", help="watch games and back them up automatically")
    sp.add_argument("daemon_action", choices=("run", "install", "uninstall"), nargs="?", default="run")
    sp.add_argument("--poll", type=float, default=5)
    sp.set_defaults(func=cmd_daemon)
    return p


def main(argv: list[str] | None = None) -> int:
    global ctx_verbose
    args = build_parser().parse_args(argv)
    ctx_verbose = args.verbose
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO if args.command_name in (
        "daemon", "run") else logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr)
    try:
        ctx = Context(args)
        result = args.func(ctx)
        if args.command_name == "run":
            return int(result)
        _print(args, result, getattr(args, "human", None))
        if isinstance(result, dict) and result.get("ok") is False:
            return 1
        return 0
    except (CliError, StorageError, LookupError, RuntimeError, ValueError, KeyError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "type": type(exc).__name__}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
