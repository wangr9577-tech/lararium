Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDir
PyExe = ScriptDir & "\venv\Scripts\python.exe"
AppDir = ScriptDir & "\backend"
LogFile = ScriptDir & "\backend\server.log"
WshShell.Run "cmd /c """"" & PyExe & """ -u -m uvicorn app.main:app --app-dir """ & AppDir & """ --host 127.0.0.1 --port 18080 > """ & LogFile & """ 2>&1""", 0, False
