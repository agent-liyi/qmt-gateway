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

function Convert-PngToIco {
    param(
        [string]$Source,
        [string]$Destination,
        [int[]]$Sizes = @(16, 32, 48, 64, 128, 256)
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Source image not found: $Source"
    }

    $original = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Source))
    try {
        $bitmaps = @()
        foreach ($size in $Sizes) {
            $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
            $graphics = [System.Drawing.Graphics]::FromImage($bmp)
            try {
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $graphics.Clear([System.Drawing.Color]::Transparent)
                $graphics.DrawImage($original, 0, 0, $size, $size)
            } finally {
                $graphics.Dispose()
            }
            $bitmaps += $bmp
        }

        $stream = [System.IO.File]::Create($Destination)
        try {
            $writer = New-Object System.IO.BinaryWriter($stream)
            try {
                $iconDir = New-Object 'System.Collections.Generic.List[byte]'
                $iconDir.Add([byte]0)
                $iconDir.Add([byte]0)
                $iconDir.Add([byte]1)
                $iconDir.Add([byte]0)
                $iconDir.Add([byte]$bitmaps.Count)
                $iconDir.Add([byte]0)

                $imageBytes = @()
                $offset = 6 + (16 * $bitmaps.Count)
                foreach ($bmp in $bitmaps) {
                    $ms = New-Object System.IO.MemoryStream
                    try {
                        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
                    } finally {
                        $bmp.Dispose()
                    }
                    $bytes = $ms.ToArray()
                    $ms.Dispose()
                    $imageBytes += , $bytes

                    $sizeField = if ($bmp.Width -ge 256) { [byte]0 } else { [byte]$bmp.Width }
                    $iconDir.Add($sizeField)
                    $iconDir.Add($sizeField)
                    $iconDir.Add([byte]0)
                    $iconDir.Add([byte]0)
                    $iconDir.Add([byte]1)
                    $iconDir.Add([byte]0)
                    $iconDir.Add([byte]32)
                    $iconDir.Add([byte]0)

                    $byteCount = $bytes.Length
                    $iconDir.Add([byte]($byteCount -band 0xFF))
                    $iconDir.Add([byte](($byteCount -shr 8) -band 0xFF))
                    $iconDir.Add([byte](($byteCount -shr 16) -band 0xFF))
                    $iconDir.Add([byte](($byteCount -shr 24) -band 0xFF))

                    $iconDir.Add([byte]($offset -band 0xFF))
                    $iconDir.Add([byte](($offset -shr 8) -band 0xFF))
                    $iconDir.Add([byte](($offset -shr 16) -band 0xFF))
                    $iconDir.Add([byte](($offset -shr 24) -band 0xFF))

                    $offset += $byteCount
                }

                $writer.Write($iconDir.ToArray())
                foreach ($bytes in $imageBytes) {
                    $writer.Write($bytes)
                }
            } finally {
                $writer.Dispose()
            }
        } finally {
            $stream.Dispose()
        }
    } finally {
        $original.Dispose()
    }
    Write-Output "Generated $Destination"
}

Convert-ImageToBmp -Source "quantide.png" -Destination "quantide.bmp" -Width 0 -Height 0
Convert-ImageToBmp -Source "contact-us.jpg" -Destination "contact-us.bmp" -Width 164 -Height 314
Convert-PngToIco -Source "quantide.png" -Destination "quantide.ico"
