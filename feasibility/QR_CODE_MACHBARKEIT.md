Machbarkeitseinschätzung: Generierung von QR-Codes aus URLs
===========================================================

**Kurzantwort:** Ja — die Generierung von QR-Codes aus URLs ist wissenschaftlich und
technisch vollständig gelöst, extrem günstig und in wenigen Stunden umsetzbar. Ein
funktionierender Prototyp ist in unter einer Stunde fertig; selbst die Massengenerierung
für den **gesamten Datensatz dieses Repositories (1.766.025.618 Domains)** ist mit
~500 Cloud-vCPUs in etwa 4 Stunden und für unter 100 USD Rechenkosten machbar.
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
4. **Zeitaufwand** — „ist so etwas in wenigen Stunden möglich?"

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
URL ergibt immer denselben Code. Ausgereifte Open-Source-Implementierungen existieren
für praktisch jede Sprache (Python: `segno`, `qrcode`; C: `libqrencode`; JavaScript,
Go, Rust, Java u. v. m.), alle kostenlos.

**Passen URLs überhaupt in einen QR-Code?** Die Byte-Modus-Kapazität nach
ISO/IEC 18004 (verifiziert durch Kreuzvalidierung zweier unabhängiger
Implementierungen, `segno` 1.6.6 und `qrcode` 8.2 — alle 24 Werte identisch):

| Version | Module  | ECC L | ECC M | ECC Q | ECC H |
|--------:|:-------:|------:|------:|------:|------:|
| 1       | 21×21   | 17    | 14    | 11    | 7     |
| 2       | 25×25   | 32    | 26    | 20    | 14    |
| 3       | 29×29   | 53    | 42    | 32    | 24    |
| 4       | 33×33   | 78    | 62    | 46    | 34    |
| 5       | 37×37   | 106   | 84    | 60    | 44    |
| 40      | 177×177 | 2 953 | 2 331 | 1 663 | 1 273 |

Die URLs dieses Datensatzes (gemessen an 6 Mio. realen Domains, Präfix `https://`)
sind im Mittel **34,7 Zeichen** lang (Median 36, 95-Perzentil 46, Maximum 99). Damit
genügt fast immer **Version 2–4** bei mittlerer Fehlerkorrektur (ECC M) — kleine,
gut scannbare Codes. Gemessene Versionsverteilung (n = 5 000): v1 0,2 %, v2 25,9 %,
**v3 41,1 %**, v4 32,7 %, v5–v6 < 0,1 %. Die Verteilung deckt sich exakt mit der
Kapazitätstabelle — ein Konsistenzbeleg für beide Messungen. Selbst extreme URLs bis
2 953 Bytes passen (Version 40, ECC L); praktisch relevant ist das hier nicht.

## 3. Empirische Messung (Benchmark)

Methodik: Benchmark in dieser Repository-Umgebung (Python 3.11.15, 4 vCPUs, 15 GiB
RAM), Eingabe: Zufallsstichprobe aus **6.007.258 realen Domains** des Datensatzes
(Shard `data/austria`), als `https://`-URLs. Skript: [`qr_benchmark.py`](qr_benchmark.py),
Rohdaten: [`qr_benchmark_report.json`](qr_benchmark_report.json). Je Variante wurden
2 000 Codes einzeln vermessen, dazu ein Durchsatztest mit 40 000 Codes auf allen
4 Kernen.

| Variante                        | Zeit/Code | Codes/s (1 Kern) | ø Dateigröße |
|---------------------------------|----------:|-----------------:|-------------:|
| `segno` nur Matrix (kein Bild)  | 3,24 ms   | 308              | —            |
| `segno` → PNG (scale 4)         | 4,06 ms   | 246              | 312 B        |
| `segno` → SVG                   | 4,27 ms   | 234              | 1 604 B      |
| `qrcode` + Pillow → PNG         | 5,96 ms   | 168              | 706 B        |
| `segno` → PNG, **4 Prozesse**   | —         | **915 gesamt**   | 312 B        |

Kernbefund: **Ein einzelner QR-Code kostet ~4 Millisekunden CPU-Zeit und ~300 Bytes
Speicher.** Die Parallelisierung skaliert nahezu linear (93 % Effizienz auf 4 Kernen),
da die Aufgabe „embarrassingly parallel" ist — jeder Code ist unabhängig.

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

Für den Gesamtdatensatz **„in wenigen Stunden"** (Ziel: 4 h) werden
1,766 Mrd. ÷ (4 × 3 600 s) ≈ 123 000 Codes/s benötigt, also **~500 vCPUs**
(125 Instanzen à 4 vCPUs). Der Datensatz liegt bereits in 1 518 Länder-Shards vor —
die Verteilung auf Worker ist trivial. RAM ist irrelevant (< 100 MB je Prozess),
der Engpass ist reine CPU-Zeit und ggf. Schreib-I/O.

Grobe Energieabschätzung: ~2 000 Kernstunden × 5–10 W je Kern ≈ **10–20 kWh** für den
kompletten Datensatz — weniger als eine Tankfüllung, im Stil der „Random facts" des
Projekt-READMEs.

## 5. Kostenschätzung

### 5.1 Software: 0 €

Alle genannten Bibliotheken sind Open Source (BSD/MIT). Es fallen keine Lizenz- oder
API-Kosten an. Der QR-Code selbst ist patentfrei nutzbar (Denso Wave übt seine
Patente für spezifikationskonforme Codes nicht aus); „QR Code" ist lediglich eine
eingetragene Marke.

### 5.2 Rechenkosten (Cloud, Stand August 2026, recherchiert)

| Anbieter/Instanz                        | vCPUs | Preis/h        | Quelle/Modell |
|-----------------------------------------|------:|---------------:|---------------|
| AWS c7g.xlarge (us-east-1)              | 4     | 0,145 USD      | On-Demand     |
| AWS c7a.xlarge (us-east-1)              | 4     | 0,205 USD      | On-Demand     |
| AWS c7a.xlarge (us-east-1a)             | 4     | ~0,094 USD     | Spot (Momentaufnahme, schwankt) |
| Hetzner CCX23 (US-Standorte)            | 4     | ~0,141 USD     | abgeleitet aus 102,99 USD/Monat |

Daraus für die **Massengenerierung des Gesamtdatensatzes (~2 000 Kernstunden =
500 Instanzstunden à 4 vCPUs)**:

- On-Demand (c7g.xlarge): 500 h × 0,145 USD ≈ **73 USD**; mit Orchestrierungs-/I/O-Puffer < 100 USD
- Spot-Instanzen: typischerweise 40–70 % darunter, also grob **25–45 USD**
- Sparvariante: 1 einzelner Cloud-Server (~25–103 USD/Monat) rechnet den Datensatz in ~3 Wochen durch

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
   ~0,005 USD je 1 000 Requests einmalig **~8 800 USD** — das 100-Fache der
   Rechenkosten. Backblaze B2 (Uploads kostenlos) oder gebündelte Ablage vermeiden das.
2. **Dateisystem-Overhead:** 1,77 Mrd. Einzeldateien à 312 B belegen bei 4-KiB-Blöcken
   real **~7 TB** statt 550 GB und sprengen übliche Inode-Budgets. Konsequenz: Codes
   gebündelt speichern (tar/xz wie im Repo üblich, SQLite, Parquet) — oder gar nicht
   vorspeichern (siehe 6.).

## 6. Architekturempfehlung: on demand statt auf Vorrat

Da ein QR-Code eine **deterministische Funktion der URL** ist und seine Erzeugung nur
~4 ms kostet, ist Vorratsgenerierung meist unnötig:

- **Serverseitig on demand:** Ein Endpunkt `GET /qr?url=…` (z. B. FastAPI + `segno`)
  liefert den Code in Millisekunden; ~250 Codes/s je Kern genügen für erheblichen
  Traffic, plus triviales Caching. Speicherkosten: 0.
- **Clientseitig:** JavaScript-Bibliotheken erzeugen den Code im Browser — Server- und
  Speicherkosten: 0.
- **Vorratsgenerierung** lohnt nur, wenn alle Codes als Datenprodukt ausgeliefert
  werden sollen (etwa als zusätzliches Dataset-Artefakt dieses Projekts) — dann
  gebündelt als xz-Archive analog zur bestehenden `data/`-Struktur.

## 7. Antwort auf die Kernfrage: „In wenigen Stunden möglich?"

| Interpretation                                            | Machbar in wenigen Stunden? |
|-----------------------------------------------------------|-----------------------------|
| Funktionierender Prototyp (Skript, Einzel-URLs)           | **Ja — unter 1 Stunde** (Kern ist ein Fünfzeiler) |
| Batch-Pipeline über Datensatz-Shards                      | **Ja — 1–2 Stunden** Entwicklungsaufwand |
| Web-API oder Browser-Lösung, einsatzbereit                | **Ja — 2–4 Stunden** inkl. Deployment |
| 1 Mio. Codes erzeugen                                     | **Ja — ~18 Minuten** auf 4 Kernen |
| Gesamtdatensatz (1,77 Mrd.) auf einem Rechner             | Nein — ~3 Wochen (aber unbeaufsichtigt) |
| Gesamtdatensatz mit ~500 Cloud-vCPUs                      | **Ja — ~4 Stunden, < 100 USD** |

**Gesamturteil: uneingeschränkt machbar.** Es bestehen keine wissenschaftlichen oder
technischen Risiken; Kosten und Ressourcenbedarf sind selbst im Milliardenmaßstab
gering. Die einzige echte Designentscheidung ist nicht *ob*, sondern *wie*: on demand
generieren statt Milliarden Kleinstdateien zu speichern, und bei Objektspeichern auf
Request-Kosten achten.

## 8. Grenzen dieser Einschätzung

- Der Benchmark lief in einer Sandbox mit 4 vCPUs unbekannten Typs; dedizierte
  Cloud-Kerne sind eher schneller. Gemessen wurde reines Python — C-Implementierungen
  wären schneller. Beides macht die Schätzungen konservativ.
- Die URL-Längenverteilung stammt aus einem Länder-Shard (6 Mio. Domains, Österreich);
  andere TLDs können leicht abweichen, ändern aber nichts an der Versionsklasse
  (v2–v4). Internationalisierte Domains liegen im Datensatz als ASCII/Punycode vor
  und sind damit unproblematisch für den Byte-Modus.
- Cloud-Preise wurden im August 2026 aus Sekundärquellen recherchiert (Suchtreffer,
  je ≥ 2 Quellen); Spot-Preise schwanken stündlich, und Hetzner hat 2026 mehrfach
  die Preise erhöht — vor einer konkreten Beschaffung aktuelle Listenpreise prüfen.
- Bewertet wurde die *Erzeugung* von QR-Codes; Scan-Zuverlässigkeit auf Endgeräten
  (Druckgröße, Kontrast, Fehlerkorrekturwahl) ist ein separates, ebenfalls gut
  verstandenes Thema.

## 9. Reproduzierbarkeit & Quellen

Reproduktion: `pip install segno qrcode pillow`, einen Daten-Shard entpacken
(`xz -dk data/<land>/*.xz`), dann `python3 feasibility/qr_benchmark.py`
(Pfad der Domainliste via Umgebungsvariable `DOMAINS_SAMPLE`).

- ISO/IEC 18004:2024 — <https://www.iso.org/standard/83389.html>
- Bibliotheken: [segno](https://github.com/heuer/segno), [python-qrcode](https://github.com/lincolnloop/python-qrcode), [libqrencode](https://fukuchi.org/works/qrencode/)
- Datensatzstatistik: [STATS.md](../STATS.md)
- Preisquellen (Auswahl, abgerufen 2026-08): [AWS S3 Pricing](https://aws.amazon.com/s3/pricing/), [Backblaze B2](https://www.backblaze.com/cloud-storage/pricing), [Hetzner Object Storage](https://www.hetzner.com/storage/object-storage/), economize.cloud / cloudprice.net (EC2 c7g/c7a)
- Rohdaten des Benchmarks: [`qr_benchmark_report.json`](qr_benchmark_report.json)
