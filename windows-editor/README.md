# Coding Opus for Windows

Source of `Coding Opus.exe`, the small WinForms window that shows the editor page through the
Microsoft WebView2 runtime. `skills/coding/scripts/desktop_editor.py` unpacks the built package,
`skills/coding/assets/windows-editor.zip`, into `%LOCALAPPDATA%\Coding Opus\Editor` and registers
the Start menu entry; the app starts `editor_server.py` from its `launcher.json`.

Build on Windows with the .NET Framework compiler and the official WebView2 package
(`Microsoft.Web.WebView2` 1.0.4314.35, checked by SHA-256):

```powershell
./build.ps1 -SdkPackage microsoft.web.webview2.1.0.4314.35.nupkg -Output ../skills/coding/assets/windows-editor.zip
```

The icon defaults to `skills/coding/assets/coding-opus-app.png`.
