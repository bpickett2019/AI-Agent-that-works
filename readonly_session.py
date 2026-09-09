"""Expose a leased operator readback browser without starting a configuration agent."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import os
import re
import uuid
from control_store import iso


def private_json(path, value):
    """Atomically write private evidence owned by the existing workspace owner."""
    path = Path(path);owner = path.parent.stat()
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x') as output:
        json.dump(value, output, indent=2)
    temporary.chmod(0o600)
    os.chown(temporary, owner.st_uid, owner.st_gid)
    temporary.replace(path)


@dataclass
class ReadonlySession:
    slot_id: int
    runtime_dir: Path
    read_only: bool = True
    process: None = None


def resolve_readonly_session(store, job, directory):
    """Only a current matching canonical lease can activate this viewer."""
    if job.get('state') != 'failed_uncertain' or not job.get('uncertain') or job.get('pid'):
        return None
    directory = Path(directory)
    pointer = directory/'read-only-reconciliation.json'
    try:
        if pointer.is_symlink() or not pointer.is_file() or pointer.stat().st_size > 4096:
            return None
        descriptor = json.loads(pointer.read_text())
        name = descriptor['directory']
        if not re.fullmatch(r'(?:readonly|atted)-[0-9a-f]{12}', name):
            return None
        folder = directory/'reconciliation'/name
        if (folder.is_symlink() or (directory/'reconciliation').is_symlink() or
                folder.resolve().parent != (directory/'reconciliation').resolve()):
            return None
        runtime_path = folder/'browser-runtime.json'
        if runtime_path.is_symlink() or runtime_path.stat().st_size > 1024*1024:
            return None
        runtime = json.loads(runtime_path.read_text())
        if (runtime.get('accessMode') != 'read_only_reconciliation' or
            runtime.get('authorizedEventId') != job['event_id'] or
            runtime.get('authorizedEventKey') != job['event_key'] or
            runtime.get('authorizedEventName') != job['event_name'] or
            runtime.get('workerSlot') != 1 or descriptor.get('jobId') != job['id'] or
            runtime.get('browserRuntimeId') != descriptor.get('browserRuntimeId')):
            return None
        with store.connect() as conn:
            row = conn.execute('''SELECT w.slot_id,w.token FROM worker_leases w
                JOIN event_leases e ON w.holder_job_id=e.holder_job_id AND w.token=e.token
                WHERE w.holder_job_id=? AND e.event_id=? AND w.expires_at>? AND e.expires_at>?''',
                (job['id'], job['event_id'], iso(), iso())).fetchone()
        if (not row or row['slot_id'] != 1 or
                hashlib.sha256(row['token'].encode()).hexdigest() != descriptor.get('leaseFingerprint')):
            return None
        return ReadonlySession(1, folder)
    except (OSError, KeyError, TypeError, ValueError):
        return None
