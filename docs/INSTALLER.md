# Offline setup and complete uninstall

The distribution is a single `dist/RepairShopManager-Offline-Setup-1.4.3.exe`. It uses the standard Inno Setup wizard: Welcome, information/README, destination folder, Start Menu folder, Desktop shortcut, Ready to Install, progress and Finish (with optional launch).

The app and Python/Qt runtime are embedded; the destination PC needs no internet, Python, source tree or compiler. Installation is per Windows user. Upgrading in place keeps existing records. Uninstalling is different: after a permanent-deletion confirmation, it removes program files, shortcuts, the Apps/Control Panel entry, credentials and the complete default local data folder (`%LOCALAPPDATA%/RepairShopManager`), including accounts and internal backups. A subsequent install starts at shop/account creation.

Exports or backup copies deliberately saved elsewhere, USB copies of the setup and the developer source repository are not installed application files and are not searched for or erased. Unknown files in a user-selected install folder are preserved; the installer removes only its recorded files there. Directory junctions/symlinks inside the shop-data tree stop removal rather than risk traversing an unrelated location. The app must be closed before uninstall.

## Developer build

The compiler is a portable build tool under `build/installer-tools/inno-6.4.3`, not an end-user dependency. Obtain the signed Inno Setup 6.4.3 installer from the [official release](https://github.com/jrsoftware/issrc/releases/tag/is-6_4_3), check its Authenticode signature, then unpack using its documented `/PORTABLE=1 /CURRENTUSER /VERYSILENT /NORESTART /DIR="..."` options. The included license permits commercial distribution. The compiler folder and its download remain ignored build artifacts. See the [portable setup documentation](https://jrsoftware.org/ishelp/topic_technotes.htm).

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath build\offline-payload RepairShopManager.spec
& scripts\build_installer.ps1
```

The builder uses the explicit fresh payload and never falls back to an installed application. `scripts/installer/RepairShopManager.iss` owns installer behavior; `scripts/installer/README.txt` is shown before installation and installed alongside the executable. Inno Setup supplies its native logged uninstaller; no PowerShell source script is shipped.

## Silent deployment and verification

Setup supports standard `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="..."` parameters. Its uninstaller requires **both** the standard silent flags and `/REMOVEALLDATA=1`; omission cancels removal without deleting the data. This switch deliberately acknowledges the destructive full reset and is not included in the normal registry uninstall command.

The old bootstrapper's legacy uninstall registration and obsolete PowerShell uninstaller are removed during migration to the native installer. Inno tracks its own `RepairShopManager_is1` uninstall registration. Program files are removed using the install log, never a recursive wildcard over the chosen installation directory.

## Verified release artifact

1.4.3 final setup: 73,511,313 bytes; SHA256 `8a420139fc09e152c34e24743d9d8753b2b4e9bb2b20c276d0fb4fe3fb21cb69`.

On this Windows host, installation, custom destination, update preservation, uninstall refusal without the silent data flag, interactive cancel, full data/credential removal and reinstall to a blank first-run setup were verified. The final cleanup also removed the pre-existing empty default install folder. No application, shop-data directory, Desktop/Start Menu shortcuts or uninstall registry entry remains from testing. Only the latest setup is left in `dist`. Installation on an independent second PC has not been tested here.
