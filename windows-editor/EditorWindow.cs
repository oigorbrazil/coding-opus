using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;
using Microsoft.Web.WebView2.WinForms;

internal sealed class EditorWindow : Form
{
    private const int UseImmersiveDarkMode = 20;
    private const int SettingsChanged = 0x001A;
    private const int ThemeChanged = 0x031A;
    private readonly WebView2 view;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    [DllImport("dwmapi.dll")]
    private static extern int DwmGetWindowAttribute(IntPtr window, int attribute, out int value, int size);

    public EditorWindow(WebView2 view)
    {
        this.view = view;
        ApplyTheme();
    }

    private static bool UsesDarkTheme()
    {
        var lightTheme = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "AppsUseLightTheme", 1);
        return !SystemInformation.HighContrast && lightTheme is int && (int)lightTheme == 0;
    }

    protected override void OnHandleCreated(EventArgs args)
    {
        base.OnHandleCreated(args);
        ApplyTheme();
    }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if ((message.Msg == SettingsChanged || message.Msg == ThemeChanged) && !Disposing && IsHandleCreated)
            ApplyTheme();
    }

    private void ApplyTheme()
    {
        bool dark = UsesDarkTheme();
        BackColor = SystemInformation.HighContrast ? SystemColors.Window
            : dark ? Color.FromArgb(11, 11, 13) : Color.FromArgb(229, 229, 234);
        if (view != null && !view.IsDisposed)
            view.DefaultBackgroundColor = BackColor;
        if (IsHandleCreated)
        {
            int immersive = dark ? 1 : 0;
            DwmSetWindowAttribute(Handle, UseImmersiveDarkMode, ref immersive, sizeof(int));
        }
    }

    public void VerifyCaptionTheme()
    {
        int immersive;
        if (DwmGetWindowAttribute(Handle, UseImmersiveDarkMode, out immersive, sizeof(int)) != 0)
            return;
        if (immersive != (UsesDarkTheme() ? 1 : 0))
            throw new InvalidOperationException("A barra de título não acompanhou o tema do Windows.");
        Console.WriteLine(immersive == 1 ? "caption-theme: dark" : "caption-theme: light");
    }
}
