# Matrix Finance TUI

Matrix Finance to kompleksowe narzędzie do prowadzenia **budżetu domowego połączonego z oszczędzaniem kopertowym**, działające w terminalu (Python + Textual). Obsługa w całości z klawiatury, architektura local-first — dane zostają na Twoim komputerze i mogą być szyfrowane.

## Najważniejsze funkcje

### Budżet kopertowy
* **Koperty** — każda kategoria wydatków ma miesięczny budżet. Pulpit i zakładka *Koperty* pokazują: dostępne, wydane, pozostało i wykorzystanie (pasek).
* **Koperty elastyczne (↻)** — niewydane środki przechodzą na kolejny miesiąc i zwiększają budżet (np. budżet 500 zł, wydano 420 zł → w kolejnym miesiącu dostępne 580 zł).
* **Do rozdysponowania** — ile przychodów nie zostało jeszcze przydzielonych do kopert.
* **Korekty kopert** (`K`) — ręczne ustawienie kwoty „zostało”, dołożenie/odjęcie środków albo cofnięcie korekt miesiąca; **przesuwanie środków między kopertami** (`M`), np. z „Rozrywki” do „Jedzenia”.

### Konta i produkty finansowe
| Grupa | Rodzaje kont |
|---|---|
| Codzienne | konto osobiste, gotówka, fintech / portfel (Revolut, PayPal…) |
| Oszczędności | konto oszczędnościowe (z oprocentowaniem), **lokata** |
| Inwestycje | **obligacje skarbowe**, konto maklerskie, **robodoradca** |
| Emerytalne | **IKE, IKZE, PPK** (z limitem rocznych wpłat) |

* **Przelewy między kontami** (`Ctrl+T` z każdego miejsca) — nie są ani wydatkiem, ani dochodem, więc nie zaburzają budżetu.
* **Lokaty i obligacje** — zakładane z dowolnego konta (np. z Revoluta), z oprocentowaniem, okresem i podatkiem Belki (19%). Postęp okresu i prognoza zysku netto; po terminie odsetki dopisują się automatycznie, a środki wracają na konto źródłowe albo lokata odnawia się z kapitalizacją. Można ją też zerwać (zwrot kapitału bez odsetek).
* **Inwestycje** — wpłaty/wypłaty, ręczna aktualizacja wyceny (zysk/strata), wpłaty zewnętrzne (np. pracodawca do PPK), dopisywanie odsetek.
* **Korekta salda** (`K`) dla każdego konta — także oszczędnościowego, lokaty i inwestycji: wpisujesz rzeczywiste saldo z banku, a różnica zapisuje się w historii jako „Korekta salda (+/−)” (nie jest wydatkiem ani dochodem).
* **Majątek netto** z podziałem na grupy, środki dostępne i ulokowane.

### Oszczędzanie automatyczne
* **Auto-oszczędzanie procentowe** — X% każdego wpływu na wybrane konto trafia na konto oszczędnościowe lub do celu.
* **Zaokrąglenia** — każdy wydatek zaokrąglany w górę do pełnych N zł, różnica odkładana (jak w Revolut).
* **Cele oszczędnościowe** z terminem — aplikacja liczy, ile odkładać miesięcznie, żeby zdążyć. Stan celu można skorygować (`K`) bez ruszania sald kont.
* **Zlecenia cykliczne**: wydatki, dochody, wpłaty na cel i przelewy (np. co miesiąc na IKE) — dzienne, tygodniowe, miesięczne, kwartalne, roczne. Zaległe terminy księgowane są wszystkie naraz.

### Analiza i raporty
* **Pulpit**: kafelki (majątek, do wydania, bilans, stopa oszczędności z wykresem 6 miesięcy), koperty, kalendarz, nadchodzące płatności, **Doradca** (wskazówki: poduszka finansowa, przekroczone koperty, kończące się lokaty, plan celów), cele i struktura majątku.
* **Kalendarz** — miesiąc z intensywnością wydatków, kwotami dni, zaplanowanymi zleceniami (•) i końcami lokat (◆); szczegóły wybranego dnia, nowa transakcja w danym dniu.
* **Raporty** — bilans, porównanie z poprzednim miesiącem, trend 6 miesięcy, TOP koperty i sklepy.
* **Drukowanie raportu miesięcznego** — raport HTML otwiera się w przeglądarce z oknem drukowania (można też zapisać jako PDF).

### Synchronizacja z telefonem (OneDrive)
Aplikacja na Androida — osobny projekt **Matrix Finance Mobile**. Synchronizacja odbywa się przez plik w folderze OneDrive (bez własnego serwera):

* komputer zapisuje zaszyfrowaną migawkę danych `MatrixFinance.mfsync` (po zalogowaniu, co 2 minuty, gdy coś się zmieniło, i przy wyjściu; ręcznie `Ctrl+Y`),
* telefon wczytuje migawkę i odkłada swoje zmiany (wydatki, dochody, przelewy, wpłaty na cele, korekty sald i kopert) w pliku `*.mfops` w tym samym folderze,
* komputer dopisuje zmiany z telefonu — każdą tylko raz, nawet jeśli plik zapisano kilka razy — i zapisuje nową migawkę; telefon po jej wczytaniu ma znowu komplet danych,
* zmiana, której nie da się wykonać (np. cel usunięty na komputerze), jest odrzucana i telefon o tym informuje,
* oba pliki są szyfrowane hasłem synchronizacji (AES/Fernet, PBKDF2).

Konfiguracja: *Ustawienia (9) → Synchronizacja z telefonem → Ustaw synchronizację* (folder OneDrive wykrywany automatycznie, hasło).

### Dane i bezpieczeństwo
* **Eksport**: pełny JSON, pełny eksport **zaszyfrowany** hasłem (.mfx), transakcje CSV (Excel), kopia całej bazy (.matrix).
* **Import**: pełne dane z JSON/.mfx (zastępuje obecne), transakcje z CSV (dopisuje), kopia .matrix jako nowy użytkownik (ekran logowania).
* **Szyfrowanie danych na dysku** (Ustawienia → Bezpieczeństwo): baza przechowywana tylko jako plik zaszyfrowany (AES/Fernet, klucz z hasła PBKDF2); w trakcie pracy dane są wyłącznie w pamięci RAM i zapisywane co 2 minuty oraz przy wylogowaniu/wyjściu.
* **Logowanie z kluczem YubiKey (eksperymentalne)** — drugi składnik po haśle (HMAC-SHA1 challenge-response przez `ykman`), z kodem awaryjnym.
* Hasła: PBKDF2-SHA256.

### Wygląd
* **Motywy kolorów**: Matrix (zielony), Bursztyn (pomarańczowy), Cyber (cyjan), Fiolet, Karmazyn, Monochromatyczny — zmiana natychmiastowa w Ustawieniach.
* **Animacja „cyfrowego deszczu”** na ekranie powitalnym i logowania (można wyłączyć).
* Jeden, czytelny styl pasków postępu w całej aplikacji: `━━━━━━────  62%` (zielony → żółty → czerwony dla budżetu).
* Interfejs dopasowuje się do okna (od ok. 60×20 do bardzo szerokich ekranów): chowane menu, 1/2/3 kolumny na pulpicie, tabele same dobierają kolumny, stopka skraca etykiety.

## Instalacja i uruchomienie

### Windows — instalator (zalecane)

Pobierz **`MatrixFinance-Setup-<wersja>.exe`** z [najnowszego wydania (Releases)](https://github.com/ArturKnopek/Matrix-Finance-TUI/releases/latest) i uruchom go:

* instaluje program **razem z własnym Pythonem** — nie trzeba niczego doinstalowywać ani mieć uprawnień administratora,
* tworzy **skrót na pulpicie** i w menu Start (program, „Sprawdź instalację”, folder z danymi, deinstalator),
* dodaje wpis w *Ustawienia → Aplikacje* (odinstalowanie), aktualizacja = uruchomienie nowszego instalatora,
* dane (`%USERPROFILE%\.matrix_finance`) nie są ruszane przy aktualizacji; deinstalator pyta o nie osobno (domyślnie zostają),
* program otwiera się w **Windows Terminal** (jeśli jest — Windows 11 ma go domyślnie), w przeciwnym razie w zwykłej konsoli.

Instalator nie ma płatnego podpisu cyfrowego, więc Windows może pokazać „System Windows ochronił ten komputer” → *Więcej informacji* → *Uruchom mimo to*. Instalacja cicha: `MatrixFinance-Setup-<wersja>.exe /S`.

Budowanie instalatora (Linux lub Windows, potrzebny NSIS 3): `python installer/windows/build_installer.py` → `dist/`. Nowe wydanie z instalatorem: wypchnięcie tagu `vX.Y.Z` (GitHub Actions zbuduje, przetestuje na Windows i opublikuje). Python dla Windows pobierany jest z oficjalnego pakietu NuGet PSF i weryfikowany sumą SHA-256.

### Ze źródeł (Linux, macOS, Windows)

```bash
git clone https://github.com/ArturKnopek/Matrix-Finance-TUI.git
cd Matrix-Finance-TUI
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Test instalacji (na danych tymczasowych): `python main.py --selftest`.

Opcjonalnie (YubiKey): `pip install yubikey-manager` i przygotowanie klucza: `ykman otp chalresp --generate --touch 2`.

Dane: `~/.matrix_finance/` — zmienna `MATRIX_FINANCE_HOME` zmienia lokalizację (`auth.db`, `data/<id>.db` lub zaszyfrowane `data/<id>.db.enc`). Logi błędów: `~/.matrix_finance/matrix.log`. Eksporty i raporty: `~/Documents/Matrix_Finance/`.

## Skróty klawiszowe

| Klawisz | Działanie |
|---|---|
| `1` – `9` | zakładki: Pulpit, Transakcje, Koperty, Konta, Cele, Automaty, Kalendarz, Raporty, Ustawienia |
| `[` / `]` | poprzedni / następny miesiąc roboczy (z każdego miejsca) |
| `Ctrl+F` | szukaj wszędzie (transakcje ze wszystkich miesięcy, konta, koperty, cele, zlecenia) |
| `Ctrl+N` | nowy element w zakładce (na pulpicie: transakcja) |
| `Ctrl+T` | przelew między kontami |
| `Ctrl+E` / `Ctrl+D` | edytuj / usuń zaznaczone (w Kontach `Ctrl+D` zamyka konto lub zrywa lokatę) |
| `+` / `-` | wpłata / wypłata (Konta, Cele); w Kopertach `+` = wydatek z koperty |
| `W` / `A` / `O` | Konta: wycena lub odsetki / reguła auto-oszczędzania / wpłata zewnętrzna |
| `K` | korekta: saldo konta (Konta) · stan koperty (Koperty) · stan celu (Cele) |
| `M` | Koperty: przesuń środki do innej koperty |
| `Ctrl+P` | pauza / wznowienie zlecenia lub reguły |
| `Ctrl+R` | odśwież, zaksięguj zaległe zlecenia, rozlicz lokaty |
| `Ctrl+Y` | synchronizuj z telefonem (OneDrive) |
| `P` / `G` / `C` | Raporty: drukuj / TXT / CSV |
| `Enter` | otwórz / edytuj; w formularzu: następne pole (w ostatnim — zapis) |
| `Ctrl+S` | zapisz formularz |
| `ESC` | zamknij okno · wróć do menu · wyczyść filtry |
| `F1` | pomoc · `F2` / `Ctrl+B` pokaż/ukryj menu |
| `Ctrl+L` / `Ctrl+Q` | wyloguj / wyjście |

**Daty** w formularzach: puste = dziś, `wczoraj`, `12`, `12.05`, `12.05.2026`, `2026-05-12`.
**Kwoty**: `12,50`, `1 200`, działania `12.5+3*2`.

## Struktura projektu

```
src/finance/   silnik: storage (baza, schemat), ledger (transakcje, przelewy), envelopes (koperty),
               accounts (konta, lokaty, inwestycje), goals (cele), recurring (zlecenia),
               autosave (auto-oszczędzanie), analytics (doradca, kalendarz, wyszukiwanie),
               data_io (eksport/import/druk), sync (synchronizacja z telefonem przez OneDrive)
src/core/      auth (hasła), vault (szyfrowanie na dysku), yubikey (2FA)
src/ui/        theme (motywy), widgets (paski, kalendarz, animacja), smart_table, dialogs, forms
src/views/     zakładki aplikacji
src/screens/   powitanie, logowanie, ekran główny, okna systemowe
src/selftest.py  test instalacji (python main.py --selftest)
installer/windows/  instalator Windows (NSIS): skrypt budujący, uruchamiacz, ikona, instrukcja
```

## Testy

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Testy obejmują silnik (salda, przelewy, lokaty z podatkiem, koperty z przenoszeniem, auto-oszczędzanie, eksport/import), bezpieczeństwo (szyfrowanie, YubiKey z atrapą klucza) oraz interfejs uruchamiany bez terminala w kilku rozmiarach okna.

## Migracja ze starej bazy `budget.db`

```bash
python -m src.migrate --old-db sciezka/do/budget.db --user TwojLogin
```

## Licencja

Projekt udostępniany na licencji MIT.
