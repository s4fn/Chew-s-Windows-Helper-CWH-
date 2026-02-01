// Example conceptual snippet (compile with csc). Use System.ServiceProcess and System.IO.
// This is only illustrative; use proper try/catch and run as admin.
using System;
using System.IO;
using System.ServiceProcess;
class Cleanup {
    static void Main() {
        try {
            ServiceController sc = new ServiceController("wuauserv");
            if (sc.Status != ServiceControllerStatus.Stopped) sc.Stop();
        } catch {}
        try { Directory.Delete(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "SoftwareDistribution", "Download"), true); } catch {}
        // etc...
    }
}