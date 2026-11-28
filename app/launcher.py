"""Starts the whole VIP patient app on one Windows computer.

Run by "Start VIP Patient.exe" (app/StartVIPPatient.cs) with the bundled Python. Starts the voice server (patient
engine) and the page on this computer only, then fills the screen with the patient window
(packaged Unreal app) on the left and the page as an app window (Edge or Chrome) on the right.
On first start the page asks for the user's own OpenAI and ElevenLabs keys. Closing this
console window stops everything, the page window included.

    launcher.py               everything
    launcher.py --no-unreal   without the patient window (the voice plays in the browser)
    launcher.py --tab         the page in a normal tab of the default browser instead
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
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


PATIENT_SHARE = 0.6  # of the screen width; the page gets the rest, on the right
# Chrome first: Edge signs a new profile into the Windows account and shows a sync dialog
BROWSERS = [
    Path(os.getenv("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
    Path(os.getenv("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    Path(os.getenv("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.getenv("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
]


def screen_halves() -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """(x, y, width, height) for the patient and for the page, in physical pixels,
    filling the main screen's work area (everything but the taskbar)."""
    import ctypes
    from ctypes import wintypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixels, not scaled ones
    except Exception:  # noqa: BLE001 - older Windows
        ctypes.windll.user32.SetProcessDPIAware()
    area = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
    width, height = area.right - area.left, area.bottom - area.top
    split = int(width * PATIENT_SHARE)
    return (area.left, area.top, split, height), (area.left + split, area.top, width - split, height)


def place_window(pid: int, rect: tuple[int, int, int, int], seconds: float) -> bool:
    """Wait for the first visible top-level window of process `pid` and move it to `rect`,
    so that its visible edge (without Windows' invisible resize border) lands exactly there."""
    import ctypes
    from ctypes import wintypes

    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # GW_OWNER
            found.append(hwnd)
            return False
        return True

    deadline = time.time() + seconds
    while time.time() < deadline:
        found.clear()
        user32.EnumWindows(visit, 0)
        if found:
            break
        time.sleep(0.5)
    else:
        return False
    hwnd = found[0]
    time.sleep(1)  # let the app finish creating its window before moving it
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE, in case it opened maximized
    x, y, w, h = rect
    user32.SetWindowPos(hwnd, 0, x, y, w, h, 0x0004 | 0x0010)  # NOZORDER | NOACTIVATE
    outer, visible = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(visible), ctypes.sizeof(visible)) == 0:  # EXTENDED_FRAME_BOUNDS
        left, top = visible.left - outer.left, visible.top - outer.top
        right, bottom = outer.right - visible.right, outer.bottom - visible.bottom
        user32.SetWindowPos(hwnd, 0, x - left, y - top, w + left + right, h + top + bottom, 0x0004 | 0x0010)
    return True


def open_page_window(url: str, rect: tuple[int, int, int, int]) -> subprocess.Popen | None:
    """Open the page as its own app window (no tabs, no address bar) in Chrome or Edge, with a
    profile of its own so it is a new window we can place. The browser asks for the microphone
    once; the profile remembers the answer."""
    browser = next((b for b in BROWSERS if b.is_file()), None)
    if browser is None:
        return None
    x, y, w, h = rect
    profile = LOGS.parent / "browser"
    turn_off_translate(profile / "Default" / "Preferences")
    return subprocess.Popen([
        str(browser), f"--app={url}", f"--user-data-dir={profile}",
        f"--window-position={x},{y}", f"--window-size={w},{h}", "--lang=en-US",
        "--no-first-run", "--no-default-browser-check", "--disable-features=msImplicitSignin",
    ])


def turn_off_translate(preferences: Path) -> None:
    """The page is English; on a German PC the browser would offer to translate it every time."""
    import json

    try:
        prefs = json.loads(preferences.read_text(encoding="utf-8")) if preferences.exists() else {}
        prefs.setdefault("translate", {})["enabled"] = False
        preferences.parent.mkdir(parents=True, exist_ok=True)
        preferences.write_text(json.dumps(prefs), encoding="utf-8")
    except (OSError, ValueError):
        pass  # only cosmetic


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

        patient_rect, page_rect = screen_halves()
        if with_unreal and not PATIENT_EXE.exists():
            say("no patient window in this download; the voice plays in the browser")
        if with_unreal and PATIENT_EXE.exists():
            ensure_vc_runtime()
            say("opening the patient window on the left (the first start can take a minute)")
            x, y, w, h = patient_rect
            patient = subprocess.Popen([
                str(PATIENT_EXE), "-windowed", f"-WinX={x}", f"-WinY={y}", f"-ResX={w}", f"-ResY={h}",
                f"-VIPServer=ws://127.0.0.1:{VOICE_PORT}/ws/unreal",
            ])
            children.append(patient)
            threading.Thread(target=place_window, args=(patient.pid, patient_rect, 180), daemon=True).start()
        else:
            page_rect = (patient_rect[0], patient_rect[1], patient_rect[2] + page_rect[2], page_rect[3])

        say("opening the page on the right")
        page_window = None if "--tab" in sys.argv else open_page_window(PAGE_URL, page_rect)
        if page_window is None:
            say(f"opening {PAGE_URL} in your browser")
            open_browser(PAGE_URL)
        else:
            threading.Thread(target=place_window, args=(page_window.pid, page_rect, 30), daemon=True).start()
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
