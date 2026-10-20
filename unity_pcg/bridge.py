"""Atomic local file RPC to an open Unity Editor or a one-shot batch process."""

import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class UnityBridge:
    def __init__(self, project, timeout=120, executable=None):
        self.project = Path(project).resolve()
        if not (self.project / "Assets/AgenticPCG/Editor/AgenticBridge.cs").is_file():
            raise ValueError("Unity project is missing Assets/AgenticPCG/Editor/AgenticBridge.cs")
        self.root = self.project.parent / ".bridge"
        self.timeout = timeout
        self.executable = executable or os.environ.get("UNITY_EDITOR_PATH")
        if self.executable and not Path(self.executable).is_file():
            raise ValueError("UNITY_EDITOR_PATH does not point to a Unity executable")

    def evaluate(self, level, route):
        request_id = uuid.uuid4().hex
        job = self.root / "jobs" / (request_id + ".json")
        report = self.root / "results" / (request_id + ".json")
        digest = level.digest()
        atomic_json(job, {"request_id": request_id, "level_digest": digest, "owner_pid": os.getpid(),
                         "level": level.to_dict(), "route": route})
        process = None
        log_file = self.root / (request_id + ".log")
        started = time.monotonic()
        try:
            if self.executable:
                process = subprocess.Popen([self.executable, "-batchmode", "-nographics", "-quit",
                    "-projectPath", str(self.project), "-executeMethod", "AgenticPCG.Editor.AgenticBridge.Batch",
                    "-pcgJob", str(job), "-logFile", str(log_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while not report.exists():
                if process is not None and process.poll() is not None:
                    if report.exists():
                        break
                    raise RuntimeError(f"Unity exited without a report; inspect {log_file}")
                if time.monotonic() - started > self.timeout:
                    raise TimeoutError("Unity bridge timed out; open unity/ in Unity 6 or configure UNITY_EDITOR_PATH")
                time.sleep(0.1)
            if report.stat().st_size > 2_000_000:
                raise ValueError("Unity report too large")
            result = json.loads(report.read_text())
            if result.get("request_id") != request_id or result.get("level_digest") != digest:
                raise ValueError("Unity returned a stale or mismatched report")
            if result.get("backend") not in {"unity-physics-editmode", "unity-physics-runtime"} or type(result.get("won")) is not bool:
                raise ValueError("Unity returned an invalid physics report")
            result["roundtrip_seconds"] = round(time.monotonic() - started, 4)
            return result
        finally:
            job.unlink(missing_ok=True)  # A timed-out job must never execute on the next Editor launch.
            if process is not None and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
