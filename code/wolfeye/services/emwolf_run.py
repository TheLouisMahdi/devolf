"""Bounded, durable PC receipts for autonomous EmWolf runs only."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import struct
import zlib
from pathlib import Path

EVENT_LIMIT = 65536
CHUNK_LIMIT = 64
EVENT = struct.Struct("<IBHBBQ")
STATUS = struct.Struct("<QBBIIH")
TERMINAL = frozenset((4, 5, 6, 8))
STATE_NAMES = {0:"IDLE", 1:"QUEUED", 2:"RUNNING", 3:"SAVING", 4:"COMPLETED", 5:"STOPPED", 6:"BUFFER FULL", 8:"INTERRUPTED", 9:"STORAGE ERROR", 10:"BUSY", 11:"REJECTED", 12:"NOT FOUND"}

def atomic_json(path: Path, value: dict) -> None:
    data=json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(data)>1024*1024:
        raise ValueError("EmWolf run metadata exceeds its bound")
    temp=path.with_suffix(path.suffix+".new")
    with temp.open("wb") as target:
        target.write(data); target.flush(); os.fsync(target.fileno())
    os.replace(temp,path)
    if os.name!="nt":
        descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

def decode_events(payload: bytes) -> list[dict]:
    if len(payload)%EVENT.size or len(payload)>CHUNK_LIMIT*EVENT.size:
        raise ValueError("Invalid autonomous event chunk size")
    result=[]
    for sequence,kind,scenario,input_id,value,time_us in EVENT.iter_unpack(payload):
        if not 1<=sequence<=EVENT_LIMIT or kind not in (1,2,3,4,5) or scenario>=29 or input_id>4 or value>1:
            raise ValueError("Invalid autonomous event field")
        result.append(dict(sequence=sequence,kind=kind,scenario=scenario,input_id=input_id,value=bool(value),time_us=time_us))
    return result

class RunCache:
    def __init__(self, directory: Path, meta: dict) -> None:
        self.directory=directory
        self.meta=meta
        self.id=int(meta["id"])
        if not 0<self.id<1<<64:
            raise ValueError("Invalid cached EmWolf run identifier")
        self.meta_path=directory/f"{self.id:016x}.json"
        self.events_path=directory/f"{self.id:016x}.events"
        self.events: list[dict]=[]
        self._raw: list[bytes]=[]
        self._load_events()

    @staticmethod
    def directory_for(host: str,port: int,root: Path|None=None) -> Path:
        root=root or Path(os.environ.get("LOCALAPPDATA",str(Path.home()/".local/share")))/"WolfEye"/"EmWolf"
        return root/hashlib.sha256(f"{host.strip().lower()}:{port}".encode()).hexdigest()[:24]

    @classmethod
    def load_active(cls,directory: Path) -> RunCache|None:
        active=directory/"active.json"
        if not active.exists(): return None
        if active.stat().st_size>128: raise ValueError("Invalid EmWolf active receipt")
        run_id=int(json.loads(active.read_text())["id"])
        if not 0<run_id<1<<64: raise ValueError("Invalid active run ID")
        path=directory/f"{run_id:016x}.json"
        if path.stat().st_size>1024*1024: raise ValueError("EmWolf metadata exceeds its bound")
        meta=json.loads(path.read_text(encoding="utf-8"))
        if int(meta["id"])!=run_id: raise ValueError("EmWolf receipt ID mismatch")
        return cls(directory,meta)

    @classmethod
    def create(cls,directory: Path,run_id: int,project: dict,started_at: str) -> RunCache:
        if not 0<run_id<1<<64: raise ValueError("Invalid EmWolf run ID")
        directory.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(directory).free<32*1024*1024:
            raise OSError("Insufficient PC disk space for a durable EmWolf receipt")
        path=directory/f"{run_id:016x}.json"
        if path.exists() or (directory/f"{run_id:016x}.events").exists():
            raise ValueError("An EmWolf receipt with this ID already exists")
        meta=dict(id=run_id,project=project,started_at=started_at,state=1,collected=False)
        atomic_json(path,meta)
        atomic_json(directory/"active.json",dict(id=run_id))
        return cls(directory,meta)

    def _load_events(self) -> None:
        if not self.events_path.exists(): return
        size=self.events_path.stat().st_size
        if size>EVENT_LIMIT*(EVENT.size+4): raise ValueError("EmWolf receipt exceeds its event bound")
        data=self.events_path.read_bytes(); stride=EVENT.size+4
        complete=len(data)//stride*stride
        for offset in range(0,complete,stride):
            raw=data[offset:offset+EVENT.size]
            if zlib.crc32(raw)&0xffffffff!=struct.unpack_from("<I",data,offset+EVENT.size)[0]:
                raise ValueError("Cached EmWolf event CRC error; file retained")
            event=decode_events(raw)[0]
            if event["sequence"]!=len(self.events)+1: raise ValueError("Cached EmWolf sequence gap")
            self.events.append(event); self._raw.append(raw)
        if complete!=len(data):
            # A PC crash during an append cannot imply a receipt for that tail.
            if self.meta.get("collected"): raise ValueError("Completed EmWolf receipt is truncated; retained")
            tail=self.events_path.with_suffix(".partial")
            if not tail.exists(): tail.write_bytes(data[complete:])
            with self.events_path.open("r+b") as target:
                target.truncate(complete); target.flush(); os.fsync(target.fileno())

        # A previous fsync may have failed after writing a complete record.
        # Re-establish durability before a reconnect is allowed to acknowledge it.
        with self.events_path.open("r+b") as target:
            os.fsync(target.fileno())

    def append(self,raw: bytes) -> list[dict]:
        decoded=decode_events(raw)
        additions=[]; records=[]
        for i,event in enumerate(decoded):
            sequence=event["sequence"]; item=raw[i*EVENT.size:(i+1)*EVENT.size]
            if sequence<=len(self.events):
                if self._raw[sequence-1]!=item: raise ValueError("Conflicting replayed EmWolf event")
                continue
            if sequence!=len(self.events)+len(additions)+1: raise ValueError("EmWolf event gap; receipt withheld")
            additions.append(event); records.append(item)
        if len(self.events)+len(additions)>EVENT_LIMIT: raise ValueError("EmWolf event capacity exceeded")
        if records:
            with self.events_path.open("ab") as target:
                for item in records:
                    target.write(item); target.write(struct.pack("<I",zlib.crc32(item)&0xffffffff))
                target.flush(); os.fsync(target.fileno())
            self.events.extend(additions); self._raw.extend(records)
        return additions

    def status(self,state: int,collected: bool) -> None:
        if self.meta.get("state")==state and self.meta.get("collected")==collected: return
        self.meta.update(state=state,collected=collected)
        atomic_json(self.meta_path,self.meta)


class ReceiptLease:
    """One EmWolf receipt writer per PC/board, released by the OS after a crash."""
    def __init__(self,directory: Path) -> None:
        directory.mkdir(parents=True,exist_ok=True)
        self.stream=(directory/"owner.lock").open("a+b")
        try:
            self.stream.seek(0,2)
            if not self.stream.tell(): self.stream.write(b"\x00"); self.stream.flush()
            self.stream.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise OSError("Another WolfEye instance owns this board's EmWolf receipts") from exc

    def close(self) -> None:
        if self.stream.closed: return
        self.stream.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()
