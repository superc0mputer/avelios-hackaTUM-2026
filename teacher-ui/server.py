"""Local teacher UI server for authoring schema-valid patient cases."""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
CASES_ROOT = PROJECT_ROOT / "cases"
SCHEMA_PATH = CASES_ROOT / "patient-case.schema.json"
PORT = 8765
MAX_REQUEST_BYTES = 1_000_000
SAVE_LOCK = threading.Lock()

FACT_CATEGORIES = (
    "symptoms", "medical_history", "medications", "allergies",
    "family_history", "lifestyle", "secrets",
)

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalized.lower())).strip("-")


def next_case_id() -> str:
    numbers = []
    for path in CASES_ROOT.glob("case-*.json"):
        match = re.fullmatch(r"case-(\d+)\.json", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return f"case-{max(numbers, default=0) + 1:03d}"


def make_evaluation_ids(case: dict) -> dict[str, list[str]]:
    return {
        category: [f"{category}-{index:03d}" for index, _ in enumerate(case[category], start=1)]
        for category in FACT_CATEGORIES
    }


def build_case(payload: dict, case_id: str) -> dict:
    diagnosis = payload["diagnosis"].strip()
    patient = payload["patient"]
    personality = payload["personality"]
    case = {
        "schema_version": "1.2",
        "case_id": case_id,
        "case_pair_id": slug(diagnosis),
        "character_id": payload["character_id"],
        "diagnosis": diagnosis,
        "patient": {
            "name": patient["name"].strip(),
            "age": patient["age"],
            "gender": patient["gender"].strip(),
            "life_story": patient["life_story"].strip(),
        },
        "personality": {
            "type": personality["type"],
            "description": personality.get("description", "").strip(),
            "mood": personality["mood"],
        },
        **{category: [item.strip() for item in payload.get(category, []) if item.strip()] for category in FACT_CATEGORIES},
    }
    case["evaluation_fact_ids"] = make_evaluation_ids(case)
    return case


def validate_case(case: dict) -> list[str]:
    errors = sorted(VALIDATOR.iter_errors(case), key=lambda error: tuple(str(part) for part in error.absolute_path))
    messages = [
        f"{'.'.join(str(part) for part in error.absolute_path) or 'case'}: {error.message}"
        for error in errors
    ]
    if case["personality"]["type"] == "custom" and not case["personality"]["description"]:
        messages.append("personality.description: describe the custom personality.")
    if not slug(case["diagnosis"]):
        messages.append("diagnosis: include letters or numbers so a pair ID can be generated.")
    return messages


class TeacherHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/next-id":
            self._json(200, {"case_id": next_case_id()})
            return
        if path.startswith("/api/"):
            self.send_error(404, "Unknown API route")
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/cases":
            self.send_error(404, "Unknown API route")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Invalid Content-Length."})
            return
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": "Case payload must be between 1 byte and 1 MB."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "Request body must be valid UTF-8 JSON."})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "Case details must be a JSON object."})
            return

        with SAVE_LOCK:
            case = build_case(payload, next_case_id())
            messages = validate_case(case)
            if messages:
                self._json(422, {"error": "Complete the required case details.", "details": messages})
                return
            destination = CASES_ROOT / f"{case['case_id']}.json"
            try:
                with destination.open("x", encoding="utf-8") as stream:
                    json.dump(case, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
            except FileExistsError:
                # Recalculate once in case another server process saved between checks.
                case = build_case(payload, next_case_id())
                with (CASES_ROOT / f"{case['case_id']}.json").open("x", encoding="utf-8") as stream:
                    json.dump(case, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
            self._json(201, {
                "saved_as": f"cases/{case['case_id']}.json",
                "case_id": case["case_id"],
                "case_pair_id": case["case_pair_id"],
                "title": case["title"],
            })

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), TeacherHandler)
    print(f"Teacher case form: http://127.0.0.1:{PORT}")
    print(f"New cases are saved in: {CASES_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping teacher UI.")
    finally:
        server.server_close()
