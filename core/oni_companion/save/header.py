"""ONI save file header.

Layout (verified on game build 744825, save version 7.38):

    <IIII>  build number, header size, header version, compressed flag
    header  JSON text, header-size bytes (UTF-8)
    rest    KSerialization templates, then the world body
            (zlib-compressed when the compressed flag is 1)

Only the first two parts are needed to list saves, so reading the header is
cheap (it never touches the 1+ MB body).
"""

import json
import struct
from dataclasses import dataclass, field

PREAMBLE = struct.Struct("<IIII")
MAX_HEADER_BYTES = 1 << 20  # a real header is ~300 bytes; refuse nonsense


class SaveFormatError(ValueError):
    """The file is not an ONI save, or is damaged."""


@dataclass
class SaveHeader:
    build: int = 0
    header_size: int = 0
    header_version: int = 0
    compressed: bool = False
    info: dict = field(default_factory=dict)  # the JSON header as the game wrote it

    @property
    def body_offset(self):
        """Byte offset where the templates start."""
        return PREAMBLE.size + self.header_size

    @property
    def cycles(self):
        return int(self.info.get("numberOfCycles", 0))

    @property
    def cycle(self):
        """Cycle number as the game shows it (numberOfCycles + 1)."""
        return self.cycles + 1

    @property
    def dupe_count(self):
        return int(self.info.get("numberOfDuplicants", 0))

    @property
    def colony_name(self):
        return self.info.get("baseName") or ""

    @property
    def colony_guid(self):
        return self.info.get("colonyGuid") or ""

    @property
    def cluster_id(self):
        return self.info.get("clusterId") or ""

    @property
    def dlc_ids(self):
        ids = self.info.get("dlcIds")
        if ids is None:
            one = self.info.get("dlcId")
            ids = [one] if one else []
        return [i for i in ids if i]  # the game writes [""] for the base game

    @property
    def save_version(self):
        return (int(self.info.get("saveMajorVersion", 0)),
                int(self.info.get("saveMinorVersion", 0)))

    @property
    def is_autosave(self):
        return bool(self.info.get("isAutoSave"))


def parse_header(data):
    """Parse the header from the first bytes of a save. Raises SaveFormatError."""
    if len(data) < PREAMBLE.size:
        raise SaveFormatError("file too short for a save header")
    build, size, version, compressed = PREAMBLE.unpack_from(data, 0)
    if size > MAX_HEADER_BYTES or PREAMBLE.size + size > len(data):
        raise SaveFormatError("header size %d does not fit the file" % size)
    raw = bytes(data[PREAMBLE.size:PREAMBLE.size + size])
    try:
        info = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SaveFormatError("header JSON unreadable: %s" % exc) from None
    if not isinstance(info, dict):
        raise SaveFormatError("header JSON is not an object")
    return SaveHeader(build, size, version, compressed == 1, info)


def read_header(path):
    """Read only the header of the save at `path`."""
    with open(path, "rb") as fh:
        head = fh.read(PREAMBLE.size)
        if len(head) == PREAMBLE.size:
            size = PREAMBLE.unpack(head)[1]
            if size <= MAX_HEADER_BYTES:
                head += fh.read(size)
    return parse_header(head)
