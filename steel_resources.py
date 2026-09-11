"""Bound the existing three-worker deployment; inspect the Docker host, not client RAM."""
import json
import subprocess

GIB = 1024 ** 3
WORKER_MEMORY = 6 * GIB
WORKER_CPUS = 2
WORKER_SHM = 2 * GIB  # Existing size; no evidence supported an increase.
WORKERS = 3
HOST_RESERVE = 2 * GIB


def validate_capacity(info, meminfo):
    total = int(info.get('MemTotal', 0))
    cpus = int(info.get('NCPU', 0))
    minimum = WORKERS * WORKER_MEMORY + HOST_RESERVE
    if total < minimum or cpus < WORKERS * WORKER_CPUS:
        raise RuntimeError(f'Steel resource admission denied: Docker host has {total} bytes/{cpus} CPUs; '
                           f'three workers require at least {minimum} bytes/{WORKERS * WORKER_CPUS} CPUs. '
                           'Do not retry Chromium on this undersized runtime.')
    available = None
    for line in meminfo.splitlines():
        if line.startswith('MemAvailable:'):
            available = int(line.split()[1]) * 1024
    if available is None or available < WORKER_MEMORY + HOST_RESERVE:
        raise RuntimeError(f'Steel resource admission denied: Docker host MemAvailable={available}; '
                           f'need {WORKER_MEMORY + HOST_RESERVE} bytes before browser startup')
    return {'dockerMemoryBytes': total, 'dockerCpuCount': cpus, 'availableBytes': available,
            'workerMemoryBytes': WORKER_MEMORY, 'workerCpuLimit': WORKER_CPUS, 'workerShmBytes': WORKER_SHM}


def check_capacity(image):
    info = json.loads(subprocess.run(['docker', 'info', '--format', '{{json .}}'],
                     capture_output=True, text=True, check=True, timeout=15).stdout)
    # Reject undersized Docker Desktop BEFORE creating even a diagnostic shell.
    validate_capacity(info, f'MemAvailable: {int(info.get("MemTotal", 0)) // 1024} kB')
    result = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--memory', '64m',
                             '--memory-swap', '64m', '--pids-limit', '32', '--entrypoint', 'sh',
                             image, '-c', 'cat /proc/meminfo'],
                            capture_output=True, text=True, check=True, timeout=30)
    return validate_capacity(info, result.stdout)
