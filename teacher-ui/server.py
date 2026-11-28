"""Local server for the VIP website: case authoring, the student practice flow and teacher review."""

from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
CASES_ROOT = PROJECT_ROOT / "cases"
PRACTICE_RESULTS_ROOT = PROJECT_ROOT / "practice-results"
SCHEMA_PATH = CASES_ROOT / "patient-case.schema.json"
HOST = os.getenv("TEACHER_UI_HOST", "127.0.0.1")
PORT = int(os.getenv("TEACHER_UI_PORT", "8765"))
# The engine's voice server (engine/voice_server.py); "Start conversation" loads the case there.
VOICE_SERVER_URL = os.getenv("VOICE_SERVER_URL", "http://127.0.0.1:8787").rstrip("/")
MAX_REQUEST_BYTES = 1_000_000
SAVE_LOCK = threading.Lock()
CASE_ID_PATTERN = re.compile(r"case-[0-9]{3,}")

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


# case-100 to case-199 are the preset demo scenarios; teacher cases are numbered around them.
PRESET_CASE_NUMBERS = range(100, 200)


def is_preset(case_id: str) -> bool:
    match = re.fullmatch(r"case-(\d+)", case_id or "")
    return bool(match) and int(match.group(1)) in PRESET_CASE_NUMBERS


def next_case_id() -> str:
    numbers = []
    for path in CASES_ROOT.glob("case-*.json"):
        match = re.fullmatch(r"case-(\d+)\.json", path.name)
        if match and int(match.group(1)) not in PRESET_CASE_NUMBERS:
            numbers.append(int(match.group(1)))
    return f"case-{max(numbers, default=0) + 1:03d}"


def make_evaluation_ids(case: dict) -> dict[str, list[str]]:
    return {
        category: [f"{category}-{index:03d}" for index, _ in enumerate(case[category], start=1)]
        for category in FACT_CATEGORIES
    }


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def build_case(payload: dict, case_id: str) -> dict:
    """The saved case from the builder's payload. Missing fields become empty and fail validation."""
    diagnosis = _text(payload.get("diagnosis"))
    patient = payload.get("patient") if isinstance(payload.get("patient"), dict) else {}
    personality = payload.get("personality") if isinstance(payload.get("personality"), dict) else {}
    case = {
        "schema_version": "1.2",
        "case_id": case_id,
        "case_pair_id": slug(diagnosis),
        "character_id": payload.get("character_id"),
        "diagnosis": diagnosis,
        "patient": {
            "name": _text(patient.get("name")),
            "age": patient.get("age"),
            "gender": _text(patient.get("gender")),
            "life_story": _text(patient.get("life_story")),
        },
        "personality": {
            "type": personality.get("type"),
            "description": _text(personality.get("description")),
            "mood": personality.get("mood"),
        },
        **{
            category: [_text(item) for item in payload.get(category, []) if _text(item)]
            if isinstance(payload.get(category), list) else []
            for category in FACT_CATEGORIES
        },
    }
    presentation = build_presentation(payload.get("presentation"))
    if presentation:
        case["presentation"] = presentation
    case["evaluation_fact_ids"] = make_evaluation_ids(case)
    return case


def build_presentation(raw) -> dict:
    """How the illness shows in the MetaHuman (optional; the schema checks the values)."""
    if not isinstance(raw, dict):
        return {}
    presentation = {}
    for key in ("pain", "discomfort"):
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
            presentation[key] = raw[key]
    if raw.get("breathing") not in (None, ""):
        presentation["breathing"] = raw["breathing"]
    signs = raw.get("visible_signs")
    if isinstance(signs, list) and signs:
        presentation["visible_signs"] = signs
    return presentation


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


def read_case(case_id: str) -> dict | None:
    if not CASE_ID_PATTERN.fullmatch(case_id or ""):
        return None
    try:
        case = json.loads((CASES_ROOT / f"{case_id}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return case if isinstance(case, dict) and isinstance(case.get("patient"), dict) else None


def all_cases() -> list[dict]:
    cases = []
    for path in sorted(CASES_ROOT.glob("case-*.json")):
        case = read_case(path.stem)
        if case:
            cases.append(case)
    return cases


def write_case(case: dict, *, exclusive: bool) -> None:
    destination = CASES_ROOT / f"{case['case_id']}.json"
    with destination.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(case, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class TeacherHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    # ---------- routing ----------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        routes = {
            "/api/next-id": lambda: self._json(200, {"case_id": next_case_id()}),
            "/api/student-cases": self._list_student_cases,
            "/api/briefing": lambda: self._get_student_briefing(query.get("case_id", [""])[0]),
            "/api/cases": self._list_teacher_cases,
            "/api/case": lambda: self._get_case(query.get("case_id", [""])[0]),
            "/api/practice-results": self._list_practice_results,
            "/api/my-results": lambda: self._list_my_results(query.get("student_name", [""])[0]),
        }
        if path in routes:
            routes[path]()
            return
        if path.startswith("/api/"):
            self.send_error(404, "Unknown API route")
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        routes = {
            "/api/start": self._start_conversation,
            "/api/practice-results": self._save_practice_result,
            "/api/grade": self._grade_practice_result,
            "/api/cases": self._create_case,
            "/api/turn": lambda: self._relay("/turn"),
            "/api/director": lambda: self._relay("/director"),
        }
        if route in routes:
            routes[route]()
        else:
            self.send_error(404, "Unknown API route")

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/case":
            self._update_case(parse_qs(parsed.query).get("case_id", [""])[0])
        else:
            self.send_error(404, "Unknown API route")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/case":
            self._delete_case(parse_qs(parsed.query).get("case_id", [""])[0])
        else:
            self.send_error(404, "Unknown API route")

    # ---------- helpers ----------

    def _read_json(self, too_large: str = "The request must be between 1 byte and 1 MB."):
        """The request body as a dict, or None after answering with an error."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Invalid Content-Length."})
            return None
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": too_large})
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "The request must be valid UTF-8 JSON."})
            return None
        if not isinstance(payload, dict):
            self._json(400, {"error": "The request must be a JSON object."})
            return None
        return payload

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---------- cases (teacher) ----------

    def _create_case(self):
        payload = self._read_json("Case payload must be between 1 byte and 1 MB.")
        if payload is None:
            return
        with SAVE_LOCK:
            case = build_case(payload, next_case_id())
            messages = validate_case(case)
            if messages:
                self._json(422, {"error": "Complete the required case details.", "details": messages})
                return
            try:
                write_case(case, exclusive=True)
            except FileExistsError:
                # Recalculate once in case another server process saved between checks.
                case = build_case(payload, next_case_id())
                write_case(case, exclusive=True)
        self._json(201, {
            "saved_as": f"cases/{case['case_id']}.json",
            "case_id": case["case_id"],
            "case_pair_id": case["case_pair_id"],
            "name": case["patient"]["name"],
        })

    def _update_case(self, case_id: str):
        if read_case(case_id) is None:
            self._json(404, {"error": "Patient case not found."})
            return
        if is_preset(case_id):
            self._json(403, {"error": "Preset cases cannot be changed. Duplicate it to make your own version."})
            return
        payload = self._read_json("Case payload must be between 1 byte and 1 MB.")
        if payload is None:
            return
        with SAVE_LOCK:
            case = build_case(payload, case_id)
            messages = validate_case(case)
            if messages:
                self._json(422, {"error": "Complete the required case details.", "details": messages})
                return
            write_case(case, exclusive=False)
        self._json(200, {"saved_as": f"cases/{case_id}.json", "case_id": case_id, "name": case["patient"]["name"]})

    def _delete_case(self, case_id: str):
        if read_case(case_id) is None:
            self._json(404, {"error": "Patient case not found."})
            return
        if is_preset(case_id):
            self._json(403, {"error": "Preset cases cannot be deleted."})
            return
        with SAVE_LOCK:
            (CASES_ROOT / f"{case_id}.json").unlink(missing_ok=True)
        self._json(200, {"deleted": case_id})

    def _get_case(self, case_id: str):
        case = read_case(case_id)
        if case is None:
            self._json(404, {"error": "Patient case not found."})
            return
        self._json(200, {"case": case, "preset": is_preset(case_id)})

    def _list_teacher_cases(self):
        counts: dict[str, int] = {}
        for result in self._read_submissions():
            counts[result.get("case_id")] = counts.get(result.get("case_id"), 0) + 1
        cases = []
        for case in all_cases():
            patient = case["patient"]
            personality = case.get("personality") or {}
            cases.append({
                "case_id": case["case_id"],
                "preset": is_preset(case["case_id"]),
                "name": patient.get("name", "Patient"),
                "age": patient.get("age"),
                "gender": patient.get("gender", ""),
                "character_id": case.get("character_id", ""),
                "diagnosis": case.get("diagnosis", ""),
                "personality": personality.get("type", ""),
                "mood": personality.get("mood", "neutral"),
                "presentation": case.get("presentation") or {},
                "secrets": len(case.get("secrets") or []),
                "submissions": counts.get(case["case_id"], 0),
            })
        self._json(200, {"cases": cases})

    # ---------- student flow ----------

    def _list_student_cases(self):
        # Identity only: never the diagnosis, the story, the facts or the personality.
        cases = [{
            "case_id": case["case_id"],
            "name": case["patient"].get("name", "Patient"),
            "age": case["patient"].get("age"),
            "gender": case["patient"].get("gender", ""),
            "character_id": case.get("character_id", ""),
            "preset": is_preset(case["case_id"]),
        } for case in all_cases()]
        self._json(200, {"cases": cases})

    def _get_student_briefing(self, case_id):
        case = read_case(case_id)
        if case is None:
            self._json(404, {"error": "Patient case not found."})
            return
        patient = case["patient"]
        # The student briefing deliberately excludes story, symptoms, diagnosis, and personality.
        self._json(200, {
            "case_id": case_id,
            "patient": {
                "name": patient.get("name", "Patient"),
                "age": patient.get("age"),
                "gender": patient.get("gender", ""),
            },
            "character_id": case.get("character_id", ""),
        })

    def _save_practice_result(self):
        payload = self._read_json("Submission must be between 1 byte and 1 MB.")
        if payload is None:
            return
        case_id = str(payload.get("case_id", "")).strip()
        student_name = str(payload.get("student_name", "")).strip()
        diagnosis = str(payload.get("student_diagnosis", "")).strip()
        symptoms = str(payload.get("symptoms", "")).strip()
        notes = str(payload.get("notes", "")).strip()
        timed_out = bool(payload.get("timed_out", False))
        transcript = payload.get("transcript") if isinstance(payload.get("transcript"), list) else []
        transcript = [
            {"role": "patient" if t.get("role") == "patient" else "student", "text": str(t.get("text", ""))[:2000]}
            for t in transcript[:400] if isinstance(t, dict) and str(t.get("text", "")).strip()
        ]
        case = read_case(case_id)
        if case is None:
            self._json(404, {"error": "The case for this interview could not be found."})
            return
        if not student_name or len(student_name) > 120:
            self._json(422, {"error": "Enter a student name or ID (up to 120 characters)."})
            return
        if (not diagnosis and not timed_out) or len(diagnosis) > 500:
            self._json(422, {"error": "Enter your likely disease (up to 500 characters)."})
            return
        if (not symptoms and not timed_out) or len(symptoms) > 5000 or len(notes) > 5000:
            self._json(422, {"error": "Enter the symptoms you found and keep each text field under 5,000 characters."})
            return

        with SAVE_LOCK:
            PRACTICE_RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
            numbers = []
            for path in PRACTICE_RESULTS_ROOT.glob("submission-*.json"):
                match = re.fullmatch(r"submission-(\d+)\.json", path.name)
                if match:
                    numbers.append(int(match.group(1)))
            submission_id = f"submission-{max(numbers, default=0) + 1:03d}"
            record = {
                "submission_id": submission_id,
                "case_id": case_id,
                "student_name": student_name,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "student_diagnosis": diagnosis,
                "symptoms": symptoms,
                "notes": notes,
                "timed_out": timed_out,
                "transcript": transcript,
                "grade": None,
                "feedback": "",
            }
            with (PRACTICE_RESULTS_ROOT / f"{submission_id}.json").open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        # After submitting, the student may see the answer (the review screen).
        self._json(201, {
            "submission_id": submission_id,
            "saved_as": f"practice-results/{submission_id}.json",
            "correct_diagnosis": case.get("diagnosis", ""),
            "patient_name": case["patient"].get("name", "Patient"),
        })

    def _list_my_results(self, student_name: str):
        """A student's own submissions with the answer and the teacher's review (only after submitting)."""
        name = student_name.strip()
        if not name:
            self._json(400, {"error": "Enter your name or ID."})
            return
        mine = [
            {k: r.get(k) for k in (
                "submission_id", "case_id", "submitted_at", "student_diagnosis", "symptoms", "notes",
                "timed_out", "grade", "feedback", "patient_name", "correct_diagnosis",
            )}
            for r in self._read_submissions() if r.get("student_name", "").strip().lower() == name.lower()
        ]
        self._json(200, {"submissions": mine})

    # ---------- teacher review ----------

    def _read_submissions(self):
        results = []
        for path in sorted(PRACTICE_RESULTS_ROOT.glob("submission-*.json")):
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(result, dict):
                continue
            case = read_case(str(result.get("case_id", ""))) or {}
            result["patient_name"] = (case.get("patient") or {}).get("name", "Deleted case")
            result["correct_diagnosis"] = case.get("diagnosis", "")
            results.append(result)
        return results

    def _list_practice_results(self):
        self._json(200, {"submissions": self._read_submissions()})

    def _grade_practice_result(self):
        payload = self._read_json("Grade update must be between 1 byte and 1 MB.")
        if payload is None:
            return
        submission_id = str(payload.get("submission_id", ""))
        if not re.fullmatch(r"submission-[0-9]{3,}", submission_id):
            self._json(400, {"error": "Choose a valid student submission."})
            return
        try:
            grade = int(payload.get("grade"))
        except (ValueError, TypeError):
            self._json(422, {"error": "Choose a grade from 1 to 5."})
            return
        feedback = str(payload.get("feedback", "")).strip()
        if not 1 <= grade <= 5 or len(feedback) > 5000:
            self._json(422, {"error": "Grade must be 1–5 and feedback no longer than 5,000 characters."})
            return
        target = PRACTICE_RESULTS_ROOT / f"{submission_id}.json"
        if not target.is_file():
            self._json(404, {"error": "Student submission not found."})
            return
        with SAVE_LOCK:
            result = json.loads(target.read_text(encoding="utf-8"))
            result["grade"] = grade
            result["feedback"] = feedback
            result["graded_at"] = datetime.now(timezone.utc).isoformat()
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._json(200, {"submission_id": submission_id, "grade": grade})

    # ---------- the voice server ----------

    def _voice(self, path: str, body: dict, timeout: float = 30):
        """POST to the voice server. Returns (status, json) or answers 502 itself and returns None."""
        request = urllib.request.Request(
            f"{VOICE_SERVER_URL}{path}", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            try:
                detail = json.loads(detail).get("detail", detail)
            except (ValueError, AttributeError):
                pass
            return error.code, {"error": str(detail)}
        except (urllib.error.URLError, TimeoutError, OSError):
            self._json(502, {"error": f"The voice server is not running at {VOICE_SERVER_URL}."})
            return None

    def _start_conversation(self):
        """Load a saved case into the voice server (and Unreal) and say how the student can talk."""
        payload = self._read_json() or {}
        case_id = str(payload.get("case_id") or "")
        if not CASE_ID_PATTERN.fullmatch(case_id):
            self._json(400, {"error": "Send the case_id of a saved case."})
            return
        answer = self._voice("/case", {"case_id": case_id})
        if answer is None:
            return
        status, result = answer
        if status >= 400:
            self._json(502, {"error": f"The voice server could not load the case: {result.get('error', '')}"})
            return
        self._json(200, result)

    def _relay(self, path: str):
        """Typed turns (/turn) and turn reports for the face (/director) go to the voice server."""
        payload = self._read_json()
        if payload is None:
            return
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) > 200:
            self._json(400, {"error": "Send the conversation as a list of messages."})
            return
        answer = self._voice(path, {"messages": messages}, timeout=60)
        if answer is not None:
            self._json(*answer)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), TeacherHandler)
    print(f"VIP website: http://{HOST}:{PORT}")
    print(f"Cases are saved in: {CASES_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the website.")
    finally:
        server.server_close()
