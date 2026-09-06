Option Explicit

Const CRM_URL = "http://5.129.243.246:8080/?print_mode=kiosk"
Const LNK_NAME = "Fulfillment CRM (autoprint).lnk"

Dim fso, shell, chrome, args, targets, i, folderPath, fullPath, link, created, cmd

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

WScript.Echo "Chrome: " & chrome
WScript.Echo "CRM:    " & CRM_URL
WScript.Echo ""

args = "--kiosk-printing " & CRM_URL
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
  WScript.Echo "Check Desktop / Start menu / folder with this script."
  WScript.Quit 1
End If

WScript.Echo ""
WScript.Echo "Done. Open CRM only via shortcut:"
WScript.Echo "  " & LNK_NAME
WScript.Echo "1. Set Xprinter as default printer (58x40 mm)"
WScript.Echo "2. In FBS assembly header: Print: Chrome (autoprint)"
WScript.Echo ""
WScript.Echo "Starting CRM..."

cmd = Chr(34) & chrome & Chr(34) & " --kiosk-printing " & CRM_URL
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
  link.Description = "Fulfillment CRM autoprint"
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
    WScript.Echo "[WARN] " & fullPath & " - not found after save"
    CreateShortcut = False
  End If
End Function
