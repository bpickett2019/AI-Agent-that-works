#!/usr/bin/env python3
"""Tiny atomic state/log updater scoped to one job."""
import argparse, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CURRENT = Path(os.environ.get("CVENT_JOB_DIR", ROOT / "data" / "current"))
STATE = CURRENT / "state.json"
LOG = CURRENT / "activity.log"

def now(): return datetime.now(timezone.utc).isoformat()
def load():
    try: return json.loads(STATE.read_text())
    except Exception: return {}
def save(state):
    CURRENT.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    fd, name = tempfile.mkstemp(dir=CURRENT, prefix="state-", suffix=".tmp")
    with os.fdopen(fd, "w") as f: json.dump(state, f, indent=2)
    os.replace(name, STATE)
def update(**changes):
    state = load(); state.update({k:v for k,v in changes.items() if v is not None}); save(state)
def log(message):
    CURRENT.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f: f.write(f"{now()}  {message.strip()}\n")

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--status"); p.add_argument("--stage", dest="current_stage")
    p.add_argument("--action", dest="current_action"); p.add_argument("--log")
    p.add_argument("--completed", nargs="*"); p.add_argument("--pending", nargs="*")
    p.add_argument("--review-json", help="JSON array replacing review_required")
    a=p.parse_args(); changes={k:v for k,v in vars(a).items() if k not in {"log","review_json"} and v is not None}
    if a.review_json is not None: changes["review_required"]=json.loads(a.review_json)
    if changes: update(**changes)
    if a.log: log(a.log)
