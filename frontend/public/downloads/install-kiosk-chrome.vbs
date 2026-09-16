Option Explicit

Const CRM_URL = "http://5.129.243.246:8080/?print_mode=kiosk"
Const LNK_NAME = "Fulfillment CRM (autoprint).lnk"
Const PROFILE_DIR = "FulfillmentCRM-Print"

Dim fso, shell, chrome, profilePath, args, targets, i, folderPath, created, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

WScript.Echo "============================================"
WScript.Echo " Fulfillment CRM - Chrome autoprint FBS"
WScript.Echo "============================================"
WScript.Echo ""

chrome = FindChrome()
If chrome = "" Then
  WScript.Echo "[ERROR] Google Chrome not found."
  WScript.Echo "Install Chrome: https://www.google.com/chrome/"
  WScript.Quit 1
End If

profilePath = shell.ExpandEnvironmentStrings("%LocalAppData%") & "\" & PROFILE_DIR
If Not fso.FolderExists(profilePath) Then
  fso.CreateFolder profilePath
End If

WScript.Echo "Chrome:  " & chrome
WScript.Echo "CRM:     " & CRM_URL
WScript.Echo "Profile: " & profilePath
WScript.Echo ""

args = "--user-data-dir=""" & profilePath & """ --disable-extensions --kiosk-printing --new-window " & CRM_URL
created = 0

targets = Array( _
  shell.SpecialFolders("Desktop"), _
  shell.SpecialFolders("Programs"), _
  fso.GetParentFolderName(WScript.ScriptFullName) _
)

For i = 0 To UBound(targets)
  folderPath = targets(i)
  If folderPath <> "" Then
    If CreateShortcut(folderPath, chrome, args) Then
      created = created + 1
    End If
  End If
Next

If created = 0 Then
  WScript.Echo ""
  WScript.Echo "[ERROR] Could not create shortcut."
  WScript.Quit 1
End If

WScript.Echo ""
WScript.Echo "Done. Before first use:"
WScript.Echo "  Task Manager -> end ALL chrome.exe"
WScript.Echo "Then open ONLY: " & LNK_NAME
WScript.Echo "Expected: ONE tab with CRM (not github/WB tabs)."
WScript.Echo ""
WScript.Echo "Starting CRM..."

cmd = Chr(34) & chrome & Chr(34) & " " & args
shell.Run cmd, 1, False

Function FindChrome()
  Dim candidates, c
  candidates = Array( _
    shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Google\Chrome\Application\chrome.exe", _
    shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Google\Chrome\Application\chrome.exe", _
    shell.ExpandEnvironmentStrings("%LocalAppData%") & "\Google\Chrome\Application\chrome.exe" _
  )
  For Each c In candidates
    If fso.FileExists(c) Then
      FindChrome = c
      Exit Function
    End If
  Next
  FindChrome = ""
End Function

Function CreateShortcut(folderPath, chromePath, chromeArgs)
  Dim fullPath, link
  On Error Resume Next
  fullPath = folderPath & "\" & LNK_NAME
  Set link = shell.CreateShortcut(fullPath)
  link.TargetPath = chromePath
  link.Arguments = chromeArgs
  link.WorkingDirectory = shell.ExpandEnvironmentStrings("%USERPROFILE%")
  link.Description = "Fulfillment CRM autoprint (separate Chrome profile)"
  link.Save
  If Err.Number <> 0 Then
    WScript.Echo "[WARN] " & fullPath & " - " & Err.Description
    Err.Clear
    CreateShortcut = False
    Exit Function
  End If
  On Error GoTo 0
  If fso.FileExists(fullPath) Then
    WScript.Echo "[OK] " & fullPath
    CreateShortcut = True
  Else
    CreateShortcut = False
  End If
End Function
