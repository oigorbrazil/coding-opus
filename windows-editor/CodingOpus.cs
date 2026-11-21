using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal static class CodingOpus
{
    private const string Product = "Coding Opus";
    private static readonly string AppFolder = AppDomain.CurrentDomain.BaseDirectory;
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    [STAThread]
    private static int Main(string[] args)
    {
        bool smoke = args.Length == 1 && args[0] == "--smoke";
        string mode = args.Length == 0 ? "" : args[0];
        try
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            if (mode == "--prompt")
                return OfferInstallation() ? 0 : 2;
            if (mode == "--check-runtime")
            {
                CoreWebView2Environment.GetAvailableBrowserVersionString();
                return 0;
            }
            if (mode == "--register")
            {
                RegisterShortcut();
                return 0;
            }
            return RunEditor(mode == "--url" && args.Length == 2 ? args[1] : null, smoke);
        }
        catch (Exception error)
        {
            if (mode == "" || mode == "--url")
                MessageBox.Show(error.Message, Product, MessageBoxButtons.OK, MessageBoxIcon.Error);
            else
                Console.Error.WriteLine(error.Message);
            return 1;
        }
    }

    private static bool OfferInstallation()
    {
        using (var dialog = new Form())
        using (var label = new Label())
        using (var buttons = new FlowLayoutPanel())
        using (var install = new Button())
        using (var later = new Button())
        {
            dialog.Text = Product;
            dialog.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            dialog.Font = SystemFonts.MessageBoxFont;
            dialog.FormBorderStyle = FormBorderStyle.FixedDialog;
            dialog.StartPosition = FormStartPosition.CenterScreen;
            dialog.MaximizeBox = false;
            dialog.MinimizeBox = false;
            dialog.ClientSize = new Size(460, 146);
            dialog.AutoScaleMode = AutoScaleMode.Font;
            label.Text = "Instalar o aplicativo Coding Opus?\r\n\r\nAbra o editor de Playbooks pelo menu Iniciar, em uma janela própria.";
            label.Dock = DockStyle.Fill;
            label.Padding = new Padding(18, 18, 18, 0);
            buttons.Dock = DockStyle.Bottom;
            buttons.Height = 53;
            buttons.Padding = new Padding(12, 7, 12, 0);
            buttons.FlowDirection = FlowDirection.RightToLeft;
            buttons.WrapContents = false;
            install.Text = "Instalar";
            install.DialogResult = DialogResult.Yes;
            install.Size = new Size(94, 31);
            later.Text = "Agora não";
            later.DialogResult = DialogResult.No;
            later.Size = install.Size;
            buttons.Controls.Add(later);
            buttons.Controls.Add(install);
            dialog.Controls.Add(label);
            dialog.Controls.Add(buttons);
            dialog.AcceptButton = install;
            dialog.CancelButton = later;
            return dialog.ShowDialog() == DialogResult.Yes;
        }
    }

    private static void RegisterShortcut()
    {
        string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
        if (string.IsNullOrEmpty(programs))
            throw new InvalidOperationException("O menu Iniciar do usuário não foi encontrado.");
        Directory.CreateDirectory(programs);
        string path = Path.Combine(programs, Product + ".lnk");
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell", true));
        dynamic link = shell.CreateShortcut(path);
        string target = link.TargetPath;
        if (File.Exists(path) && !string.Equals(target, Application.ExecutablePath, StringComparison.OrdinalIgnoreCase))
        {
            string releases = Directory.GetParent(AppFolder.TrimEnd(Path.DirectorySeparatorChar)).FullName;
            string previous = Path.GetDirectoryName(target);
            if (string.IsNullOrEmpty(previous) || !string.Equals(Path.GetFileName(target), Product + ".exe",
                    StringComparison.OrdinalIgnoreCase) || !string.Equals(Directory.GetParent(previous).FullName,
                    releases, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Já existe um atalho Coding Opus apontando para outro aplicativo.");
        }
        link.TargetPath = Application.ExecutablePath;
        link.Arguments = "";
        link.WorkingDirectory = AppFolder;
        link.Description = "Editor de Playbooks da Coding Opus";
        link.IconLocation = Application.ExecutablePath + ",0";
        link.Save();
    }

    public sealed class LauncherSettings
    {
        public string python { get; set; }
        public string script { get; set; }
        public string policy { get; set; }
    }

    public sealed class ServerResponse
    {
        public string url { get; set; }
    }

    private static string StartEditor()
    {
        var settings = Json.Deserialize<LauncherSettings>(File.ReadAllText(Path.Combine(AppFolder, "launcher.json")));
        if (!File.Exists(settings.python) || !File.Exists(settings.script))
            throw new InvalidOperationException("A instalação da skill mudou. Reinstale o aplicativo pelo comando da Opus.");
        string arguments = Quote(settings.script) + " --launch --no-open --policy " + Quote(settings.policy);
        var start = new ProcessStartInfo(settings.python, arguments)
        {
            WorkingDirectory = Path.GetDirectoryName(settings.script),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8
        };
        start.EnvironmentVariables["PYTHONUTF8"] = "1";
        using (var process = Process.Start(start))
        {
            var output = process.StandardOutput.ReadToEndAsync();
            var errors = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(20000))
            {
                process.Kill();
                throw new InvalidOperationException("O servidor local da Opus demorou para iniciar.");
            }
            if (process.ExitCode != 0)
            {
                string detail = errors.GetAwaiter().GetResult().Trim();
                if (detail.Length > 700)
                    detail = detail.Substring(detail.Length - 700);
                throw new InvalidOperationException("O servidor local da Opus não iniciou.\r\n" + detail);
            }
            return Json.Deserialize<ServerResponse>(output.GetAwaiter().GetResult()).url;
        }
    }

    private static string Quote(string path)
    {
        if (string.IsNullOrEmpty(path) || path.IndexOf('"') != -1)
            throw new InvalidOperationException("A configuração do aplicativo contém um caminho inválido.");
        return "\"" + path + "\"";
    }

    private static int RunEditor(string suppliedUrl, bool smoke)
    {
        using (var view = new WebView2())
        using (var window = new EditorWindow(view))
        {
            window.Text = Product;
            window.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            window.Size = new Size(1280, 850);
            window.MinimumSize = new Size(420, 420);
            window.StartPosition = FormStartPosition.CenterScreen;
            view.Dock = DockStyle.Fill;
            window.Controls.Add(view);
            var context = new ApplicationContext();
            int exit = 0;
            Func<Task> initialize = async () =>
            {
                try
                {
                    string url = suppliedUrl ?? await Task.Run((Func<string>)StartEditor);
                    Uri address;
                    if (!Uri.TryCreate(url, UriKind.Absolute, out address) || address.Scheme != Uri.UriSchemeHttp
                        || address.Host != "127.0.0.1" || address.Port <= 0 || !address.Fragment.StartsWith("#token=", StringComparison.Ordinal))
                        throw new InvalidOperationException("O servidor local da Opus devolveu um endereço inválido.");
                    string dataFolder = smoke
                        ? Path.Combine(Path.GetTempPath(), "CodingOpus-WebView2-Smoke")
                        : Path.Combine(Directory.GetParent(AppFolder.TrimEnd(Path.DirectorySeparatorChar)).FullName, "WebView2");
                    var environment = await CoreWebView2Environment.CreateAsync(null, dataFolder);
                    await view.EnsureCoreWebView2Async(environment);
                    view.CoreWebView2.NavigationStarting += (sender, args) =>
                    {
                        Uri destination;
                        args.Cancel = !Uri.TryCreate(args.Uri, UriKind.Absolute, out destination)
                            || destination.GetLeftPart(UriPartial.Authority) != address.GetLeftPart(UriPartial.Authority);
                        if (args.Cancel && args.IsUserInitiated)
                            OpenExternal(args.Uri);
                    };
                    view.CoreWebView2.NewWindowRequested += (sender, args) =>
                    {
                        args.Handled = true;
                        if (args.IsUserInitiated)
                            OpenExternal(args.Uri);
                    };
                    view.CoreWebView2.Navigate(address.AbsoluteUri);
                    if (smoke)
                    {
                        await WaitForPlaybooks(view.CoreWebView2);
                        window.VerifyCaptionTheme();
                        context.ExitThread();
                    }
                }
                catch (Exception error)
                {
                    exit = 1;
                    if (smoke)
                    {
                        Console.Error.WriteLine(error.Message);
                        context.ExitThread();
                    }
                    else if (!window.IsDisposed)
                    {
                        MessageBox.Show(window, error.Message, Product, MessageBoxButtons.OK, MessageBoxIcon.Error);
                        window.Close();
                    }
                }
            };
            if (smoke)
            {
                var handle = view.Handle;
                EventHandler idle = null;
                idle = async (_, __) =>
                {
                    Application.Idle -= idle;
                    await initialize();
                };
                Application.Idle += idle;
                Application.Run(context);
            }
            else
            {
                window.Shown += async (_, __) => await initialize();
                Application.Run(window);
            }
            context.Dispose();
            return exit;
        }
    }

    private static void OpenExternal(string url)
    {
        Uri address;
        if (!Uri.TryCreate(url, UriKind.Absolute, out address) || address.IsLoopback
            || (address.Scheme != Uri.UriSchemeHttp && address.Scheme != Uri.UriSchemeHttps))
            return;
        try { Process.Start(new ProcessStartInfo(address.AbsoluteUri) { UseShellExecute = true }); }
        catch (System.ComponentModel.Win32Exception) { }
    }

    private static async Task WaitForPlaybooks(CoreWebView2 view)
    {
        for (int attempt = 0; attempt < 30; attempt++)
        {
            if (await view.ExecuteScriptAsync("!!document.querySelector('.editor-body svg[class*=canvas]') && !document.querySelector('[data-startup-splash]')") == "true")
                return;
            await Task.Delay(300);
        }
        throw new InvalidOperationException("O editor não exibiu o canvas de Playbooks.");
    }
}
