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

        $scale = [Math]::Min(
            [double]$Width / [double]$original.Width,
            [double]$Height / [double]$original.Height
        )
        $drawWidth = [Math]::Max(1, [int][Math]::Round($original.Width * $scale))
        $drawHeight = [Math]::Max(1, [int][Math]::Round($original.Height * $scale))
        $offsetX = [int][Math]::Floor(($Width - $drawWidth) / 2)
        $offsetY = [int][Math]::Floor(($Height - $drawHeight) / 2)

        $bmp = New-Object System.Drawing.Bitmap($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bmp)
        try {
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.Clear([System.Drawing.Color]::White)
            $graphics.DrawImage($original, $offsetX, $offsetY, $drawWidth, $drawHeight)
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

function New-FinishWizardBitmap {
    param(
        [string]$Destination,
        [int]$Width = 164,
        [int]$Height = 314
    )

    $bmp = New-Object System.Drawing.Bitmap($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bmp)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

        $backgroundBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(0, 18, 126))
        $stripePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(0, 32, 150), 1)
        $arrowPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(0, 44, 160), 8)
        $arrowPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
        $iconFrameBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $iconFillBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(235, 238, 245))
        $iconLinePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(30, 30, 35), 3)
        try {
            $graphics.FillRectangle($backgroundBrush, 0, 0, $Width, $Height)

            for ($row = 0; $row -lt $Height; $row += 3) {
                $graphics.DrawLine($stripePen, 0, $row, $Width, $row)
            }

            $graphics.DrawLine($arrowPen, 15, 186, 73, 128)
            $graphics.DrawLine($arrowPen, 73, 128, 38, 128)
            $graphics.DrawLine($arrowPen, 73, 128, 73, 92)
            $graphics.DrawLine($arrowPen, 15, 245, 98, 245)
            $graphics.DrawLine($arrowPen, 98, 245, 68, 215)
            $graphics.DrawLine($arrowPen, 98, 245, 68, 275)

            $graphics.FillRectangle($iconFrameBrush, 70, 20, 60, 60)
            $graphics.FillRectangle($iconFillBrush, 76, 26, 48, 48)
            $graphics.DrawRectangle($iconLinePen, 84, 42, 26, 20)
            $graphics.DrawLine($iconLinePen, 84, 42, 97, 35)
            $graphics.DrawLine($iconLinePen, 110, 42, 97, 35)
            $graphics.DrawArc($iconLinePen, 82, 54, 32, 18, 20, 280)
        } finally {
            $backgroundBrush.Dispose()
            $stripePen.Dispose()
            $arrowPen.Dispose()
            $iconFrameBrush.Dispose()
            $iconFillBrush.Dispose()
            $iconLinePen.Dispose()
        }
        $bmp.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Bmp)
    } finally {
        $graphics.Dispose()
        $bmp.Dispose()
    }
    Write-Output "Generated $Destination"
}

Convert-ImageToBmp -Source "quantide.png" -Destination "quantide.bmp" -Width 0 -Height 0
Convert-ImageToBmp -Source "contact-us.jpg" -Destination "contact-us.bmp" -Width 280 -Height 280
New-FinishWizardBitmap -Destination "finish-wizard.bmp" -Width 164 -Height 314
Convert-PngToIco -Source "quantide.png" -Destination "quantide.ico"
