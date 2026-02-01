// WinCleanup.Program.cs - supports --dry-run, --loglevel, --json (preview)
// Build with dotnet publish -r win-x64 -c Release -p:PublishSingleFile=true -o ../bin
using System;
using System.IO;
using System.ServiceProcess;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;

namespace WinCleanup
{
    class Program
    {
        static int Main(string[] args)
        {
            bool dryRun = args.Contains("--dry-run");
            bool wantJson = args.Contains("--json");
            string logLevel = "info";
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--loglevel" && i + 1 < args.Length) logLevel = args[i + 1].ToLower();
            }
            Log("INFO", $"Started. dryRun={dryRun} logLevel={logLevel} json={wantJson}");
            List<Dictionary<string, string>> preview = new List<Dictionary<string,string>>();
            try
            {
                TryStopService("wuauserv", dryRun);
                RemoveDirectoryContents(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "SoftwareDistribution", "Download"), dryRun, preview);
                RemoveDirectoryContents(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "catroot2"), dryRun, preview);
                RemovePath(Environment.GetEnvironmentVariable("TEMP"), dryRun, preview);
                RemovePath(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Temp"), dryRun, preview);
                RemovePath(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Temp"), dryRun, preview);
                RemoveDirectoryContents(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Prefetch"), dryRun, preview);
                TryStartService("wuauserv", dryRun);
                Log("INFO", "Completed.");
                if (wantJson && dryRun)
                {
                    var obj = new { items = preview };
                    var json = JsonSerializer.Serialize(obj, new JsonSerializerOptions { WriteIndented = true });
                    Console.WriteLine(json);
                }
                return 0;
            }
            catch (Exception ex)
            {
                Log("ERROR", ex.Message);
                return 1;
            }
        }

        static void Log(string level, string message)
        {
            Console.WriteLine($"{level.ToUpper()}: {message}");
        }

        static void TryStopService(string svcName, bool dryRun)
        {
            try
            {
                Log("INFO", $"Stopping {svcName}...");
                if (dryRun) { Log("INFO", $"(DRY-RUN) Would stop {svcName}"); return; }
                ServiceController sc = new ServiceController(svcName);
                if (sc.Status != ServiceControllerStatus.Stopped && sc.Status != ServiceControllerStatus.StopPending)
                {
                    sc.Stop();
                    sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(10));
                }
                Log("INFO", $"Stopped {svcName} or not running.");
            }
            catch (Exception ex) { Log("WARN", $"Could not stop {svcName}: {ex.Message}"); }
        }

        static void TryStartService(string svcName, bool dryRun)
        {
            try
            {
                Log("INFO", $"Starting {svcName}...");
                if (dryRun) { Log("INFO", $"(DRY-RUN) Would start {svcName}"); return; }
                ServiceController sc = new ServiceController(svcName);
                if (sc.Status != ServiceControllerStatus.Running)
                {
                    sc.Start();
                    sc.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(10));
                }
                Log("INFO", $"Started {svcName} or already running.");
            }
            catch (Exception ex) { Log("WARN", $"Could not start {svcName}: {ex.Message}"); }
        }

        static void RemoveDirectoryContents(string dir, bool dryRun, List<Dictionary<string,string>> preview)
        {
            if (!Directory.Exists(dir))
            {
                Log("INFO", $"Not found: {dir}");
                return;
            }
            Log("INFO", $"Clearing {dir}...");
            preview.Add(new Dictionary<string,string> { { "path", dir }, { "type", "dir" } });
            if (dryRun) { Log("INFO", $"(DRY-RUN) Would clear {dir}"); return; }
            try
            {
                foreach (var f in Directory.GetFiles(dir))
                {
                    try { File.Delete(f); } catch (Exception e) { Log("WARN", $"Failed delete {f}: {e.Message}"); }
                }
                foreach (var d in Directory.GetDirectories(dir))
                {
                    try { Directory.Delete(d, true); } catch (Exception e) { Log("WARN", $"Failed delete {d}: {e.Message}"); }
                }
                Log("INFO", $"Cleared {dir}");
            }
            catch (Exception ex) { Log("WARN", $"Error clearing {dir}: {ex.Message}"); }
        }

        static void RemovePath(string path, bool dryRun, List<Dictionary<string,string>> preview)
        {
            if (string.IsNullOrEmpty(path))
            {
                return;
            }
            RemoveDirectoryContents(path, dryRun, preview);
        }
    }
}