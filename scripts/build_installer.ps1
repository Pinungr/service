param(
    [string]$InputExe = "dist\releases\1.4.1\RepairShopManager.exe",
    [string]$OutputDirectory = "dist\installer",
    [string]$Version = "1.4.1"
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$inputPath = Resolve-Path (Join-Path $repo $InputExe)
$outputRoot = Join-Path $repo $OutputDirectory
$setupPath = Join-Path $outputRoot "RepairShopManager-Offline-Setup-$Version.exe"
$buildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RSMSetupBuild-" + [System.Guid]::NewGuid().ToString("N"))
$sourcePath = Join-Path $buildRoot "RepairShopManagerSetup.cs"

if (!(Test-Path $inputPath)) {
    throw "Application executable not found: $inputPath"
}

$resolvedOutput = [System.IO.Path]::GetFullPath($outputRoot)
$resolvedRepo = [System.IO.Path]::GetFullPath($repo)
if (!$resolvedOutput.StartsWith($resolvedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output directory must stay inside the repository."
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

$source = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class RepairShopManagerSetup
{
    private const string AppName = "RepairShop Manager";
    private const string Version = "__VERSION__";
    private const string ResourceName = "RepairShopPayload";

    [STAThread]
    private static int Main(string[] args)
    {
        bool quiet = false;
        foreach (string arg in args)
        {
            string normalized = arg.TrimStart('/', '-').ToLowerInvariant();
            quiet = quiet || normalized == "quiet" || normalized == "silent" || normalized == "q";
        }

        try
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string installDir = Path.Combine(localAppData, "Programs", "RepairShopManager");
            string exePath = Path.Combine(installDir, "RepairShopManager.exe");
            string startMenuDir = Path.Combine(appData, "Microsoft", "Windows", "Start Menu", "Programs", "RepairShop Manager");
            string uninstallPath = Path.Combine(installDir, "Uninstall RepairShop Manager.ps1");

            Directory.CreateDirectory(installDir);
            Directory.CreateDirectory(startMenuDir);
            ExtractApplication(exePath);
            WriteUninstaller(uninstallPath);

            CreateShortcut(Path.Combine(startMenuDir, "RepairShop Manager.lnk"), exePath, installDir, exePath, "Offline RepairShop Manager");
            CreateShortcut(Path.Combine(desktop, "RepairShop Manager.lnk"), exePath, installDir, exePath, "Offline RepairShop Manager");
            CreateShortcut(
                Path.Combine(startMenuDir, "Uninstall RepairShop Manager.lnk"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                installDir,
                exePath,
                "Uninstall RepairShop Manager",
                "-NoProfile -ExecutionPolicy Bypass -File \"" + uninstallPath + "\"");

            RegisterUninstall(installDir, exePath, uninstallPath);

            if (!quiet)
            {
                MessageBox.Show(
                    "RepairShop Manager has been installed.\n\nUse the Desktop or Start Menu shortcut to open it.",
                    "RepairShop Manager Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
            return 0;
        }
        catch (Exception ex)
        {
            if (!quiet)
            {
                MessageBox.Show(
                    "RepairShop Manager could not be installed.\n\n" + ex.Message,
                    "RepairShop Manager Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }

    private static void ExtractApplication(string exePath)
    {
        using (Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream(ResourceName))
        {
            if (input == null)
            {
                throw new InvalidOperationException("Embedded application payload is missing.");
            }
            using (FileStream output = new FileStream(exePath, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                input.CopyTo(output);
            }
        }
    }

    private static void WriteUninstaller(string uninstallPath)
    {
        string script = @"
`$ErrorActionPreference = ""Stop""
`$installDir = Split-Path -Parent `$MyInvocation.MyCommand.Path
`$startMenuDir = Join-Path `$env:APPDATA ""Microsoft\Windows\Start Menu\Programs\RepairShop Manager""
`$desktopShortcut = Join-Path ([Environment]::GetFolderPath(""Desktop"")) ""RepairShop Manager.lnk""
Remove-Item -LiteralPath `$desktopShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath `$startMenuDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ""HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RepairShopManager"" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath `$installDir -Recurse -Force
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show(""RepairShop Manager was uninstalled. Shop data in LocalAppData\RepairShopManager was not removed."", ""RepairShop Manager"") | Out-Null
";
        File.WriteAllText(uninstallPath, script);
    }

    private static void RegisterUninstall(string installDir, string exePath, string uninstallPath)
    {
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\RepairShopManager"))
        {
            key.SetValue("DisplayName", AppName);
            key.SetValue("DisplayVersion", Version);
            key.SetValue("Publisher", "RepairShop");
            key.SetValue("InstallLocation", installDir);
            key.SetValue("DisplayIcon", exePath);
            key.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"" + uninstallPath + "\"");
            key.SetValue("NoModify", 1, RegistryValueKind.DWord);
            key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        }
    }

    private static void CreateShortcut(string path, string target, string workingDirectory, string icon, string description, string arguments = "")
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType == null)
        {
            throw new InvalidOperationException("Windows Script Host is not available to create shortcuts.");
        }
        object shell = Activator.CreateInstance(shellType);
        object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
        Type shortcutType = shortcut.GetType();
        shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { target });
        shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDirectory });
        shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { icon });
        shortcutType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
        if (!String.IsNullOrEmpty(arguments))
        {
            shortcutType.InvokeMember("Arguments", BindingFlags.SetProperty, null, shortcut, new object[] { arguments });
        }
        shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
        Marshal.FinalReleaseComObject(shortcut);
        Marshal.FinalReleaseComObject(shell);
    }
}
"@
$source = $source.Replace("__VERSION__", $Version)
Set-Content -LiteralPath $sourcePath -Value $source -Encoding UTF8

$compiler = Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (!(Test-Path $compiler)) {
    throw "The .NET Framework C# compiler was not found: $compiler"
}

$outputArg = "/out:$setupPath"
$resourceArg = "/resource:$inputPath,RepairShopPayload"
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll /reference:Microsoft.CSharp.dll $outputArg $resourceArg $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "Setup bootstrapper compilation failed with exit code $LASTEXITCODE"
}
if (!(Test-Path $setupPath)) {
    throw "Setup file was not created: $setupPath"
}

$hash = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Offline setup created:"
Write-Host $setupPath
Write-Host "SHA256: $hash"
