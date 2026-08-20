Name:           klassenbildung
Version:        %{_kb_version}
Release:        1%{?dist}
Summary:        Lokale Anwendung zur Klassenbildung
License:        LicenseRef-Unknown
URL:            https://github.com/user1342554/klassenbildung-go-local
Requires:       glibc >= 2.28
Requires:       libstdc++
Requires:       xdg-utils

%description
Importiert Excel-Daten, prueft Regeln und erstellt lokale Klasseneinteilungen.
Python, Streamlit und OR-Tools sind im Paket enthalten.

%prep

%build

%install
mkdir -p %{buildroot}
cp -a %{_kb_root}/. %{buildroot}/

%files
/usr/bin/klassenbildung
/usr/lib/klassenbildung/
/usr/share/applications/klassenbildung.desktop
/usr/share/icons/hicolor/scalable/apps/klassenbildung.svg
/usr/share/metainfo/de.klassenbildung.local.metainfo.xml

%changelog
* Thu Aug 20 2026 Klassenbildung <noreply@example.invalid> - %{_kb_version}-1
- Erstes natives Linux-Paket
