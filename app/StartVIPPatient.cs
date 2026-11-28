// "Start VIP Patient.exe": the app. Its own window, no browser and no console.
// Starts app\launcher.py (engine, page, patient) hidden with the bundled Python and shows the page
// in this window with WebView2, the web engine that is part of Windows. Closing the window stops
// everything. F11 switches full screen. Arguments are passed to launcher.py (for example --no-unreal).
// Built by make_windows_app.ps1 with the C# compiler that ships with Windows (so: C# 5 only).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

static class StartVIPPatient
{
    [STAThread]
    static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        bool first;
        using (new Mutex(true, "VIPPatientApp", out first))
        {
            if (!first)
            {
                MessageBox.Show("VIP Patient is already open.", "VIP Patient");
                return;
            }
            KillChildrenWithThisProcess();
            Application.Run(new AppWindow(args));
        }
    }

    // A Windows job that ends Python, the engine and the patient when this process ends,
    // however it ends.
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
        if (job != IntPtr.Zero && SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf(typeof(ExtendedLimits))))
        {
            AssignProcessToJobObject(job, GetCurrentProcess());
        }
    }
}

class AppWindow : Form
{
    const string PageUrl = "http://127.0.0.1:8765/";  // PAGE_PORT in launcher.py
    static readonly string Data = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "VIPPatient");

    readonly string[] arguments;
    readonly Label status = new Label();
    readonly WebView2 view = new WebView2();
    readonly StringBuilder output = new StringBuilder();
    Process launcher;
    bool closing, pageShown, fullScreen;

    public AppWindow(string[] args)
    {
        arguments = args;
        Text = "VIP Patient";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        BackColor = Color.FromArgb(11, 26, 39);
        ClientSize = new Size(1280, 800);
        MinimumSize = new Size(900, 600);
        StartPosition = FormStartPosition.CenterScreen;
        WindowState = FormWindowState.Maximized;
        KeyPreview = true;

        status.Dock = DockStyle.Fill;
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.ForeColor = Color.FromArgb(207, 226, 238);
        status.Font = new Font("Segoe UI", 14);
        status.Text = "Starting VIP Patient…";
        view.Dock = DockStyle.Fill;
        view.Visible = false;
        view.DefaultBackgroundColor = BackColor;
        Controls.Add(view);
        Controls.Add(status);

        KeyDown += ToggleFullScreen;
        view.KeyDown += ToggleFullScreen;
        Shown += delegate { StartEngine(); };
        FormClosing += delegate { closing = true; };
    }

    void ToggleFullScreen(object sender, KeyEventArgs e)
    {
        if (e.KeyCode != Keys.F11) return;
        e.Handled = true;
        fullScreen = !fullScreen;
        WindowState = FormWindowState.Normal;  // a maximized window must be restored to cover the taskbar
        FormBorderStyle = fullScreen ? FormBorderStyle.None : FormBorderStyle.Sizable;
        WindowState = FormWindowState.Maximized;
    }

    void Fail(string message)
    {
        if (closing) return;
        view.Visible = false;
        status.Visible = true;
        status.Text = message + "\n\nLogs: " + Path.Combine(Data, "logs");
    }

    void StartEngine()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, @"runtime\python\python.exe");
        string script = Path.Combine(root, @"app\launcher.py");
        if (!File.Exists(python) || !File.Exists(script))
        {
            status.Text = "The app folder is incomplete.\nUnzip the whole folder and start this file from inside it.";
            return;
        }
        string line = Quote(script) + " --host";
        foreach (string arg in arguments) line += " " + Quote(arg);
        var start = new ProcessStartInfo(python, line)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = root,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        launcher = new Process { StartInfo = start, EnableRaisingEvents = true };
        launcher.OutputDataReceived += OnLauncherLine;
        launcher.ErrorDataReceived += OnLauncherLine;
        launcher.Exited += delegate { OnUiThread(delegate { Fail("The patient engine stopped.\n" + LastError()); }); };
        launcher.Start();
        launcher.BeginOutputReadLine();
        launcher.BeginErrorReadLine();
    }

    void OnLauncherLine(object sender, DataReceivedEventArgs e)
    {
        string line = e.Data;
        if (line == null) return;
        lock (output) output.AppendLine(line);
        try
        {
            Directory.CreateDirectory(Path.Combine(Data, "logs"));
            lock (output) File.WriteAllText(Path.Combine(Data, "logs", "launcher.log"), output.ToString());
        }
        catch (IOException) { }
        if (line == "VIP-READY") OnUiThread(ShowPage);
        else if (line.StartsWith("== ")) OnUiThread(delegate { if (!pageShown) status.Text = "Starting VIP Patient…\n" + line.Substring(3); });
    }

    string LastError()
    {
        lock (output)
        {
            string text = output.ToString();
            int at = text.LastIndexOf("ERROR: ", StringComparison.Ordinal);
            return at < 0 ? "" : text.Substring(at + 7).Trim();
        }
    }

    void OnUiThread(Action action)
    {
        if (!closing && IsHandleCreated) BeginInvoke(action);
    }

    async void ShowPage()
    {
        try
        {
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Data, "webview"));
            view.Visible = true;
            await view.EnsureCoreWebView2Async(environment);
        }
        catch (Exception error)
        {
            Fail("The app window could not be created. Windows needs the Microsoft Edge WebView2 Runtime\n"
                 + "(developer.microsoft.com/microsoft-edge/webview2).\n" + error.Message);
            return;
        }
        var web = view.CoreWebView2;
        web.Settings.AreDefaultContextMenusEnabled = false;
        web.Settings.AreDevToolsEnabled = false;
        web.Settings.IsStatusBarEnabled = false;
        web.Settings.IsPasswordAutosaveEnabled = false;
        web.Settings.IsGeneralAutofillEnabled = false;
        // This window only ever shows the app's own page; anything else opens in the user's browser
        web.NavigationStarting += (sender, e) =>
        {
            if (e.Uri.StartsWith(PageUrl, StringComparison.OrdinalIgnoreCase)) return;
            e.Cancel = true;
            OpenOutside(e.Uri);
        };
        web.NewWindowRequested += (sender, e) => { e.Handled = true; OpenOutside(e.Uri); };
        // The interview needs the microphone: allowed for the app's own page only.
        // Windows' own privacy setting for the microphone still applies.
        web.PermissionRequested += (sender, e) =>
        {
            if (e.PermissionKind == CoreWebView2PermissionKind.Microphone
                && e.Uri.StartsWith(PageUrl, StringComparison.OrdinalIgnoreCase))
            {
                e.State = CoreWebView2PermissionState.Allow;
            }
        };
        web.Navigate(PageUrl);
        status.Visible = false;
        pageShown = true;
        view.Focus();
    }

    static void OpenOutside(string url)
    {
        if (url.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) Process.Start(url);
    }

    static string Quote(string arg)
    {
        return "\"" + arg.Replace("\"", "\\\"") + "\"";
    }
}
