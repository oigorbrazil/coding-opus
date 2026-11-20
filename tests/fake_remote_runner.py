import json
from pathlib import Path
import sys
import time

folder = Path(sys.argv[1])
worker = json.loads((folder / "plan.json").read_text(encoding="utf-8"))["workers"][0]
output = folder / "run/workers/remote"
output.mkdir(parents=True)
(folder / "run/state.json").write_text(json.dumps({"status": "running", "workers": {}}), encoding="utf-8")
if worker["task"].startswith("wait"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not (folder / "run/stop").exists():
        time.sleep(.02)
stopped = (folder / "run/stop").exists()
(output / "result.md").write_text("Resposta de teste · ação concluída", encoding="utf-8")
(output / "outcome.json").write_text(json.dumps({"finishedAt": "2026-11-15T23:00:00Z", "sessionId": "fake-native",
                                               "account": "default", "status": "stopped" if stopped else "succeeded"}), encoding="utf-8")
