param(
    [Parameter(Mandatory)] [string] $SdkPackage,
    [string] $Logo,
    [Parameter(Mandatory)] [string] $Output
)

$ErrorActionPreference = 'Stop'
if (-not $PSBoundParameters.ContainsKey('Logo')) {
    $Logo = Join-Path $PSScriptRoot '../skills/coding/assets/coding-opus-app.png'
}
$sdk = (Resolve-Path -LiteralPath $SdkPackage).Path
$logoPath = (Resolve-Path -LiteralPath $Logo).Path
$destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
$expected = '90778DEB1B77E36292828B4B5833C9255C27533F40E0DDD55891AE718944EDC4'
if ((Get-FileHash -LiteralPath $sdk -Algorithm SHA256).Hash -ne $expected) {
    throw 'Expected the official Microsoft.Web.WebView2 1.0.4314.35 package.'
}

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Store PNG entries directly to preserve full color and alpha at every icon size.
function Write-AppIcon([string] $Source, [string] $Destination) {
    $image = [Drawing.Image]::FromFile($Source)
    $sizes = @(16, 32, 48, 64, 128)
    try {
        $entries = foreach ($size in $sizes) {
            $bitmap = [Drawing.Bitmap]::new($image, $size, $size)
            $stream = [IO.MemoryStream]::new()
            try {
                $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
                @{ Size = $size; Png = $stream.ToArray() }
            } finally {
                $stream.Dispose()
                $bitmap.Dispose()
            }
        }
    } finally {
        $image.Dispose()
    }

    $writer = [IO.BinaryWriter]::new([IO.File]::Create($Destination))
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$entries.Count)
        $offset = 6 + 16 * $entries.Count
        foreach ($entry in $entries) {
            $writer.Write([byte]$entry.Size)
            $writer.Write([byte]$entry.Size)
            $writer.Write([uint16]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$entry.Png.Length)
            $writer.Write([uint32]$offset)
            $offset += $entry.Png.Length
        }
        foreach ($entry in $entries) {
            $writer.Write([byte[]]$entry.Png)
        }
    } finally {
        $writer.Dispose()
    }
}

$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
$tempRoot = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path
$work = Join-Path $tempRoot ('coding-opus-editor-' + [Guid]::NewGuid().ToString('N'))
$files = Join-Path $work 'files'
New-Item -ItemType Directory -Force -Path $files | Out-Null
try {
    $archive = [IO.Compression.ZipFile]::OpenRead($sdk)
    try {
        $assets = [ordered]@{
            'LICENSE.txt' = 'LICENSE.txt'
            'Microsoft.Web.WebView2.Core.dll' = 'lib/net462/Microsoft.Web.WebView2.Core.dll'
            'Microsoft.Web.WebView2.WinForms.dll' = 'lib/net462/Microsoft.Web.WebView2.WinForms.dll'
        }
        foreach ($arch in @('x86', 'x64', 'arm64')) {
            $path = "runtimes/win-$arch/native/WebView2Loader.dll"
            $assets[$path] = $path
        }
        foreach ($file in $assets.Keys) {
            $target = Join-Path $files $file
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($archive.GetEntry($assets[$file]), $target)
        }
    } finally {
        $archive.Dispose()
    }
    $iconPath = Join-Path $work 'coding-opus.ico'
    Write-AppIcon $logoPath $iconPath
    $binary = Join-Path $files 'Coding Opus.exe'
    $core = Join-Path $files 'Microsoft.Web.WebView2.Core.dll'
    $winforms = Join-Path $files 'Microsoft.Web.WebView2.WinForms.dll'
    $references = @('System.dll', 'System.Drawing.dll', 'System.Windows.Forms.dll', 'System.Web.Extensions.dll',
        'Microsoft.CSharp.dll', $core, $winforms) | ForEach-Object { '/reference:' + $_ }
    & $compiler /nologo /target:winexe /platform:anycpu /optimize+ "/win32icon:$iconPath" "/out:$binary" @references (Join-Path $PSScriptRoot 'CodingOpus.cs') (Join-Path $PSScriptRoot 'EditorWindow.cs')
    if ($LASTEXITCODE -ne 0) { throw 'The Coding Opus application build failed.' }
    $package = Join-Path $work 'windows-editor.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($files, $package, [IO.Compression.CompressionLevel]::Optimal, $false)
    [IO.File]::Copy($package, $destination, $true)
    Get-Item -LiteralPath $destination | Select-Object FullName,Length
} finally {
    $resolvedWork = (Resolve-Path -LiteralPath $work).Path
    if ([IO.Path]::GetDirectoryName($resolvedWork) -ieq $tempRoot -and
        [IO.Path]::GetFileName($resolvedWork) -like 'coding-opus-editor-*') {
        Remove-Item -LiteralPath $resolvedWork -Recurse -Force
    }
}
