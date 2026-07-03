# Docker Rsync Scheduler & Backup Service

Uniwersalne, lekkie i w pełni konteneryzowane narzędzie do automatycznego tworzenia kopii zapasowych (1:1, przyrostowych oraz przenoszenia danych) przy użyciu narzędzia `rsync`. Działa wszędzie tam, gdzie dostępny jest Docker oraz Docker Compose.

## 🚀 Główne funkcje

* **Wieloplatformowość:** Działa na systemach Linux, Windows, macOS oraz na serwerach NAS (Synology, QNAP).
* **Trzy tryby pracy:** * `mirror` – Kopia 1:1 (usuwa z celu pliki skasowane w źródle).
  * `incremental` – Kopia przyrostowa (dodaje nowe i zmienione pliki, nie kasuje nic z celu).
  * `move` – Przenoszenie danych (usuwa pliki ze źródła po udanym transferze).
* **Inteligentny Scheduler:** Dynamiczne przeładowywanie zadań po edycji pliku konfiguracji JSON, bez restartu kontenera.
* **Kolejkowanie zadań:** Możliwość wymuszenia wykonywania zadań sekwencyjnie (jedno po drugim), aby nie przeciążać dysków.
* **Healthcheck ścieżek:** Przed uruchomieniem kopiowania aplikacja weryfikuje obecność podmontowanych zasobów.
* **Graceful Shutdown:** Bezpieczne przerywanie procesów i informowanie o zamknięciu kontenera (obsługa sygnałów `SIGTERM`).
* **Powiadomienia Discord:** Raporty o starcie, sukcesach (wraz ze statystykami wagowymi) lub błędach prosto na Twój kanał.

---

## 📂 Struktura katalogów

```text
.
├── config/
│   └── config.json       # Główny plik konfiguracyjny aplikacji
├── logs/
│   ├── app.log           # Ogólne logi systemowe (start, zmiany konfiguracji)
│   └── task_*.log        # Logi per konkretne zadanie rsync
├── src/
│   └── main.py           # Serce aplikacji (Python)
├── Dockerfile
└── docker-compose.yml

```

---

## ⚙️ Konfiguracja `config/config.json`

Aplikacja sterowana jest jednym plikiem JSON. Pamiętaj, aby ścieżki `source` i `dest` wskazywały na foldery **wewnątrz kontenera** (zdefiniowane po prawej stronie w `docker-compose.yml`).

```json
{
  "general": {
    "discord_webhook_url": "[https://discord.com/api/webhooks/](https://discord.com/api/webhooks/)...",
    "notification_level": "all",
    "config_check_interval_seconds": 10,
    "default_scheduler": "0 2 * * *",
    "max_concurrent_tasks": 1
  },
  "tasks": [
    {
      "name": "Backup Dokumentow",
      "enabled": true,
      "type": "incremental",
      "source": "/source/documents",
      "dest": "/dest/backup_documents",
      "scheduler": "*/5 * * * *",
      "exclude": [
        "@Recycle",
        "@eaDir",
        ".DS_Store",
        "/2026/banan.docx"
      ],
      "extra_rsync_flags": "--bwlimit=5000"
    }
  ]
}

```

### 💡 Ważna uwaga dotycząca ukośników na końcu ścieżek (Trailing Slash)
Aplikacja została zaprojektowana tak, aby jej działanie było zawsze przewidywalne. Niezależnie od tego, czy w pliku `config.json` dodasz ukośnik na końcu ścieżki źródłowej (np. `/source/documents/`), czy go pominiesz (`/source/documents`), skrypt **zawsze automatycznie wymusi ukośnik na końcu**.

Oznacza to, że `rsync` zawsze skopiuje **samą zawartość** wskazanego folderu bezpośrednio do miejsca docelowego, zamiast tworzyć tam podfolder o nazwie źródła.

* **Przykład:** Jeśli źródło zawiera plik `foto.jpg`, a cel to `/dest/backup`, plik po skopiowaniu zawsze trafi bezpośrednio do `/dest/backup/foto.jpg`.

### Opis parametrów sekcji `general`:

* `notification_level`:
* `"all"` – Powiadomienia o starcie, sukcesie ze statystykami oraz błędach.
* `"errors_only"` – Informacja na Discordzie ląduje tylko w przypadku awarii.
* `"none"` – Wyłączenie powiadomień.


* `max_concurrent_tasks`: Określa ile zadań może wykonywać się jednocześnie. Ustawienie `1` gwarantuje wykonywanie zadań jedno po drugim.

### Precyzyjne wykluczenia (`exclude`):

* Snaspshoty i foldery systemowe: `"@Recycle"`, `".DS_Store"`.
* Konkretny plik w konkretnym miejscu: `"/2026/banan.docx"` (ukośnik na początku oznacza relatywny root folderu źródłowego).

### Przydatne flagi zaawansowane (`extra_rsync_flags`):

Aplikacja domyślnie uruchamia rsync z parametrami `-avh --stats`. Możesz rozbudować zachowanie skryptu, dopisując w stringu:

* `--bwlimit=5000` – Ogranicza prędkość transferu do ok. 5MB/s (wartość podawana w KB/s). Przydatne, aby nie zapchać sieci lub dysku.
* `--ignore-errors` – Kontynuuje kopiowanie reszty danych, nawet jeśli rsync napotka zablokowany lub uszkodzony plik.
* `--checksum` – Zmusza rsync do porównywania plików na podstawie sum kontrolnych (md5), a nie tylko daty modyfikacji i rozmiaru. Bardzo dokładne, ale obciąża procesor.
* `--update` – Pomija pliki, które w katalogu docelowym (`dest`) są nowsze niż w źródłowym (`source`).
* `-z` – Kompresuje dane w locie podczas przesyłania (przydatne przy wolnych połączeniach sieciowych).

---

## 🐳 Uruchomienie (Docker Compose)

1. Dostosuj plik `docker-compose.yml`, mapując swoje fizyczne foldery (lewa strona) do folderów w kontenerze (prawa strona).
2. Skonfiguruj plik `config/config.json`.
3. Uruchom kontener poleceniem:

```bash
docker compose up -d --build

```

---

## 📊 Logi i diagnostyka

Wszystkie operacje i statystyki rsync (liczba plików, całkowita waga transferu) są wypisywane na konsolę Dockera:

```bash
docker logs -f docker-rsync-scheduler

```

Logi są również trwale zapisywane w katalogu `./logs/`.
