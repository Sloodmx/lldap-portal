
import os
import sys

DATA_DIR = (os.environ.get("DATA_DIR") or "/app/data").rstrip("/") or "/app/data"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


APP_UID = _int_env("APP_UID", 1000)
APP_GID = _int_env("APP_GID", 1000)


def fix_ownership() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as e:
        print(f"[entrypoint] data folder cannot be created : {e}", file=sys.stderr)
        return

    entries = [DATA_DIR] + [
        os.path.join(DATA_DIR, name) for name in os.listdir(DATA_DIR)
    ]
    for path in entries:
        if path != DATA_DIR and os.path.islink(path):
            print(f"[entrypoint] symbolic link skipped : {path}", file=sys.stderr)
            continue
        try:
            os.chown(path, APP_UID, APP_GID)
        except OSError as e:
            print(f"[entrypoint] chown skipped on {path} : {e}", file=sys.stderr)


def drop_privileges() -> None:
    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)


def main() -> None:
    if os.geteuid() == 0:
        fix_ownership()
        try:
            drop_privileges()
        except OSError as e:
            print(f"[entrypoint] cannot drop privileges : {e}",
                  file=sys.stderr)
    else:
        print(f"[entrypoint] déjà sans privilèges (uid={os.geteuid()}) : "
              f"permissions of {DATA_DIR} unchanged", file=sys.stderr)

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()