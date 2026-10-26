"""python3 -m oni_companion --mode barry|standalone [--listen 127.0.0.1:PORT]"""
import argparse
import ipaddress
import logging
import os
import sys

from .server.service import Service, ServiceConfig

log = logging.getLogger("oni_companion")
LOOPBACK_NAMES = {"localhost"}


def _is_loopback(host):
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_listen(text):
    host, _, port = text.rpartition(":")
    if not host:
        host, port = text, "0"
    return host, int(port)


def default_user_dir():
    env = os.environ.get("ONI_USER_DIR")
    if env:
        return env
    from . import sources
    found = sources.default_user_dir()
    if found:
        return found
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/unity.Klei.Oxygen Not Included")
    return os.path.expanduser("~/.config/unity3d/Klei/Oxygen Not Included")


def _save_parser(path):
    """Colony facts from a save: the `live` block of colony_from_save (header-only on damage)."""
    from .save.colony_from_save import colony_from_save
    return colony_from_save(path)["live"]


def build_config(argv, environ=None):
    environ = os.environ if environ is None else environ
    ap = argparse.ArgumentParser(prog="oni_companion")
    ap.add_argument("--mode", choices=("barry", "standalone"), required=True)
    ap.add_argument("--listen", help="host:port (loopback only in v1)")
    ap.add_argument("--user-dir", default=None)
    ap.add_argument("--save-dir", action="append", default=None)
    ap.add_argument("--game-dir", default=None)
    ap.add_argument("--ignore-game", action="store_true",
                    help="development only: do not tie the service to the game process")
    args = ap.parse_args(argv)
    if args.mode == "barry":
        if args.listen and not _is_loopback(parse_listen(args.listen)[0]):
            sys.exit("oni_companion: listening beyond loopback is not in v1")
        token = environ.get("BARRY_SERVICE_TOKEN")
        port = environ.get("BARRY_SERVICE_PORT")
        if not token or not port:
            sys.exit("oni_companion: barry mode needs BARRY_SERVICE_PORT and BARRY_SERVICE_TOKEN")
        host, port = "127.0.0.1", int(port)
    else:
        host, port = parse_listen(args.listen or "127.0.0.1:0")
        if not _is_loopback(host):
            sys.exit("oni_companion: standalone mode on a non-loopback address is not in v1")
        token = environ.get("ONI_TOKEN")
    from . import config as oni_config
    cfg = oni_config.load(env=environ, mode=args.mode, game_dir=args.game_dir, user_dir=args.user_dir,
                          save_dir=(args.save_dir[0] if args.save_dir else None))
    user_dir = cfg.user_dir or default_user_dir()
    saves = args.save_dir or ([cfg.save_dir] if cfg.save_dir else [])
    if not saves:
        saves = [d for d in (os.path.join(user_dir, "cloud_save_files"), os.path.join(user_dir, "save_files"))
                 if os.path.isdir(d)]
    follow = not cfg.user_dir_forced                     # plan 4.3: follow the running game across the ONI folders
    explicit_saves = bool(args.save_dir or cfg.save_dir)
    from . import lifetime
    return ServiceConfig(user_dir=user_dir, save_dirs=saves, game_dir=cfg.game_dir or None,
                         host=host, port=port, token=token, barry_mode=(args.mode == "barry"),
                         save_parser=_save_parser,
                         data_dir=environ.get("ONI_DATA_DIR") or environ.get("BARRY_APP_DATA") or cfg.data_dir,
                         ignore_game=args.ignore_game, follow=follow, shared=True, follow_env=environ,
                         auto_saves=follow and not explicit_saves, user_dirs=cfg.user_dirs,
                         find=lifetime.find_game if os.path.isdir("/proc") else None)


TOKEN_FILE = "api-token"


def token_path(cfg):
    from . import config as oni_config
    return os.path.join(cfg.data_dir or oni_config.default_data_dir(), TOKEN_FILE)


def _announce(cfg, svc):
    """Standalone: the loopback API token goes to a file only the owner can read, never to the journal."""
    from .connect.files import write_atomic
    path = token_path(cfg)
    write_atomic(path, svc.token, 0o600)
    log.info("listening on http://%s:%d (token in %s)", cfg.host, svc.port, path)


def _remove_token_file(cfg):
    try:
        os.unlink(token_path(cfg))
    except OSError:
        pass


def main(argv=None):
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(message)s")
    cfg = build_config(sys.argv[1:] if argv is None else argv)
    if not cfg.barry_mode and not cfg.ignore_game:
        # Standalone lives only as long as the game (plan 5.1): no game -> exit at once.
        from . import lifetime

        def start():
            svc = Service(cfg).start()
            _announce(cfg, svc)
            return svc
        try:
            sys.exit(lifetime.run_standalone(start, user_dir=cfg.user_dir))
        finally:
            _remove_token_file(cfg)
    svc = Service(cfg)
    if cfg.barry_mode and not cfg.ignore_game:
        svc.connect.game_running = False      # the network listener and mDNS wait for the game (plan 5.1)
    svc.start()
    if cfg.barry_mode:
        if not cfg.ignore_game:
            svc.enable_game_gate()      # network listener / mDNS follow the game; the loopback API stays up
    else:
        _announce(cfg, svc)
    svc.serve_forever()


if __name__ == "__main__":
    main()
