# Product Requirements Document (PRD): DokuWiki MCP Server

## 1. Executive Summary

Dieses PRD definiert die Anforderungen und die Architektur für einen Model Context Protocol (MCP) Server zur Anbindung einer DokuWiki-Instanz. Das primäre Ziel ist nicht die bloße 1:1-Durchreichung der REST/XML-RPC-API, sondern die Etablierung einer intelligenten Middleware. Der MCP-Server übernimmt die Aufgabe der **semantischen Verdichtung** (Information Perception) und ermöglicht effizientes, agentisches Lesen, Editieren und Umstrukturieren von Informationen durch Large Language Models (LLMs), bei gleichzeitig minimalem Token-Verbrauch und reduzierter Fehleranfälligkeit.

## 2. Ausgangslage & Basis-Architektur

* **Fundament:** Die Basis bildet eine vollständig in Pydantic typisierte Formalisierung der DokuWiki-API (Contract-First).

* **Herausforderung:** Eine direkte Übergabe dieser komplexen Typisierungen an das LLM führt zu "Tool Bloat", hohem Token-Verbrauch und gesteigerter Halluzinationsrate bei der Parameterübergabe.

* **Lösungsansatz:** Das **Data Transfer Object (DTO) Pattern**. Der MCP-Server implementiert eine strikte Zwei-Schichten-Architektur:

  1. **Interne Schicht:** Vollständige, typsichere Abbildung der API-Logik (Pydantic).

  2. **Externe (LLM-facing) Schicht:** Radikal reduzierte, semantisch verdichtete Schnittstellen (Tools), die auf die kognitiven Fähigkeiten und Einschränkungen von Agenten zugeschnitten sind.

## 3. Kernkonzepte der Semantischen Verdichtung (Information Perception)

Diese Konzepte zielen darauf ab, den Input für das LLM zu komprimieren (Rauschen minimieren) und die Steuerung durch das LLM effizienter zu gestalten (weniger Roundtrips).

### 3.1. Read & Search (Input-Kompression)

Der Server agiert als Filter- und Aggregations-Engine.

* **Layout Stripping & Content Chunking:** Wiki-Markup wird serverseitig in sauberes Markdown transformiert. Das LLM erhält auf Wunsch isolierte semantische Abschnitte (z.B. nur ein spezifisches Kapitel) statt der gesamten Seite.

* **Lokale NLP-Verdichtung (Offline):**

  * *Keyword-Extraktion:* Initiale Suchergebnisse werden durch leichtgewichtige Verfahren (z.B. YAKE) auf Top-Schlüsselwörter reduziert, um dem LLM eine schnelle Relevanzbewertung zu ermöglichen.

  * *Extrahierende Zusammenfassung (TextRank/TF-IDF):* Der Server berechnet lokal die wichtigsten Sätze eines Dokuments ("Executive Summary") für schnelle Überblicke.

* **Progressive Disclosure (Drill-Down):** Werkzeuge liefern initial nur das Inhaltsverzeichnis (TOC) und Metadaten. Detaillierte Inhalte werden vom LLM bedarfsgerecht nachgeladen.

* **Meta-Data Aggregation & Hashing:** Redundante Informationen (Revisionsdaten, ACLs, Boilerplate-Texte) werden serverseitig in kompakte Header oder Referenz-Token dedupliziert.

* **Pagination Abstraction (Anti-Blätter-Muster):** Paginierung der API wird vor dem LLM verborgen. Der Server iteriert selbstständig und liefert ein konsolidiertes, verdichtetes Top-N-Ergebnis.

### 3.2. Targeted Querying (Output-Optimierung des LLMs)

Das LLM wird befähigt, Suchanfragen präzise zu steuern.

* **Polymorphe Schemas:** Nutzung von *Discriminated Unions* in Pydantic, um Lese-Aktionen (Suche, Page-Fetch, TOC-Fetch) in einem Super-Tool zu bündeln, gesteuert über einen `action`-Parameter.

* **Multi-Query Batching & Exclusion:** Das LLM kann Arrays von Suchbegriffen absetzen und irrelevante Namespaces explizit ausschließen, um die Treffermenge serverseitig zu filtern.

* **Fuzzy Resolution:** Der Server toleriert leichte Syntax-Fehler bei Seiten-IDs (Levenshtein-Distanz) und löst diese lokal auf, ohne das LLM mit Fehlermeldungen in Schleifen zu zwingen.

* **Regex-gestützte Extraktion:** Das LLM kann reguläre Ausdrücke übergeben, die der Server lokal auf das Dokument anwendet, um ausschließlich strukturierte Treffer (z.B. IPs, URLs) zurückzuliefern.

## 4. Kernkonzepte für Agentic Authoring & Refactoring

Diese Konzepte sichern die Autonomie des Agenten ab und verlagern Verarbeitungs- und Validierungslast auf den Server.

### 4.1. Stateful Operations

* **Stateful Context:** Der MCP-Server merkt sich Zustände (z.B. den `active_namespace`), sodass das LLM diese Parameter nicht bei jedem Tool-Aufruf repetitiv mitsenden muss.

### 4.2. Sicheres Editieren (Schreiben)

* **Two-Phase Commit (Plan & Execute):** Schreiboperationen erfolgen zweistufig. Das `prepare`-Tool liefert einen semantischen Diff zurück. Das LLM (oder der User) muss die Änderung über ein `commit`-Tool mit der entsprechenden Transaction-ID finalisieren.

* **Section-Level Edits:** Werkzeuge ermöglichen die gezielte Manipulation einzelner Überschriften-Äste, anstatt die gesamte Seite neu zu verfassen (Minimierung von Halluzinationen und Latenz).

* **Dynamic Templating & Linting:** Der Server stellt Pydantic-Modelle für standardisierte Strukturen bereit (z.B. Tabellen) und formatiert diese serverseitig in DokuWiki-Syntax. Ein Linter prüft die vom LLM generierte Syntax vor dem API-Write.

### 4.3. Strukturierung & Reorganisation

* **Semantic Diffing & Orphan Resolution:** Tools zur inhaltlichen Bewertung von Änderungen (jenseits von String-Matching) und zur Identifikation und agentischen Eingliederung verwaister Seiten.

* **Cross-Reference Management:** Nach Seitenverschiebungen oder Refactorings bietet der Server Tools zur Überprüfung und Korrektur interner Links im betroffenen Namespace.

* **Automated Taxonomy:** Das LLM analysiert Inhalte und generiert Vorschläge für Tags/Kategorien, die als Metadaten im Wiki verankert werden.

## 5. Fallback & Fehlerbehandlung

* **Proxy & Spec Pattern:** Für Operationen jenseits der semantischen Makro-Tools wird ein abstraktes `dokuwiki_raw_proxy`-Tool bereitgestellt. Dieses wird mit einem Dokumentations-Lesewerkzeug kombiniert, damit das LLM die Bedienung der Raw-API autonom erlernen kann.

* **Error as Actionable Prompts:** HTTP- und Validierungs-Fehler werden nicht als Stacktraces, sondern als konkrete, natürlichsprachliche Handlungsanweisungen für den Agenten formuliert.