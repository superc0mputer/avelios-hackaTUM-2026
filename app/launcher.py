"""Starts the whole VIP patient app on one Windows computer.

Run by "Start VIP Patient.cmd" with the bundled Python. Starts the voice server (patient
engine) and the page on this computer only, opens the patient window (packaged Unreal app)
and the page in the browser. On first start the page asks for the user's own OpenAI and
ElevenLabs keys. Closing this console window stops everything.

    launcher.py               everything
    launcher.py --no-unreal   without the patient window (the voice plays in the browser)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parent              # ...\app
ROOT = APP.parent                                  # the folder the user unpacked
ENGINE = APP / "engine"
PAGE = APP / "teacher-ui"
PATIENT_EXE = ROOT / "Patient" / "VIPPatient.exe"
VC_REDIST = ROOT / "redist" / "vc_redist.x64.exe"
VOICE_PORT, PAGE_PORT = 8787, 8765
PAGE_URL = f"http://127.0.0.1:{PAGE_PORT}/"
LOGS = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "VIPPatient" / "logs"


def say(message: str) -> None:
    print(f"== {message}", flush=True)


def fail(message: str) -> None:
    print(f"\nERROR: {message}\n", flush=True)
    input("Press Enter to close this window.")
    sys.exit(1)


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.5)
    return False


def ensure_vc_runtime() -> None:
    """The patient window needs Microsoft's C++ runtime; most PCs have it already."""
    system32 = Path(os.getenv("SystemRoot", r"C:\Windows")) / "System32"
    if (system32 / "vcruntime140.dll").exists() and (system32 / "msvcp140.dll").exists():
        return
    if not VC_REDIST.exists():
        say("Microsoft C++ runtime missing and no installer found; the patient window may not start")
        return
    say("installing Microsoft's C++ runtime (Windows asks for permission once)")
    subprocess.run([str(VC_REDIST), "/install", "/quiet", "/norestart"], check=False)


def start(args: list[str], cwd: Path, log_name: str, env: dict[str, str]) -> subprocess.Popen:
    log = open(LOGS / log_name, "w", encoding="utf-8")
    return subprocess.Popen(
        args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def stop_children_with_this_window() -> None:
    """Put this process in a Windows job that kills everything it starts when it ends.

    Closing the console kills Python before any cleanup code runs, so the engine and the
    patient window would otherwise keep running in the background.
    """
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    # KILL_ON_JOB_CLOSE, plus BREAKAWAY_OK so the browser can be started outside the job
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x800
    ok = job and kernel32.SetInformationJobObject(
        wintypes.HANDLE(job), 9, ctypes.byref(limits), ctypes.sizeof(limits)  # 9 = extended limits
    ) and kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(kernel32.GetCurrentProcess()))
    if not ok:
        say("note: could not tie the app to this window; close the patient window by hand when done")
    # keep `job` open for the life of this process (closing it would end everything)
    globals()["_JOB"] = job


def open_browser(url: str) -> None:
    """Open the page outside the job, so closing this window does not close the user's browser."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "", url], creationflags=0x01000000 | subprocess.CREATE_NO_WINDOW)
    except OSError:  # breakaway refused: fall back to the normal way
        webbrowser.open(url)


def main() -> None:
    with_unreal = "--no-unreal" not in sys.argv
    LOGS.mkdir(parents=True, exist_ok=True)
    stop_children_with_this_window()
    print("VIP: Virtual Interview Patient\n")

    for port in (VOICE_PORT, PAGE_PORT):
        if port_in_use(port):
            fail(f"port {port} is already in use. Is the app already running? Close the other window first.")

    env = dict(os.environ, VIP_APP="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    children: list[subprocess.Popen] = []
    try:
        say("starting the patient engine")
        children.append(start(
            [sys.executable, "-m", "uvicorn", "voice_server:app", "--host", "127.0.0.1", "--port", str(VOICE_PORT)],
            ENGINE, "voice_server.log", env,
        ))
        children.append(start([sys.executable, "server.py"], PAGE, "page.log", env))
        if not wait_for(f"http://127.0.0.1:{VOICE_PORT}/health", 60) or not wait_for(PAGE_URL, 30):
            fail(f"the patient engine did not start. Logs: {LOGS}")

        if with_unreal:
            if PATIENT_EXE.exists():
                ensure_vc_runtime()
                say("opening the patient window (the first start can take a minute)")
                children.append(subprocess.Popen([
                    str(PATIENT_EXE), "-windowed", "-resx=1280", "-resy=720",
                    f"-VIPServer=ws://127.0.0.1:{VOICE_PORT}/ws/unreal",
                ]))
            else:
                say("no patient window in this download; the voice plays in the browser")

        say(f"opening {PAGE_URL} in your browser")
        open_browser(PAGE_URL)
        print(f"\nThe app is running. Keep this window open; close it to stop everything.\nLogs: {LOGS}\n", flush=True)
        while all(child.poll() is None for child in children[:2]):
            time.sleep(1)
        fail(f"the patient engine stopped unexpectedly. Logs: {LOGS}")
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()


if __name__ == "__main__":
    main()
