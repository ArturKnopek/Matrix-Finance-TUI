## Matrix Finance — instalator dla Windows

Pobierz **`MatrixFinance-Setup-<wersja>.exe`** (poniżej, w sekcji *Assets*) i uruchom.

* zawiera wszystko, czego program potrzebuje (także **Python 3.13**) — nie trzeba niczego doinstalowywać,
* nie wymaga uprawnień administratora (instalacja do `%LOCALAPPDATA%\Programs\MatrixFinance`),
* tworzy **skrót na pulpicie** i w menu Start (program, „Sprawdź instalację”, folder z danymi, instrukcja, deinstalator),
* program otwiera się w Windows Terminal (jeśli jest), w przeciwnym razie w zwykłym oknie konsoli,
* aktualizacja = uruchomienie nowszego instalatora; dane (`%USERPROFILE%\.matrix_finance`) zostają,
* deinstalacja: *Ustawienia → Aplikacje → Matrix Finance* (o usunięciu danych pyta osobno, domyślnie zostają).

**Ostrzeżenie „System Windows ochronił ten komputer”** — instalator nie ma płatnego podpisu cyfrowego: kliknij *Więcej informacji* → *Uruchom mimo to*. Sumę kontrolną SHA-256 znajdziesz w pliku `.sha256`.

Wymagania: Windows 10 lub 11, 64-bit. Instalacja cicha: `MatrixFinance-Setup-<wersja>.exe /S`.

**Nowości:** kredyty i zakupy na raty (Konta → Ctrl+N → Zobowiązania; raty księgują się same), własny rodzaj konta, tryb stanów początkowych bez historii (Ustawienia), poprawiona zmiana motywu kolorów; synchronizacja z aplikacją na Androida przez OneDrive (Ustawienia → Synchronizacja z telefonem, `Ctrl+Y`).
Aplikacja na telefon: repozytorium Matrix-Finance-Mobile.

Inne systemy (Linux, macOS) i uruchamianie ze źródeł — zobacz README.
