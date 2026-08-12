Machbarkeitseinschätzung: Generierung von QR-Codes aus URLs
===========================================================

**Kurzantwort:** Ja — die Generierung von QR-Codes aus URLs ist wissenschaftlich und
technisch vollständig gelöst, extrem günstig und in wenigen Stunden umsetzbar. Ein
funktionierender Prototyp ist in unter einer Stunde fertig; selbst die Massengenerierung
für den **gesamten Datensatz dieses Repositories (1.766.025.618 Domains)** ist mit
~500 Cloud-vCPUs in gut 4 Stunden und für unter 100 USD Rechenkosten machbar.
Auf einem einzelnen 4-Kern-Rechner dauert der Gesamtdatensatz ~3 Wochen; 1 Million
Codes dauern dort nur ~18 Minuten.

Alle Zahlen in diesem Dokument sind empirisch gemessen (Benchmark-Skript und
Rohdaten liegen in diesem Verzeichnis bei) bzw. mit Quellenangabe recherchiert
(Stand: August 2026).

---

## 1. Fragestellung

Bewertet wird die Machbarkeit der Erzeugung von QR-Codes aus URLs hinsichtlich:

1. **Wissenschaftlich-technischer Machbarkeit** — ist das Problem gelöst, gibt es Risiken?
2. **Rechenressourcen** — CPU-Zeit, Speicher, Skalierung
3. **Kosten** — Software, Rechenzeit, Speicherung
4. **Zeitaufwand** — „ist so etwas in wenigen Stunden möglich?“

Bezugsrahmen ist dieses Repository: der Domains-Project-Datensatz mit
**1.766.025.618 Domains** (siehe [STATS.md](../STATS.md)), aus denen sich URLs der Form
`https://<domain>` ableiten lassen.

## 2. Wissenschaftliche Einordnung: ein gelöstes Problem

Die QR-Code-Erzeugung ist **kein Forschungsproblem, sondern eine standardisierte
Ingenieursaufgabe**. Der QR-Code ist seit 1994 im Einsatz und international genormt —
aktuell als **ISO/IEC 18004:2024** (4. Ausgabe, August 2024). Der Algorithmus ist
deterministisch: Eingabetext → Segmentierung (Byte-Modus für URLs) →
Reed-Solomon-Fehlerkorrektur → Matrixplatzierung → Maskierung. Es gibt keine offenen
wissenschaftlichen Fragen, keine Modellunsicherheit und keine Trainingsdaten; dieselbe
URL ergibt bei gleicher Bibliothek und gleichen Parametern immer denselben Code (die
Norm lässt Implementierungen etwas Spielraum, z. B. bei der Maskenwahl). Ausgereifte Open-Source-Implementierungen existieren
für praktisch jede Sprache (Python: `segno`, `qrcode`; C: `libqrencode`; JavaScript,
Go, Rust, Java u. v. m.), alle kostenlos.

**Passen URLs überhaupt in einen QR-Code?** Die Byte-Modus-Kapazität nach
ISO/IEC 18004 (verifiziert durch Kreuzvalidierung zweier unabhängiger
Implementierungen, `segno` 1.6.6 und `qrcode` 8.2 — alle geprüften Werte identisch,
reproduzierbar via [`qr_capacity_check.py`](qr_capacity_check.py)):

| Version | Module  | ECC L | ECC M | ECC Q | ECC H |
|--------:|:-------:|------:|------:|------:|------:|
| 1       | 21×21   | 17    | 14    | 11    | 7     |
| 2       | 25×25   | 32    | 26    | 20    | 14    |
| 3       | 29×29   | 53    | 42    | 32    | 24    |
| 4       | 33×33   | 78    | 62    | 46    | 34    |
| 5       | 37×37   | 106   | 84    | 60    | 44    |
| 40      | 177×177 | 2 953 | 2 331 | 1 663 | 1 273 |

Die URLs dieses Datensatzes (gemessen an einer Zufallsstichprobe von 200 000 aus
6 Mio. realen Domains, Präfix `https://`) sind im Mittel **34,7 Zeichen** lang
(Median 36, 95-Perzentil 46; Maximum der Stichprobe 99, des vollen Shards 130). Damit
genügt fast immer **Version 2–4** bei mittlerer Fehlerkorrektur (ECC M) — kleine,
gut scannbare Codes. Gemessene Versionsverteilung (n = 5 000): v1 0,2 %, v2 25,9 %,
**v3 41,1 %**, v4 32,7 %, v5–v6 < 0,1 %. Die Verteilung passt zur gemessenen
Längenverteilung (Median 36 Zeichen → Version 3 mit Kapazität 42). Selbst die längste
URL des vollen Shards (130 Zeichen) passt bequem in Version 8 bei ECC M
(Kapazität 152 Bytes, siehe [`qr_capacity_check.py`](qr_capacity_check.py));
die theoretische Obergrenze liegt bei 2 953 Bytes (Version 40, ECC L).

## 3. Empirische Messung (Benchmark)

Methodik: Benchmark in dieser Repository-Umgebung (Python 3.11.15, 4 vCPUs, 15 GiB
RAM), Eingabe: Zufallsstichprobe aus **6.007.258 realen Domains** des Datensatzes
(Shard `data/austria`), als `https://`-URLs. Skript: [`qr_benchmark.py`](qr_benchmark.py),
Rohdaten: [`qr_benchmark_report.json`](qr_benchmark_report.json). Je Variante wurde
die Erzeugung von 2 000 Codes gemessen (ausgewiesen ist der Mittelwert je Code), dazu
ein Durchsatztest mit 40 000 Codes auf allen 4 Kernen.

| Variante                        | Zeit/Code | Codes/s (1 Kern) | ø Dateigröße |
|---------------------------------|----------:|-----------------:|-------------:|
| `segno` nur Matrix (kein Bild)  | 3,24 ms   | 308              | —            |
| `segno` → PNG (scale 4)         | 4,06 ms   | 246              | 312 B        |
| `segno` → SVG                   | 4,27 ms   | 234              | 1 604 B      |
| `qrcode` + Pillow → PNG         | 5,96 ms   | 168              | 706 B        |
| `segno` → PNG, **4 Prozesse**   | —         | **915 gesamt**   | 312 B        |

Kernbefund: **Ein einzelner QR-Code kostet ~4 Millisekunden CPU-Zeit und ~300 Bytes
Speicher.** Die Parallelisierung skaliert nahezu linear (93 % Effizienz auf 4 Kernen),
da die Aufgabe „embarrassingly parallel“ ist — jeder Code ist unabhängig.

*Konservativität:* Gemessen wurde eine reine Python-Implementierung in einer
Sandbox-Umgebung. C-Bibliotheken wie `libqrencode` sind erfahrungsgemäß nochmals
deutlich schneller (hier nicht gemessen); alle folgenden Hochrechnungen sind also
eher Ober- als Untergrenzen.

## 4. Hochrechnung: Rechenressourcen

Basis: 246 Codes/s je Kern (PNG) bzw. 915 Codes/s auf der 4-Kern-Maschine.

| Menge                          | 4-Kern-Rechner (gemessen/extrapoliert) | Kernstunden gesamt |
|--------------------------------|---------------------------------------:|-------------------:|
| 1 URL                          | ~4 ms                                  | vernachlässigbar   |
| 1 000 URLs                     | ~1,1 s                                 | vernachlässigbar   |
| 1 Mio. URLs                    | **~18 Minuten**                        | ~1,1               |
| 100 Mio. URLs                  | ~30 Stunden                            | ~113               |
| **1,766 Mrd. (Gesamtdatensatz)** | **~22 Tage**                         | **~2 000**         |

Für den Gesamtdatensatz **„in wenigen Stunden“** (Ziel: 4 h) werden
1,766 Mrd. ÷ (4 × 3 600 s) ≈ 123 000 Codes/s benötigt, also **~500 vCPUs** bei
idealer Skalierung — mit dem gemessenen Parallelisierungsverlust von 7 % eher
~540 vCPUs (135 Instanzen à 4 vCPUs) bzw. gut 4 Stunden mit 500 vCPUs.
Der Datensatz liegt bereits in 1 518 Länder-Shards vor —
die Verteilung auf Worker ist trivial. RAM ist irrelevant (< 100 MB je Prozess),
der Engpass ist reine CPU-Zeit und ggf. Schreib-I/O.

Grobe Energieabschätzung: ~2 000 Kernstunden × 5–10 W je Kern ≈ **10–20 kWh** für den
kompletten Datensatz — weniger als eine Tankfüllung, im Stil der „Random facts“ des
Projekt-READMEs.

## 5. Kostenschätzung

### 5.1 Software: 0 €

Alle genannten Bibliotheken sind Open Source (BSD/MIT). Es fallen keine Lizenz- oder
API-Kosten an. Der QR-Code selbst ist patentfrei nutzbar (Denso Wave übt seine
Patente für spezifikationskonforme Codes nicht aus); „QR Code“ ist lediglich eine
eingetragene Marke.

### 5.2 Rechenkosten (Cloud, Stand August 2026, recherchiert)

| Anbieter/Instanz                        | vCPUs | Preis/h        | Quelle/Modell |
|-----------------------------------------|------:|---------------:|---------------|
| AWS c7g.xlarge (us-east-1)              | 4     | 0,145 USD      | On-Demand     |
| AWS c7a.xlarge (us-east-1)              | 4     | 0,205 USD      | On-Demand     |
| AWS c7a.xlarge (us-east-1a)             | 4     | ~0,094 USD     | Spot (Momentaufnahme, schwankt) |
| Hetzner CCX23 (US-Standorte)            | 4     | ~0,141 USD     | abgeleitet aus 102,99 USD/Monat; Quellen uneinheitlich (32–103 USD/Monat) |
| Hetzner CPX31 (shared vCPU, US)         | 4     | ~0,034 USD     | abgeleitet aus 24,99 USD/Monat (Stand 04/2026, spätere Erhöhung möglich) |

Daraus für die **Massengenerierung des Gesamtdatensatzes (~2 000 Kernstunden =
500 Instanzstunden à 4 vCPUs)**:

- On-Demand (c7g.xlarge): 500 h × 0,145 USD ≈ **73 USD**; mit Orchestrierungs-/I/O-Puffer < 100 USD
- Spot-Instanzen: typischerweise 40–70 % unter On-Demand, also grob **20–50 USD**
  (40–70 % Rabatt ≈ 22–44 USD; der zitierte c7a-Spot-Schnappschuss ergäbe ~47 USD)
- Sparvariante: ein einzelner 4-vCPU-Server (z. B. Hetzner CPX31 ~25 USD/Monat,
  CCX23 32–103 USD/Monat je nach Quelle) rechnet den Datensatz in ~3 Wochen durch

Für kleine Mengen (bis einige Millionen Codes) sind die Rechenkosten praktisch null —
das erledigt jeder Laptop nebenbei.

### 5.3 Speicherkosten — der eigentliche Knackpunkt bei 1,77 Mrd. Dateien

Reines Datenvolumen (gemessene Dateigrößen × 1,766 Mrd.):

- PNG (~150×150 px): 312 B/Code → **~550 GB**
- SVG: 1 604 B/Code → ~2,8 TB

Speicherpreise (recherchiert, Stand August 2026): AWS S3 Standard ~23 USD/TB-Monat,
Backblaze B2 ~6 USD/TB-Monat, Hetzner Object Storage ~6 USD/Monat inkl. 1 TB. Die
PNG-Variante kostet also **3–13 USD pro Monat** Speicher.

**Zwei nicht offensichtliche Kostenfallen:**

1. **Request-Kosten dominieren bei S3:** 1,766 Mrd. einzelne PUT-Uploads kosten bei
   ~0,005 USD je 1 000 Requests einmalig **~8 800 USD** — mehr als das 100-Fache der
   Rechenkosten. Backblaze B2 (Uploads kostenlos) oder gebündelte Ablage vermeiden das.
2. **Dateisystem-Overhead:** 1,77 Mrd. Einzeldateien à 312 B belegen bei 4-KiB-Blöcken
   real **~7 TB** statt 550 GB und sprengen übliche Inode-Budgets. Konsequenz: Codes
   gebündelt speichern (tar/xz wie im Repo üblich, SQLite, Parquet) — oder gar nicht
   vorspeichern (siehe Abschnitt 6).

## 6. Architekturempfehlung: on demand statt auf Vorrat

Da ein QR-Code — bei fixierter Bibliothek und Parametern — eine **deterministische
Funktion der URL** ist und seine Erzeugung nur ~4 ms kostet, ist Vorratsgenerierung
meist unnötig:

- **Serverseitig on demand:** Ein Endpunkt `GET /qr?url=…` (z. B. FastAPI + `segno`)
  liefert den Code in Millisekunden; ~250 Codes/s je Kern genügen für erheblichen
  Traffic, plus triviales Caching. Speicherkosten: 0.
- **Clientseitig:** JavaScript-Bibliotheken erzeugen den Code im Browser — Server- und
  Speicherkosten: 0.
- **Vorratsgenerierung** lohnt nur, wenn alle Codes als Datenprodukt ausgeliefert
  werden sollen (etwa als zusätzliches Dataset-Artefakt dieses Projekts) — dann
  gebündelt als xz-Archive analog zur bestehenden `data/`-Struktur.

## 7. Konkreter AWS-Ausführungsplan (~512 vCPU)

Falls doch auf Vorrat generiert werden soll, hier die durchgerechnete Flotte.
Alle Zahlen aus AWS' eigenem Spot-Advisor-Feed (abgerufen 08/2026) bzw. aus dem
Probelauf; Preise sind us-east-1, Linux.

### 7.1 Flotte: 16 × c7g.8xlarge auf Spot

| Posten | Wert |
|--------|------|
| Instanz | **c7g.8xlarge** (Graviton3, ARM64), 32 vCPU, 64 GiB |
| Anzahl | **16** → **512 vCPU** |
| Spot-Abbruchrate | **< 5 %** (bestes Band des Spot Advisors) |
| Spot-Ersparnis | 65 % gegenüber On-Demand |
| Flottenkosten | **~6,50 USD/h** Spot, 18,56 USD/h On-Demand |
| Laufzeit | **~4,0 h** (gemessen hochgerechnet) |
| **Gesamtkosten Rechnen** | **~26 USD Spot / ~74 USD On-Demand** |

Warum c7g und nicht c7a: identische Leistung für diese Aufgabe, aber 29 %
günstiger je vCPU on-demand und **rund doppelt so günstig auf Spot** — und vor
allem stabiler. `c7a.48xlarge` und `c7a.12xlarge` liegen im schlechtesten
Abbruchband (> 20 %), `c7g.8xlarge` im besten (< 5 %). Die kleineren c7g-Größen
sind stabiler als `c7g.16xlarge` (5–10 %); 16 Instanzen streuen das Risiko
zusätzlich. ARM ist hier gratis: `segno` ist ein `py3-none-any`-Wheel ohne
Kompilat und ohne Laufzeitabhängigkeiten — auf Graviton gibt es nichts zu
portieren.

### 7.2 Task-Zuschnitt: 8 831 Tasks à 200 000 Codes

Die Task-Größe folgt aus der Spot-Abbruchrate, nicht aus Bequemlichkeit: Ein
abgebrochener Task wird komplett wiederholt, also darf er nicht lange laufen.

- **200 000 Codes je Task ≈ 14 Minuten** — ein Abbruch kostet höchstens das.
- **8 831 Tasks** bleiben unter dem **harten Limit von 10 000** je AWS-Batch-Array-Job
  (nicht erhöhbar). Tasks deutlich größer zu schneiden, spart nichts und macht
  Abbrüche teuer.
- Bei 512 vCPUs laufen ~17 Wellen à 14 min ⇒ ~4 h.
- Das Zwei-Minuten-Fenster einer Spot-Kündigung reicht **nicht**, um ein Artefakt
  fertigzustellen und hochzuladen. Deshalb ist die Pipeline auf *idempotente
  Wiederholung* ausgelegt statt auf geordnetes Austrudeln.

### 7.3 Kontingente vorher prüfen — der häufigste Stolperstein

| Kontingent | Code | Standard |
|------------|------|----------|
| Running On-Demand Standard instances | `L-1216C47A` | 5 vCPU (neuer Account), 1 152 vCPU (etabliert) |
| All Standard Spot Instance Requests | `L-34B43A08` | 5 vCPU (neuer Account) |

Beide zählen in **vCPUs, nicht in Instanzen**, und c7g wie c7a fallen beide unter
„Standard“ — die 512 vCPU lassen sich also nicht durch Mischen von Familien
umgehen. On-Demand und Spot sind getrennte Zähler.

Prüfen lässt sich das vorab per CLI:

```bash
aws service-quotas get-service-quota --service-code ec2 \
  --quota-code L-1216C47A --query 'Quota.Value'   # On-Demand
aws service-quotas get-service-quota --service-code ec2 \
  --quota-code L-34B43A08 --query 'Quota.Value'   # Spot
```

Bei einem etablierten Account genügen die 1 152 vCPU bereits; bei einem neuen
Account blockieren 5 vCPU den Lauf vollständig. Ein Sprung von 5 auf 512 geht in
die manuelle Prüfung (1–3 Werktage, kein Eskalationsweg) — **also ein bis zwei
Wochen vorher beantragen**, nicht am Vortag.

Zwei Einordnungen, die den Quota-Ärger relativieren:

- **Das ist nicht die GPU-Quota.** Die als zäh bekannte Freischaltung „großer
  Maschinen" betrifft die P-Familie (`L-417A185B`, GPU-Instanzen) — die braucht
  dieser Lauf nicht. C-Familie-Erhöhungen genehmigt AWS deutlich routinierter.
- **Die Quota kauft nur Wanduhrzeit, kein Geld.** Die ~2 000 Kernstunden sind
  fix: 512 vCPU ⇒ ~4 h, 128 vCPU ⇒ ~16 h, 64 vCPU ⇒ ~31 h — die Kosten bleiben
  jeweils ~26 USD (Spot). Da die Pipeline idempotent und unbeaufsichtigt läuft,
  ist ein Wochenend-Lauf auf kleiner Quota ein vollwertiger Plan B ohne Antrag;
  Spot und On-Demand sind zudem getrennte Zähler. Plan C ganz ohne Quotas ist
  der Pod-Weg aus Abschnitt 7.7. Ein Nebeneffekt, der viel Zeit
kostet: AWS Batch meldet fehlendes Kontingent nicht als Fehler, die Jobs bleiben
einfach unbegrenzt in `RUNNABLE` hängen.

### 7.4 Orchestrierung

Für einen **einmaligen** Lauf ist **EC2 Fleet (`type: instant`) + SQS + Bootstrap
aus S3** der kürzeste Weg: kein Container-Image, keine ECR-Registry, keine
service-linked Roles. Achtung auf das **harte 16-KB-Limit für User-Data** — das
Bootstrap-Skript lädt die Nutzlast per `aws s3 cp` nach, statt sie einzubetten.

**AWS Batch mit Array-Jobs** kostet beim ersten Mal einige Stunden Einrichtung
(Compute Environment, Job Queue, Job Definition, ECR-Image, IAM-Rollen), liefert
dafür Retry-Logik, `AWS_BATCH_JOB_ARRAY_INDEX` und CloudWatch-Logs geschenkt —
die bessere Wahl, wenn der Lauf wiederholbar sein soll. `qr_pipeline.py` liest
den Task-Index direkt aus dieser Variablen.

Nicht geeignet: **Fargate** (16 vCPU je Task, Graviton2 statt Graviton3, unklares
vCPU-Kontingent) und **ParallelCluster** (für eng gekoppeltes MPI-HPC gebaut, hier
komplett überdimensioniert).

### 7.5 S3

- Ausgabe sind ~8 831 Artefakte à ~50 MB, zusammen **~0,44 TB** →
  **PUT-Kosten 0,04 USD**. Zum Vergleich: einzelne Dateien hätten ~8 800 USD
  gekostet. Upload nach S3 ist kostenlos, Speicher ~10 USD/Monat.
- **Vor dem Lauf eine Lifecycle-Regel `AbortIncompleteMultipartUpload` (1 Tag)
  setzen.** Bei Spot-Abbrüchen mitten im Upload bleiben sonst verwaiste
  Multipart-Fragmente liegen, für die dauerhaft Speicher berechnet wird.
- Jeder `UploadPart` zählt als PUT — bei ~50-MB-Artefakten irrelevant, bei
  vielen kleinen Teilen nicht.

### 7.6 Bootstrap auf Amazon Linux 2023 (ARM64)

AMI über den SSM-Parameter beziehen statt AMI-IDs zu verdrahten:

```
/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64
```

Das System-Python von AL2023 ist 3.9; Python 3.11 kommt per `dnf install
python3.11` daneben. **Den Symlink `/usr/bin/python3` nicht umbiegen** — `dnf`
benutzt ihn selbst und die Paketverwaltung bricht. Stattdessen `python3.11`
explizit aufrufen:

```bash
dnf install -y python3.11 python3.11-pip
python3.11 -m pip install segno
```

### 7.7 Alternative: gpu.ai-Pod (z. B. B300) statt AWS-Flotte

Für Teams, die bereits einen GPU-Cloud-Workflow haben (rclone/Drive statt S3,
Pods statt Instanzen), liegt [`qr_gpuai_start.sh`](qr_gpuai_start.sh) bei. Es
folgt den erprobten Konventionen eines früheren GPU-Projekts des Nutzers
(Vollscan-Runner) und übernimmt daraus die Muster, die sich dort bewährt haben:

- **Positivkontrolle vor dem Fan-out** — der erste Task läuft allein und wird
  vollständig verifiziert (Prüfsumme + Decodierung); erst danach starten die
  restlichen Worker. Ein systematischer Fehler kostet so Minuten, nicht den Lauf.
- **Messung vor Verpflichtung** — das Skript misst den echten Durchsatz der
  Maschine am ersten Task und druckt Laufzeit- und Kostenprojektion, bevor die
  lange Rechnung beginnt.
- **Wiederholrunden** (bis zu 3) über offene Tasks statt Einzel-Retry-Logik.
- **Zwischenstand-Verschiebung alle 120 s** nach Drive (`rclone move`); fertige
  Artefakte sind atomar, es kann nichts Halbes ankommen.
- **Marker-Dateien in Drive** für Shard-Fortschritt und POD/PODS-Streifen für
  mehrere Pods — Wiederaufsetzen ist derselbe Befehl noch einmal.
- **Kostenuhr-Warnung**: Container-Pods können sich nicht selbst abschalten;
  das Skript endet mit einem unübersehbaren „POD STOPPEN"-Hinweis.

Die Ökonomie ist klar anders als bei der AWS-Flotte: Die QR-Erzeugung nutzt
**keine GPU** — auf einem B300-Pod rechnet nur die Host-CPU, das
GPU-Silizium liegt brach. Bei ~7,76 USD/h und typischen 100–200 Host-vCPUs
landet der Gesamtdatensatz bei grob 9–18 h ⇒ **70–140 USD** gegenüber
~26 USD für die reine CPU-Spot-Flotte. Sinnvoll ist der Pod-Weg also nur,
wenn die Maschine ohnehin läuft, Credits vorhanden sind oder der
Drive-Workflow den Ausschlag gibt — nicht aus Kostengründen.

Übungsmodus (klein, lokal, ohne Drive):

```bash
QR_LIMIT_SHARDS=1 QR_TEST_ZEILEN=40000 QR_CODES_JE_TASK=10000 \
QR_DRIVE_ZIEL= QR_DATEN=./data bash feasibility/qr_gpuai_start.sh
```

## 8. Antwort auf die Kernfrage: „In wenigen Stunden möglich?“

| Interpretation                                            | Machbar in wenigen Stunden? |
|-----------------------------------------------------------|-----------------------------|
| Funktionierender Prototyp (Skript, Einzel-URLs)           | **Ja — unter 1 Stunde** (Kern ist ein Fünfzeiler) |
| Batch-Pipeline über Datensatz-Shards                      | **Ja — 1–2 Stunden** Entwicklungsaufwand |
| Web-API oder Browser-Lösung, einsatzbereit                | **Ja — 2–4 Stunden** inkl. Deployment |
| 1 Mio. Codes erzeugen                                     | **Ja — ~18 Minuten** auf 4 Kernen |
| Gesamtdatensatz (1,77 Mrd.) auf einem Rechner             | Nein — ~3 Wochen (aber unbeaufsichtigt) |
| Gesamtdatensatz mit ~500 Cloud-vCPUs                      | **Ja — gut 4 Stunden, < 100 USD** |

**Gesamturteil: uneingeschränkt machbar.** Es bestehen keine wissenschaftlichen oder
technischen Risiken; Kosten und Ressourcenbedarf sind selbst im Milliardenmaßstab
gering. Die einzige echte Designentscheidung ist nicht *ob*, sondern *wie*: on demand
generieren statt Milliarden Kleinstdateien zu speichern, und bei Objektspeichern auf
Request-Kosten achten.

## 9. Grenzen dieser Einschätzung

- Der Benchmark lief in einer Sandbox mit 4 vCPUs unbekannten Typs; dedizierte
  Cloud-Kerne sind eher schneller. Gemessen wurde reines Python — C-Implementierungen
  wären schneller. Beides macht die Schätzungen konservativ.
- Die URL-Längenverteilung stammt aus einer 200 000er-Zufallsstichprobe eines
  Länder-Shards (6 Mio. Domains, Österreich); andere TLDs können leicht abweichen,
  ändern aber nichts an der Versionsklasse (v2–v4). Internationalisierte Domains
  liegen fast ausschließlich als ASCII/Punycode vor (im untersuchten Shard 4
  Nicht-ASCII-Ausnahmen unter 6 Mio., teils mit defekter Kodierung) und sind für
  den Byte-Modus unproblematisch.
- Cloud-Preise wurden im August 2026 aus Sekundärquellen recherchiert (Suchtreffer,
  je ≥ 2 Quellen); Spot-Preise schwanken stündlich, und Hetzner hat 2026 mehrfach
  die Preise erhöht — vor einer konkreten Beschaffung aktuelle Listenpreise prüfen.
- Die Spot-Abbruchraten und vCPU-Zahlen in Abschnitt 7 stammen aus AWS' eigenem
  Spot-Advisor-Feed, die On-Demand-Dollarpreise dagegen aus Aggregatoren (die
  AWS-Preis-API war nicht erreichbar). Die Abbruchbänder sind rollierende
  30-Tage-Mittel je Region, keine Prognose und nicht AZ-genau. Das
  Fargate-vCPU-Kontingent `L-3032A538` blieb widersprüchlich (6 vs. 4 000) — im
  eigenen Konto prüfen, falls Fargate doch infrage kommt.
- Bewertet wurde die *Erzeugung* von QR-Codes; Scan-Zuverlässigkeit auf Endgeräten
  (Druckgröße, Kontrast, Fehlerkorrekturwahl) ist ein separates, ebenfalls gut
  verstandenes Thema.

## 10. Trockenübung vor dem scharfen Lauf

Der Probelauf [`qr_toy_run.sh`](qr_toy_run.sh) fährt die komplette Pipeline
[`qr_pipeline.py`](qr_pipeline.py) im Kleinen: Er simuliert einen
AWS-Batch-Array-Job lokal (`AWS_BATCH_JOB_ARRAY_INDEX` wird genauso gesetzt wie
dort), verifiziert jedes Artefakt, probt Idempotenz und Spot-Abbruch und rechnet
die Messwerte auf die Flotte hoch:

```bash
pip install segno opencv-python-headless      # Decoder optional
./feasibility/qr_toy_run.sh                   # synthetische Domains
TOY_INPUT=data/austria/domain2multi-at00.txt ./feasibility/qr_toy_run.sh
```

Geprüft werden die sechs Dinge, die einen 512-vCPU-Lauf ruinieren können:

1. **Bilanz** — jede Eingabezeile ist erzeugt oder als Ausschuss gezählt.
2. **Verifikation** — Prüfsumme je Artefakt plus echtes Decodieren einer
   Stichprobe, nicht nur „Datei existiert“.
3. **Atomarität** — es gibt keine halben Artefakte, nur `.tmp` oder fertig.
4. **Idempotenz** — ein Wiederanlauf überspringt fertige Tasks.
5. **Spot-Abbruch** — SIGTERM führt zu Exit 75 (`EX_TEMPFAIL`), das Fragment
   wird verworfen, die Wiederholung liefert ein vollständiges Artefakt.
6. **Hochrechnung** — gemessener Durchsatz → Laufzeit, Kosten, Datenmenge.

Zwei Befunde, die erst der Probelauf zutage gefördert hat und die im scharfen
Lauf teuer geworden wären:

- **Micro-QR-Codes:** `segno.make()` erzeugt für sehr kurze URLs wie
  `https://a.at` standardmäßig einen *Micro*-QR-Code (Version M1–M4) statt eines
  normalen QR-Codes. Viele Kamera-Apps lesen die nicht. Die Zufallsstichprobe des
  Benchmarks enthielt keinen einzigen; die alphabetisch sortierte Eingabe des
  Probelaufs sofort mehrere. Beide Skripte setzen deshalb explizit `micro=False`.
- **Bündelformat:** Ein reines `tar` verdreifacht den Platzbedarf, weil jeder
  312-Byte-PNG auf zwei 512-Byte-Blöcke aufgerundet wird. `tar.xz` kommt auf
  **249 B je Code** — kleiner als das nackte PNG — und kostet nur ~0,1 ms je
  Code. Gemessene Gesamtausgabe: **0,44 TB** statt der 7 TB, die Einzeldateien
  auf einem 4-KiB-Dateisystem belegt hätten.

## 11. Reproduzierbarkeit & Quellen

Reproduktion: `pip install segno qrcode pillow`, einen Daten-Shard entpacken
(`xz -dk data/<land>/*.xz`), dann `python3 feasibility/qr_benchmark.py`
(Pfad der Domainliste via Umgebungsvariable `DOMAINS_SAMPLE`). Die Kapazitätstabelle
in Abschnitt 2 lässt sich mit `python3 feasibility/qr_capacity_check.py` gegen beide
Bibliotheken verifizieren.

- ISO/IEC 18004:2024 — <https://www.iso.org/standard/83389.html>
- Bibliotheken: [segno](https://github.com/heuer/segno), [python-qrcode](https://github.com/lincolnloop/python-qrcode), [libqrencode](https://fukuchi.org/works/qrencode/)
- Datensatzstatistik: [STATS.md](../STATS.md)
- Preisquellen (Auswahl, abgerufen 2026-08): [AWS S3 Pricing](https://aws.amazon.com/s3/pricing/), [Backblaze B2](https://www.backblaze.com/cloud-storage/pricing), [Hetzner Object Storage](https://www.hetzner.com/storage/object-storage/), economize.cloud / cloudprice.net (EC2 c7g/c7a)
- Rohdaten des Benchmarks: [`qr_benchmark_report.json`](qr_benchmark_report.json)
- AWS-Fakten in Abschnitt 7: [Spot Instance Advisor
  (Feed)](https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json),
  [AWS-Batch-Kontingente](https://docs.aws.amazon.com/batch/latest/userguide/service_limits.html),
  [EC2-Spot-Kontingente](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-spot-limits.html),
  [EC2-Fleet-Kontingente](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/fleet-quotas.html),
  [S3-Multipart-Limits](https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html),
  [Python unter AL2023](https://docs.aws.amazon.com/linux/al2023/ug/python.html)
