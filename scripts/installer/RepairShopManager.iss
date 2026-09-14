#ifndef AppVersion
  #define AppVersion "1.5.0"
#endif
#ifndef AppPayload
  #error AppPayload must identify the freshly built application EXE.
#endif
#ifndef SetupOutput
  #error SetupOutput is required.
#endif

[Setup]
AppId=RepairShopManager
AppName=RepairShop Manager
AppVersion={#AppVersion}
AppPublisher=RepairShop
DefaultDirName={localappdata}\Programs\RepairShopManager
DefaultGroupName=RepairShop Manager
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
WizardSizePercent=110
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=no
DisableReadyPage=no
DisableFinishedPage=no
InfoBeforeFile=README.txt
OutputDir={#SetupOutput}
OutputBaseFilename=RepairShopManager-Offline-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\RepairShopManager.exe
UninstallDisplayName=RepairShop Manager
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Messages]
ConfirmUninstall=Completely uninstall %1?%n%nThis permanently deletes the application and all saved local shop data: customers, repairs, photos, login accounts, settings and local backups.%n%nA later installation will start with a fresh shop setup. Continue?

[Tasks]
Name: desktopicon; Description: "Create a &Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#AppPayload}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\RepairShop Manager"; Filename: "{app}\RepairShopManager.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall RepairShop Manager"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RepairShop Manager"; Filename: "{app}\RepairShopManager.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\RepairShopManager.exe"; Description: "Open RepairShop Manager"; Flags: nowait postinstall skipifsilent

[InstallDelete]
Type: files; Name: "{app}\Uninstall RepairShop Manager.ps1"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\RepairShopManager"; Flags: deletekey

[UninstallDelete]
; Remove an empty legacy default directory, never unrelated contents.
Type: dirifempty; Name: "{localappdata}\Programs\RepairShopManager"
Type: dirifempty; Name: "{app}"

[Code]
function CredDelete(TargetName: String; CredType, Flags: Cardinal): Boolean;
  external 'CredDeleteW@advapi32.dll stdcall';
function GetLastError(): Cardinal;
  external 'GetLastError@kernel32.dll stdcall';
function GetFileAttributes(Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function ShopDataDirectory: String;
begin
  Result := ExpandConstant('{localappdata}\RepairShopManager');
end;

function SafeTree(const Directory: String): Boolean;
var Entry: TFindRec;
begin
  Result := False;
  if (GetFileAttributes(Directory) and $400) <> 0 then exit;
  Result := True;
  if FindFirst(AddBackslash(Directory) + '*', Entry) then
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        if (Entry.Attributes and $400) <> 0 then begin Result := False; exit; end;
        if (Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          if not SafeTree(AddBackslash(Directory) + Entry.Name) then begin Result := False; exit; end;
      end;
    until not FindNext(Entry);
  finally
    FindClose(Entry);
  end;
end;

function AppRunning: Boolean;
var Locator, Services, Processes: Variant;
begin
  Locator := CreateOleObject('WbemScripting.SWbemLocator');
  Services := Locator.ConnectServer('', 'root\CIMV2');
  Processes := Services.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''RepairShopManager.exe''');
  Result := Processes.Count > 0;
end;

function InitializeUninstall: Boolean;
begin
  Result := False;
  if AppRunning then begin
    if not UninstallSilent then MsgBox('Close RepairShop Manager before uninstalling, then try again.', mbError, MB_OK);
    exit;
  end;
  if DirExists(ShopDataDirectory) and not SafeTree(ShopDataDirectory) then begin
    if not UninstallSilent then MsgBox('The shop data folder contains a linked directory. Uninstall stopped to avoid removing files outside the application folder.', mbError, MB_OK);
    exit;
  end;
  if UninstallSilent then begin
    Result := ExpandConstant('{param:REMOVEALLDATA|0}') = '1';
    exit;
  end;
  // The native ConfirmUninstall dialog carries the permanent-deletion explanation.
  Result := True;
end;

procedure RemoveCredential(const Target: String);
var ErrorCode: Cardinal;
begin
  if not CredDelete(Target, 1, 0) then begin
    ErrorCode := GetLastError;
    if ErrorCode <> 1168 then RaiseException('Unable to remove saved messaging credential. Error ' + IntToStr(ErrorCode));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var DataPath: String;
begin
  if CurUninstallStep = usUninstall then begin
    DataPath := ShopDataDirectory;
    if CompareText(ExtractFileDir(DataPath), ExpandConstant('{localappdata}')) <> 0 then
      RaiseException('Unexpected shop data path. Uninstall stopped.');
    if DirExists(DataPath) then begin
      if not SafeTree(DataPath) then RaiseException('Linked directory found. Uninstall stopped.');
      if not DelTree(DataPath, True, True, True) then
        RaiseException('Unable to remove all shop data. Close programs using this folder and run uninstall again: ' + DataPath);
    end;
    RemoveCredential('RepairShop Manager');
    RemoveCredential('whatsapp_token@RepairShop Manager');
    RemoveCredential('smtp_credential@RepairShop Manager');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Chosen: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Chosen := RemoveBackslashUnlessRoot(ExpandFileName(WizardDirValue));
    if (CompareText(Chosen, ExpandConstant('{localappdata}')) = 0) or
       (CompareText(Chosen, ShopDataDirectory) = 0) or
       (CompareText(Chosen, ExpandConstant('{win}')) = 0) or
       (Length(Chosen) <= 3) then begin
      MsgBox('Choose a dedicated application folder, such as ' + ExpandConstant('{localappdata}\Programs\RepairShopManager') + '.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
