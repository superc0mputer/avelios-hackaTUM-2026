// "Start VIP Patient.exe": the one file to double-click in the Windows app folder.
// Runs app\launcher.py with the bundled Python in this console window and passes any
// arguments on (for example --no-unreal). Built by make_windows_app.ps1 with the C#
// compiler that ships with Windows, so nothing extra is needed to build it.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

static class StartVIPPatient
{
    static int Main(string[] args)
    {
        Console.Title = "VIP Patient";
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, @"runtime\python\python.exe");
        string launcher = Path.Combine(root, @"app\launcher.py");
        if (!File.Exists(python) || !File.Exists(launcher))
        {
            Console.WriteLine("ERROR: the app folder is incomplete (runtime\\python or app\\launcher.py is missing).");
            Console.WriteLine("Unzip the whole folder and start this file from inside it.");
            Console.WriteLine("Press Enter to close this window.");
            Console.ReadLine();
            return 1;
        }

        string arguments = Quote(launcher);
        foreach (string arg in args) arguments += " " + Quote(arg);

        KillChildrenWithThisProcess();

        // Ctrl+C reaches Python too, which stops the app cleanly; this process just waits for it.
        Console.CancelKeyPress += (sender, e) => { e.Cancel = true; };

        var start = new ProcessStartInfo(python, arguments)
        {
            UseShellExecute = false,  // same console window, so its output and prompts show here
            WorkingDirectory = root,
        };
        using (Process child = Process.Start(start))
        {
            child.WaitForExit();
            return child.ExitCode;
        }
    }

    // A Windows job that ends Python, the engine and the patient window when this process ends,
    // however it ends. Breakaway stays allowed so the browser opened by launcher.py survives.
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits Basic;
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll")] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits info, int size);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();

    static IntPtr job;  // never closed: Windows closes it when this process ends

    static void KillChildrenWithThisProcess()
    {
        job = CreateJobObject(IntPtr.Zero, null);
        var limits = new ExtendedLimits();
        limits.Basic.LimitFlags = 0x2000 | 0x800;  // KILL_ON_JOB_CLOSE | BREAKAWAY_OK
        if (job == IntPtr.Zero
            || !SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf(typeof(ExtendedLimits)))
            || !AssignProcessToJobObject(job, GetCurrentProcess()))
        {
            Console.WriteLine("note: could not tie the app to this window; close the patient window by hand when done");
        }
    }

    static string Quote(string arg)
    {
        return "\"" + arg.Replace("\"", "\\\"") + "\"";
    }
}
