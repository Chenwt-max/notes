param([Parameter(Mandatory=$true)][string]$Source,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$existing=@(Get-Process POWERPNT -ErrorAction SilentlyContinue).Count -gt 0
$app=$null; $presentation=$null; $security=$null; $alerts=$null
try {
    $app=New-Object -ComObject PowerPoint.Application
    $security=$app.AutomationSecurity; $alerts=$app.DisplayAlerts
    $app.AutomationSecurity=3
    $app.DisplayAlerts=1
    $presentation=$app.Presentations.Open($Source,-1,0,0)
    # Render every source page, including slides hidden from a slideshow.
    # Only this read-only presentation in memory changes; the source is never saved.
    foreach ($slide in $presentation.Slides) { $slide.SlideShowTransition.Hidden=0 }
    $presentation.SaveAs($Destination,32)
} finally {
    if ($null -ne $presentation) { $presentation.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($null -ne $app) {
        if ($null -ne $security) { $app.AutomationSecurity=$security; $app.DisplayAlerts=$alerts }
        if (-not $existing -and $app.Presentations.Count -eq 0) { $app.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    }
}
