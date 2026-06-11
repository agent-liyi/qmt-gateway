Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Convert-ImageToBmp {
    param(
        [string]$Source,
        [string]$Destination,
        [int]$Width,
        [int]$Height
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source image not found: $Source"
    }

    $original = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Source))
    try {
        if ($Width -le 0) { $Width = $original.Width }
        if ($Height -le 0) { $Height = $original.Height }

        $bmp = New-Object System.Drawing.Bitmap($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bmp)
        try {
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.Clear([System.Drawing.Color]::White)
            $graphics.DrawImage($original, 0, 0, $Width, $Height)
        } finally {
            $graphics.Dispose()
        }
        $bmp.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Bmp)
        $bmp.Dispose()
    } finally {
        $original.Dispose()
    }
    Write-Output "Generated $Destination"
}

# Contact-us QR used as the left-side artwork on the welcome / finish
# pages. The source is contact-us.png, a 704x1280 PNG (aspect 0.55 - tall).
# The MUI2 left-side bitmap slot is 109x193 (aspect 0.56). Using 109x193 as
# the BMP target lets Convert-ImageToBmp draw the QR at its native aspect
# ratio (~106x193 inside the 109x193 BMP) so it fills the slot edge-to-
# edge with no squashing and only a sliver of side margin.
Convert-ImageToBmp -Source "contact-us.png" -Destination "contact-us.bmp" -Width 109 -Height 193
# quantide.png is no longer used: the installer lets NSIS use its default icon
# and does not draw a brand mark on the title bar, taskbar, or wizard header.
