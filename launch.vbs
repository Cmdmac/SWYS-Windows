' Silent launcher: hides the console window and starts the app via run.bat.
' MUST be pure ASCII (ANSI). VBScript cannot parse UTF-8 source with non-ASCII chars.
Set ws = CreateObject("WScript.Shell")
full = WScript.ScriptFullName
scriptDir = Left(full, InStrRev(full, "\"))

' Write a trace immediately so we always know the VBS executed (no fso needed).
traceFile = scriptDir & "vbs_trace.log"
ws.Run "cmd /c echo %DATE% %TIME% launch.vbs executed >> """ & traceFile & """", 0, True

bat = """" & scriptDir & "run.bat"" silent"
rc = ws.Run(bat, 0, True)

If rc <> 0 Then
    MsgBox "VoiceControl failed to start (exit code " & rc & ")." & vbCrLf & vbCrLf & _
           "Log folder (open this in Explorer):" & vbCrLf & _
           "  " & scriptDir & vbCrLf & vbCrLf & _
           "Check these files in that folder:" & vbCrLf & _
           "  vbs_trace.log" & vbCrLf & _
           "  bat_trace.log" & vbCrLf & _
           "  launch_trace.log" & vbCrLf & _
           "  voice_control_error.log", vbCritical, "VoiceControl launch failed"
End If
