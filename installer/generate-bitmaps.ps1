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

# Square contact-us QR used as the left-side artwork on the welcome page.
# 180x180 keeps it visually balanced against the text on the right and
# prevents the squashed 164x314 aspect ratio. The welcome page reads it via
# MUI_WELCOMEPAGE_BITMAP; the finish page reads it via MUI_FINISHPAGE_BITMAP.
Convert-ImageToBmp -Source "contact-us.jpg" -Destination "contact-us.bmp" -Width 180 -Height 180
# quantide.png is no longer used: the installer lets NSIS use its default icon
# and does not draw a brand mark on the title bar, taskbar, or wizard header.
