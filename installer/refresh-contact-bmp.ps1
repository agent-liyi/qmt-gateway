param(
    [Parameter(Mandatory = $true)]
    [string]$PluginDir,

    [Parameter(Mandatory = $true)]
    [string]$BmpName,

    [Parameter(Mandatory = $true)]
    [string]$JpgName,

    [Parameter(Mandatory = $true)]
    [string]$CdnUrl,

    [Parameter()]
    [string]$ReadyFlagName = 'contact-us.ready',

    [Parameter()]
    [int]$BmpWidth = 280,

    [Parameter()]
    [int]$BmpHeight = 280
)

$ErrorActionPreference = 'Stop'

$pluginDir = [System.IO.Path]::GetFullPath($PluginDir)
New-Item -ItemType Directory -Path $pluginDir -Force | Out-Null

$bmpPath = Join-Path $pluginDir $BmpName
$jpgPath = Join-Path $pluginDir $JpgName
$readyFlagPath = Join-Path $pluginDir $ReadyFlagName

function Convert-JpgToBmp {
    param([string]$Source, [string]$Destination, [int]$Width, [int]$Height)

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source JPG not found: $Source"
    }

    Add-Type -AssemblyName System.Drawing

    $image = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Source))
    try {
        if ($Width -le 0) { $Width = $image.Width }
        if ($Height -le 0) { $Height = $image.Height }

        $scale = [Math]::Min(
            [double]$Width / [double]$image.Width,
            [double]$Height / [double]$image.Height
        )
        $drawWidth = [Math]::Max(1, [int][Math]::Round($image.Width * $scale))
        $drawHeight = [Math]::Max(1, [int][Math]::Round($image.Height * $scale))
        $offsetX = [int][Math]::Floor(($Width - $drawWidth) / 2)
        $offsetY = [int][Math]::Floor(($Height - $drawHeight) / 2)

        $bmp = New-Object System.Drawing.Bitmap($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bmp)
        try {
            $graphics.Clear([System.Drawing.Color]::White)
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.DrawImage($image, $offsetX, $offsetY, $drawWidth, $drawHeight)
        } finally {
            $graphics.Dispose()
        }
        $bmp.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Bmp)
        $bmp.Dispose()
    } finally {
        $image.Dispose()
    }
}

# Try to download the freshest QR from the CDN with a 3 second timeout. The
# installer ships a local JPG in the same directory; the local file is
# bundled as the page bitmap so the welcome screen is never blank.
$downloaded = $false
try {
    $previousPreference = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        $request = [System.Net.HttpWebRequest]::Create($CdnUrl)
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $request.Method = 'GET'
        $response = $request.GetResponse()
        try {
            if ($response.StatusCode -eq [System.Net.HttpStatusCode]::OK) {
                $stream = $response.GetResponseStream()
                try {
                    $fileStream = [System.IO.File]::Create($jpgPath)
                    try {
                        $stream.CopyTo($fileStream)
                    } finally {
                        $fileStream.Dispose()
                    }
                } finally {
                    $stream.Dispose()
                }
                $downloaded = $true
            }
        } finally {
            $response.Dispose()
        }
    } finally {
        $ProgressPreference = $previousPreference
    }
} catch {
    # Network is not available or timed out; the local JPG is still in place.
    $downloaded = $false
}

# Convert the JPG to a BMP sized to the dialog. The output path always
# overwrites the bundled contact-us.bmp so the welcome page picks it up
# from $PLUGINSDIR.
Convert-JpgToBmp -Source $jpgPath -Destination $bmpPath -Width $BmpWidth -Height $BmpHeight
Set-Content -LiteralPath $readyFlagPath -Encoding ASCII -Value $(if ($downloaded) { 'downloaded' } else { 'local' })

exit 0
