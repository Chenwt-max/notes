param([string]$ScriptPath, [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$lesson = [IO.File]::ReadAllText($ScriptPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1
    if (-not $voice) { throw 'A locally installed zh-CN Windows voice is required.' }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $synth.Rate = 0
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    [IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
    $index = 0
    foreach ($slide in $lesson.slides) {
        foreach ($sentence in $slide.sentences) {
            $path = Join-Path $OutputDirectory ('speech-{0:D2}.wav' -f $index)
            if (-not (Test-Path -LiteralPath $path)) {
                $synth.SetOutputToWaveFile($path, $format)
                $synth.Speak($sentence)
                $synth.SetOutputToNull()
            }
            $index++
        }
    }
} finally { $synth.Dispose() }
