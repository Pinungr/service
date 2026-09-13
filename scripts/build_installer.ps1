param(
    [string]$InputExe = "dist\releases\1.4.1\RepairShopManager.exe",
    [string]$OutputDirectory = "dist",
    [string]$Version = "1.4.1"
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$candidateInput = Join-Path $repo $InputExe
$installedFallback = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\RepairShopManager\RepairShopManager.exe"
if (Test-Path -LiteralPath $candidateInput) {
    $inputPath = Resolve-Path $candidateInput
} elseif (Test-Path -LiteralPath $installedFallback) {
    $inputPath = Resolve-Path $installedFallback
} else {
    throw "Application executable not found. Build the app first or install the current setup once. Checked: $candidateInput and $installedFallback"
}

$outputRoot = Join-Path $repo $OutputDirectory
$setupPath = Join-Path $outputRoot "RepairShopManager-Offline-Setup-$Version.exe"
$buildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RSMSetupBuild-" + [System.Guid]::NewGuid().ToString("N"))
$sourcePath = Join-Path $buildRoot "RepairShopManagerSetup.cs"

$resolvedOutput = [System.IO.Path]::GetFullPath($outputRoot)
$resolvedRepo = [System.IO.Path]::GetFullPath($repo)
if (!$resolvedOutput.StartsWith($resolvedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output directory must stay inside the repository."
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

$source = @'
using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class RepairShopManagerSetup
{
    internal const string AppName = "RepairShop Manager";
    internal const string Version = "__VERSION__";
    private const string ResourceName = "RepairShopPayload";
    internal static readonly string DefaultInstallDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Programs",
        "RepairShopManager");

    internal static readonly string ReadmeText =
@"RepairShop Manager" + Environment.NewLine +
@"

Offline desktop application for a repair shop counter.

What this setup installs:
- RepairShop Manager application file
- Desktop shortcut, if selected
- Start Menu shortcut
- Uninstall entry in Windows Apps / Control Panel

What this setup does not require:
- Internet
- Python
- Source code
- Administrator permission when installing to the default user folder

Data storage:
Shop data is stored separately in:
" + Environment.ExpandEnvironmentVariables(@"%LOCALAPPDATA%\RepairShopManager") + @"

Uninstalling the program removes the installed application and shortcuts. It does not remove shop data, backups, customer photos or records.";

    [STAThread]
    private static int Main(string[] args)
    {
        bool quiet = false;
        foreach (string arg in args)
        {
            string normalized = arg.TrimStart('/', '-').ToLowerInvariant();
            quiet = quiet || normalized == "quiet" || normalized == "silent" || normalized == "q";
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        try
        {
            if (quiet)
            {
                Install(DefaultInstallDir, true);
                return 0;
            }

            using (SetupForm form = new SetupForm())
            {
                Application.Run(form);
                return form.ExitCode;
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "RepairShop Manager could not be installed.\n\n" + ex.Message,
                "RepairShop Manager Setup",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }
    }

    internal static void Install(string installDir, bool createDesktopShortcut)
    {
        if (String.IsNullOrWhiteSpace(installDir))
        {
            throw new InvalidOperationException("Choose an installation folder.");
        }

        installDir = Path.GetFullPath(Environment.ExpandEnvironmentVariables(installDir.Trim()));
        string exePath = Path.Combine(installDir, "RepairShopManager.exe");
        string startMenuDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "RepairShop Manager");
        string uninstallPath = Path.Combine(installDir, "Uninstall RepairShop Manager.ps1");
        string desktopShortcut = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            "RepairShop Manager.lnk");

        Directory.CreateDirectory(installDir);
        Directory.CreateDirectory(startMenuDir);
        ExtractApplication(exePath);
        File.WriteAllText(Path.Combine(installDir, "README.txt"), ReadmeText);
        WriteUninstaller(uninstallPath);

        CreateShortcut(
            Path.Combine(startMenuDir, "RepairShop Manager.lnk"),
            exePath,
            installDir,
            exePath,
            "Offline RepairShop Manager");

        if (createDesktopShortcut)
        {
            CreateShortcut(desktopShortcut, exePath, installDir, exePath, "Offline RepairShop Manager");
        }
        else if (File.Exists(desktopShortcut))
        {
            File.Delete(desktopShortcut);
        }

        CreateShortcut(
            Path.Combine(startMenuDir, "Uninstall RepairShop Manager.lnk"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            installDir,
            exePath,
            "Uninstall RepairShop Manager",
            "-NoProfile -ExecutionPolicy Bypass -File \"" + uninstallPath + "\"");

        RegisterUninstall(installDir, exePath, uninstallPath);
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
        string script =
@"param([switch]$Quiet)
$ErrorActionPreference = ""Stop""
$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startMenuDir = Join-Path $env:APPDATA ""Microsoft\Windows\Start Menu\Programs\RepairShop Manager""
$desktopShortcut = Join-Path ([Environment]::GetFolderPath(""Desktop"")) ""RepairShop Manager.lnk""
Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $startMenuDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ""HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RepairShopManager"" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $installDir -Recurse -Force
if (!$Quiet) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(""RepairShop Manager was uninstalled. Shop data in LocalAppData\RepairShopManager was not removed."", ""RepairShop Manager"") | Out-Null
}
";
        File.WriteAllText(uninstallPath, script);
    }

    private static void RegisterUninstall(string installDir, string exePath, string uninstallPath)
    {
        long estimatedSizeKb = new FileInfo(exePath).Length / 1024;
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\RepairShopManager"))
        {
            key.SetValue("DisplayName", AppName);
            key.SetValue("DisplayVersion", Version);
            key.SetValue("Publisher", "RepairShop");
            key.SetValue("InstallLocation", installDir);
            key.SetValue("DisplayIcon", exePath);
            key.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"" + uninstallPath + "\"");
            key.SetValue("QuietUninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"" + uninstallPath + "\" -Quiet");
            key.SetValue("EstimatedSize", (int)Math.Min(Int32.MaxValue, estimatedSizeKb), RegistryValueKind.DWord);
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

internal sealed class SetupForm : Form
{
    private readonly TextBox pathBox;
    private readonly CheckBox desktopShortcut;
    private readonly Button installButton;
    private readonly Button cancelButton;
    private readonly Label statusLabel;
    internal int ExitCode { get; private set; }

    internal SetupForm()
    {
        Text = "RepairShop Manager Setup";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ClientSize = new Size(780, 590);
        Font = new Font("Segoe UI", 9F);
        ExitCode = 1;

        Label title = new Label();
        title.Text = "Install RepairShop Manager";
        title.Font = new Font("Segoe UI", 16F, FontStyle.Bold);
        title.AutoSize = true;
        title.Location = new Point(24, 20);
        Controls.Add(title);

        Label subtitle = new Label();
        subtitle.Text = "Complete offline setup for this Windows user.";
        subtitle.AutoSize = true;
        subtitle.Location = new Point(27, 56);
        Controls.Add(subtitle);

        RichTextBox readme = new RichTextBox();
        readme.Multiline = true;
        readme.ReadOnly = true;
        readme.BorderStyle = BorderStyle.FixedSingle;
        readme.BackColor = Color.White;
        readme.ScrollBars = RichTextBoxScrollBars.Vertical;
        readme.WordWrap = true;
        readme.DetectUrls = false;
        readme.Text = RepairShopManagerSetup.ReadmeText;
        readme.Location = new Point(28, 92);
        readme.Size = new Size(724, 286);
        Controls.Add(readme);

        Label pathLabel = new Label();
        pathLabel.Text = "Install folder";
        pathLabel.AutoSize = true;
        pathLabel.Location = new Point(28, 402);
        Controls.Add(pathLabel);

        pathBox = new TextBox();
        pathBox.Text = RepairShopManagerSetup.DefaultInstallDir;
        pathBox.Location = new Point(28, 426);
        pathBox.Size = new Size(620, 24);
        Controls.Add(pathBox);

        Button browse = new Button();
        browse.Text = "Browse...";
        browse.Location = new Point(664, 424);
        browse.Size = new Size(88, 28);
        browse.Click += BrowseClicked;
        Controls.Add(browse);

        desktopShortcut = new CheckBox();
        desktopShortcut.Text = "Create Desktop shortcut";
        desktopShortcut.Checked = true;
        desktopShortcut.AutoSize = true;
        desktopShortcut.Location = new Point(28, 464);
        Controls.Add(desktopShortcut);

        statusLabel = new Label();
        statusLabel.Text = "";
        statusLabel.AutoSize = false;
        statusLabel.Location = new Point(28, 502);
        statusLabel.Size = new Size(724, 24);
        Controls.Add(statusLabel);

        installButton = new Button();
        installButton.Text = "Install";
        installButton.Location = new Point(572, 542);
        installButton.Size = new Size(86, 30);
        installButton.Click += InstallClicked;
        Controls.Add(installButton);

        cancelButton = new Button();
        cancelButton.Text = "Cancel";
        cancelButton.Location = new Point(666, 542);
        cancelButton.Size = new Size(86, 30);
        cancelButton.Click += delegate { Close(); };
        Controls.Add(cancelButton);
    }

    private void BrowseClicked(object sender, EventArgs e)
    {
        using (FolderBrowserDialog dialog = new FolderBrowserDialog())
        {
            dialog.Description = "Choose where RepairShop Manager should be installed";
            dialog.SelectedPath = pathBox.Text;
            dialog.ShowNewFolderButton = true;
            if (dialog.ShowDialog(this) == DialogResult.OK)
            {
                pathBox.Text = dialog.SelectedPath;
            }
        }
    }

    private void InstallClicked(object sender, EventArgs e)
    {
        try
        {
            installButton.Enabled = false;
            cancelButton.Enabled = false;
            statusLabel.Text = "Installing...";
            Application.DoEvents();

            RepairShopManagerSetup.Install(pathBox.Text, desktopShortcut.Checked);

            statusLabel.Text = "Installed successfully.";
            ExitCode = 0;
            installButton.Visible = false;
            cancelButton.Text = "Close";
            cancelButton.Enabled = true;
            statusLabel.Text = "Installed successfully. Use the Desktop or Start Menu shortcut to open RepairShop Manager.";
        }
        catch (Exception ex)
        {
            installButton.Enabled = true;
            cancelButton.Enabled = true;
            statusLabel.Text = "Installation failed.";
            MessageBox.Show(
                this,
                "RepairShop Manager could not be installed.\n\n" + ex.Message,
                "RepairShop Manager Setup",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }
}
'@
$source = $source.Replace("__VERSION__", $Version)
Set-Content -LiteralPath $sourcePath -Value $source -Encoding UTF8

$compiler = Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (!(Test-Path $compiler)) {
    throw "The .NET Framework C# compiler was not found: $compiler"
}

$outputArg = "/out:$setupPath"
$resourceArg = "/resource:$inputPath,RepairShopPayload"
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:Microsoft.CSharp.dll $outputArg $resourceArg $sourcePath
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
