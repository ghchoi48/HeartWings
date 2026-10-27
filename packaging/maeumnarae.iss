; python scripts/build_desktop.py supplies these values from program_info.py.
#if Ver < EncodeVer(6, 3, 0)
  #error Inno Setup 6.3 or newer is required.
#endif
#ifndef AppName
  #error Run python scripts/build_desktop.py to supply AppName and AppVersion.
#endif
#ifndef AppVersion
  #error AppVersion is required.
#endif
#ifndef SourceRoot
  #define SourceRoot SourcePath + ".."
#endif

[Setup]
AppId={{C23BF272-20E9-4CB3-99D8-F15549D17098}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=최규호
AppPublisherURL=https://github.com/ghchoi48/HeartWings
DefaultDirName={localappdata}\Programs\maeumnarae
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir={#SourceRoot}\dist\installer
OutputBaseFilename=maeumnarae-{#AppVersion}-windows-x64-setup
SetupIconFile={#SourceRoot}\resources\icons\icon.ico
UninstallDisplayIcon={app}\maeumnarae.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
UsePreviousTasks=no

[Languages]
#if Ver >= EncodeVer(6, 5, 0)
Name: "korean"; MessagesFile: "languages\Korean.isl"
#else
Name: "korean"; MessagesFile: "languages\Korean-6.3.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "바로가기:"

[Files]
Source: "{#SourceRoot}\dist\maeumnarae\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\maeumnarae.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\maeumnarae.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\maeumnarae.exe"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  BootstrapperURL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
var
  DeleteUserData: Boolean;

function DeleteUserFile(Filename: String): Boolean;
  external 'DeleteFileW@kernel32.dll stdcall';

function HasRuntimeAt(RootKey: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, WebViewKey, 'pv', Version);
  if Result then
    Result := (Version <> '') and (Version <> '0.0.0.0');
end;

function HasWebView2: Boolean;
begin
  Result := HasRuntimeAt(HKLM32) or HasRuntimeAt(HKCU64) or HasRuntimeAt(HKCU32);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2 then exit;
  try
    WizardForm.StatusLabel.Caption := 'Microsoft WebView2 다운로드 및 설치 중...';
    DownloadTemporaryFile(BootstrapperURL, 'MicrosoftEdgeWebview2Setup.exe', '', nil);
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'),
        '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'WebView2 설치 프로그램 실행 실패: ' + SysErrorMessage(ExitCode)
    else if (ExitCode <> 0) and (ExitCode <> 3010) then
      Result := 'WebView2 설치 실패. 오류 코드: ' + IntToStr(ExitCode)
    else if not HasWebView2 then
      Result := 'WebView2 설치를 확인할 수 없습니다. 인터넷 연결과 시스템 정책을 확인하세요.'
    else if ExitCode = 3010 then begin
      NeedsRestart := True;
      Result := 'WebView2 설치를 마치려면 Windows를 다시 시작한 후 설치 프로그램을 실행하세요.';
    end;
  except
    Result := 'WebView2 다운로드 또는 설치 실패: ' + GetExceptionMessage;
  end;
end;

function DataFile(Index: Integer): String;
begin
  case Index of
    0: Result := 'maeumnarae.db';
    1: Result := 'maeumnarae.db-wal';
    2: Result := 'maeumnarae.db-shm';
    3: Result := 'maeumnarae.db-journal';
    4: Result := 'display-settings.json';
  end;
  Result := ExpandConstant('{localappdata}\maeumnarae\data\') + Result;
end;

function InitializeUninstall: Boolean;
var
  Form: TSetupForm;
  Check: TNewCheckBox;
  Info: TNewStaticText;
  ContinueButton, CancelButton: TNewButton;
  Paths: String;
  I: Integer;
begin
  Result := True;
  DeleteUserData := False;
  if UninstallSilent then exit;
  Paths := '';
  for I := 0 to 4 do Paths := Paths + DataFile(I) + #13#10;
#if Ver >= EncodeVer(6, 6, 0)
  Form := CreateCustomForm(ScaleX(620), ScaleY(290), False, False);
#else
  Form := CreateCustomForm;
#endif
  try
    Form.Caption := '{#AppName} 제거';
#if Ver < EncodeVer(6, 6, 0)
    Form.ClientWidth := ScaleX(620);
    Form.ClientHeight := ScaleY(290);
#endif
    Info := TNewStaticText.Create(Form);
    Info.Parent := Form;
    Info.SetBounds(ScaleX(16), ScaleY(16), ScaleX(588), ScaleY(180));
    Info.AutoSize := False;
    Info.WordWrap := True;
    Info.Caption := '앱을 종료한 후 계속하세요. 기본적으로 사용자 데이터는 보존됩니다.' + #13#10 +
      '삭제 옵션을 선택하면 아래 파일만 삭제합니다. 삭제 후 복구할 수 없습니다.' + #13#10#13#10 + Paths;
    Check := TNewCheckBox.Create(Form);
    Check.Parent := Form;
    Check.SetBounds(ScaleX(16), ScaleY(202), ScaleX(588), ScaleY(24));
    Check.Caption := '사용자 DB 및 설정 파일도 삭제';
    Check.Checked := False;
    ContinueButton := TNewButton.Create(Form);
    ContinueButton.Parent := Form;
    ContinueButton.SetBounds(ScaleX(408), ScaleY(246), ScaleX(90), ScaleY(28));
    ContinueButton.Caption := '계속';
    ContinueButton.ModalResult := mrOK;
    ContinueButton.Default := True;
    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.SetBounds(ScaleX(508), ScaleY(246), ScaleX(90), ScaleY(28));
    CancelButton.Caption := '취소';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    Result := Form.ShowModal = mrOK;
    if Result and Check.Checked then begin
      Result := MsgBox('다음 데이터를 영구 삭제하시겠습니까?' + #13#10 + Paths + #13#10 +
        '별도 백업과 외부 DB는 삭제하지 않습니다.', mbConfirmation,
        MB_YESNO or MB_DEFBUTTON2) = IDYES;
      DeleteUserData := Result;
    end;
  finally
    Form.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  I: Integer;
  Filename, Failures: String;
begin
  if (CurUninstallStep <> usPostUninstall) or not DeleteUserData or UninstallSilent then exit;
  Failures := '';
  for I := 0 to 4 do begin
    Filename := DataFile(I);
    if FileExists(Filename) then
      if not DeleteUserFile(Filename) then begin
        Failures := Failures + Filename + ': ' + SysErrorMessage(DLLGetLastError) + #13#10;
        { If the database is locked, preserve its recovery files as well. }
        if I = 0 then break;
      end;
  end;
  if Failures <> '' then
    MsgBox('일부 데이터 삭제에 실패했습니다. 앱을 종료하고 해당 파일을 확인하세요.' + #13#10 +
      Failures + '사용자 데이터가 남아 있을 수 있습니다.', mbError, MB_OK);
end;
