"""Constants for the Rclone integration."""

DOMAIN = "rclone"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 5

BISYNC = "sync/bisync"
SYNC = "sync/sync"
COPY = "sync/copy"
MOVE = "sync/move"
CHECK = "operations/check"
COPYFILE = "operations/copyfile"
COPYURL = "operations/copyurl"
DELETE = "operations/delete"
DELETEFILE = "operations/deletefile"
FSINFO = "operations/fsinfo"
HASHSUM = "operations/hashsum"
HASHSUMFILE = "operations/hashsumfile"
LIST = "operations/list"
MKDIR = "operations/mkdir"
MOVEFILE = "operations/movefile"
PURGE = "operations/purge"
RMDIR = "operations/rmdir"
RMDIRS = "operations/rmdirs"
RCLONE_COMMANDS = {
    BISYNC: "sync/bisync",
    SYNC: "sync/sync",
    COPY: "sync/copy",
    MOVE: "sync/move",
    CHECK: "operations/check",
    COPYFILE: "operations/copyfile",
    COPYURL: "operations/copyurl",
    DELETE: "operations/delete",
    DELETEFILE: "operations/deletefile",
    FSINFO: "operations/fsinfo",
    HASHSUM: "operations/hashsum",
    HASHSUMFILE: "operations/hashsumfile",
    LIST: "operations/list",
    MKDIR: "operations/mkdir",
    MOVEFILE: "operations/movefile",
    PURGE: "operations/purge",
    RMDIR: "operations/rmdir",
    RMDIRS: "operations/rmdirs",
}
COMMAND_ARGS = "command_args"
