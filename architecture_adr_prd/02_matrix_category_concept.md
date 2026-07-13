# Konzept-Matrix: Semantische Verdichtung & Agentic Operations (Erweitert)

| Kategorie | Konzept | Beschreibung (MCP / Agentischer Fokus) |
| :--- | :--- | :--- |
| **Read & Search (Input-Kompression)**<br>*(MCP ➔ LLM)* | **Content Chunking** | Rückgabe isolierter semantischer Abschnitte (z. B. nur eine bestimmte Überschriften-Ebene) statt vollständiger Wiki-Seiten. |
| | **Layout Stripping** | Rigoroses Exkludieren von Standard-HTML-Elementen und Layout-Tags; Fokus liegt ausschließlich auf inhaltlichen Texten. |
| | **Lokale Keyword-Extraktion** | Nutzung lokaler NLP (z.B. YAKE) zur On-the-fly-Analyse. Das LLM erhält bei der initialen Suche nur Top-Keywords statt Volltext zur Relevanzprüfung. |
| | **Extrahierende Zusammenfassung** | Berechnung der semantisch wichtigsten Sätze (z.B. via TextRank/TF-IDF) für eine stark komprimierte "Executive Summary" der Seite. |
| | **Lokale Vektorsuche** | Serverseitiges Embedding (Semantic Chunking). Das LLM erhält via Ähnlichkeitssuche exakt die relevantesten Textabsätze statt klassischer Volltext-Treffer. |
| | **Progressive Disclosure** | Drill-Down-Verfahren: Das Lese-Tool liefert anfangs nur das Inhaltsverzeichnis (TOC). Der Agent lädt spezifische Kapitel gezielt nach. |
| | **Meta-Data Aggregation** | Zusammenfassen von ACLs, Autoren-Kürzeln und Revisionsdaten in einem extrem kurzen YAML-Header pro Treffer. |
| | **Strukturelles Hashing** | Deduplizierung: Identische Textbausteine (Boilerplate, Disclaimer) in aggregierten Inhalten werden durch Referenz-Token (`[REF: Block-A]`) ersetzt. |
| | **Backlink Contextualization** | Liefert zu einer gefundenen Seite direkt den Kontext der verweisenden Seiten mit, um die semantische Relevanz zu klären (Knowledge Graph Subsetting). |
| | **Pagination Abstraction** | "Anti-Blätter-Muster": Server aggregiert asynchron Suchergebnisse über mehrere API-Seiten hinweg und gibt eine finale Top-N-Liste zurück. |
| **Read & Search (Output-Optimierung)**<br>*(LLM ➔ MCP)* | **Multi-Query Batching** | Das Schema erlaubt Arrays von Suchbegriffen. Der MCP führt diese parallel aus, dedupliziert lokal und liefert ein bereinigtes Gesamt-Ergebnis. |
| | **Negative Prompting** | Das LLM nutzt Exclusion-Parameter (`exclude_namespaces`, `ignore_keywords`), um irrelevante Treffer an der Quelle auszuschließen. |
| | **Fuzzy Resolution** | Serverseitige Unschärfesuche (z.B. Levenshtein-Distanz) verzeiht Syntaxfehler des LLMs bei Seiten-IDs und löst diese transparent auf. |
| | **Regex-gestützte Extraktion** | Das LLM übergibt Regex-Pattern. Der Server wendet diese lokal an und liefert ausschließlich strukturierte Treffer (z.B. IPs, Links) zurück. |
| | **Zeitliche & Strukturelle Filter** | Parameter wie `modified_after` oder `min_heading_level` ermöglichen dem Agenten das präzise Eingrenzen des Suchraums. |
| | **Stateful Namespace Traversal** | Der MCP speichert den durchsuchten Namespace lokal. Das LLM muss diesen Kontext bei Folgeaufrufen nicht mehr als Parameter mitsenden. |
| **Agentic Authoring**<br>*(Schreiben)* | **Two-Phase Commit (Plan/Exec)** | Schreibvorgänge geben zunächst einen simulierten Diff zurück. Erst nach semantischer Prüfung wird die Änderung per `execute` persistiert. |
| | **Section-Level Edits** | Tools manipulieren gezielt nur den Ast eines bestimmten Headers, statt die gesamte Seite neu zu generieren (minimiert Halluzinations-Risiko). |
| | **Idempotent Writes** | Schreib-Tools garantieren, dass mehrfache identische Aufrufe des LLMs durch Retries den Wiki-Zustand nicht unbeabsichtigt vervielfältigen. |
| | **Dynamic Templating** | Bereitstellung strukturierter Pydantic-Modelle, die der Server vor dem API-Call in die korrekte DokuWiki-Syntax kompiliert. |
| | **Tone & Voice Alignment** | Dem LLM wird serverseitig ein Kontext-Prompt (z. B. "technische Doku vs. User-Guide") für den Ziel-Namespace mitgegeben. |
| | **Conflict Resolution** | Der Server fängt Edit-Collisions ab und weist das LLM an, einen Merge-Konflikt auf Basis des aktuellen Live-Zustands logisch aufzulösen. |
| **Refactoring & Sync**<br>*(Umstrukturieren)*| **Semantic Diffing** | Agent bewertet Inhaltsänderungen nicht nach String-Matching, sondern nach inhaltlicher Logik, bevor er Reorganisationen vorschlägt. |
| | **Orphan Resolution** | Ein Makro-Tool identifiziert verwaiste Seiten und lässt das LLM logische Eltern-Namespaces zur Eingliederung vorschlagen. |
| | **Automated Taxonomy** | Das LLM analysiert Text-Payloads und generiert eigenständig Tags/Kategorien, die als DokuWiki-Metadaten weggeschrieben werden. |
| | **Syntax Linting Hook** | Ein lokaler Validator prüft die vom LLM generierte DokuWiki-Syntax auf Fehler, bevor der eigentliche API-Write-Call ausgelöst wird. |
| | **Cross-Reference Checking** | Überprüfen und agentisches Korrigieren aller internen Links innerhalb eines Namespaces nach einer Seitenverschiebung. |
| **Agentic Bridging**<br>*(System-Übersetzung)*| **AST Mapping** | Überführung der Inhalte in einen Abstract Syntax Tree, um komplexe Logik verlustfrei zwischen DokuWiki und GitLab/Confluence zu übersetzen. |
| | **Macro Emulation** | DokuWiki-spezifische Plugins werden agentisch in äquivalente Zielsystem-Makros übersetzt. |
| | **Asset Relocation Workflow** | Tool lädt Medien herunter, lädt sie im Zielsystem hoch und passt die Verlinkungen im Text automatisch an. |
| | **Frontmatter Injection** | Automatisiertes Anreichern der konvertierten DokuWiki-Inhalte mit YAML-Frontmatter für Git-basierte Repositories. |
| | **Capability Negotiation** | Das LLM validiert die Features des Zielsystems (z.B. unterstützt es Mermaid-Charts?), um den Text passend zu formatieren. |
| | **Contextual Cross-Linking** | Umschreiben von relativen DokuWiki-Links in absolute URIs unter Berücksichtigung der neuen Ziel-Projektstruktur. |
| **Architecture Base**<br>*(Fundament)* | **DTO Pattern** | Strikte Trennung: Vollständige Pydantic-Abbildung der API nach innen, radikal entschlackte Schema-Sicht für das LLM nach außen. |
| | **Polymorphic Tooling** | Nutzung von *Discriminated Unions*, um Lese/Schreib-Aktionen in einem einzigen Super-Tool mit klar definierten Action-Flags zu bündeln. |
| | **Graceful Degradation** | Wenn semantische High-Level-Tools versagen, Rückfall auf ein überwachtes `Raw API Proxy` Tool (inklusive Dokumentations-Leser). |
| | **Error as Actionable Prompts** | API-Fehler werden serverseitig in konkrete Handlungsanweisungen für den Agenten übersetzt (z. B. "Lege Namespace zuerst an"). |
| **Latenz & Speed (Infrastruktur)** | **Flat-File Direct Read (API Bypass)** | Wenn der MCP-Server Dateisystem-Zugriff hat, liest er die `.txt`-Dateien der Seiten direkt aus, statt den langsameren HTTP/XML-RPC-Overhead der DokuWiki-API zu nutzen. Extrem niedrige Komplexität, massiver Speed-Boost. |
| | **Local ETag / Hash Caching** | Der MCP speichert MD5-Hashes zuletzt gelesener Seiten. Fordert das LLM eine Seite erneut an, prüft der Server den Hash. Ist er identisch, sendet der MCP nur ein `[USE_CONTEXT]` Token zurück (spart Bandbreite, Token und Verarbeitungszeit). |
| | **Speculative Pre-Fetching** | Während das LLM "denkt", lädt der MCP in einem Hintergrund-Thread (asynchron) bereits die direkt verlinkten Nachbar-Seiten der aktuell betrachteten Seite in einen lokalen In-Memory-Cache. |
| | **In-Memory SQLite Indexing** | Statt schwergewichtiger Vektordatenbanken wird der Namespace-Baum und einfache Metadaten beim Start in eine lokale SQLite-Datenbank (im RAM) geladen, um Namespace-Traversals in Millisekunden aufzulösen. |
| **Input-Kompression (Low Complexity)**<br>*(MCP ➔ LLM)* | **Regex-based Outline Generation** | Statt NLP-Modelle zur Zusammenfassung zu nutzen, extrahiert ein einfacher lokaler Regex nur Zeilen mit `====== Überschrift ======` und sendet dem LLM einen extrem kompakten Strukturbaum der Seite. |
| | **Binary/Hex Truncation** | Ein starrer Filter-Mechanismus, der vor der Übergabe an das LLM typische Non-Text-Blobs (wie Base64-Strings in Plugins) lokal durch kurze Platzhalter (`[BIN_DATA_OMITTED]`) ersetzt. |
| | **Delta/Patch Responses** | Nach einer Schreib- oder Änderungsoperation sendet der MCP nicht die gesamte aktualisierte Seite zurück an das LLM, sondern nur eine kurze Bestätigung oder den exakten Diff der Änderung. |
| **Output-Optimierung (Robustheit)**<br>*(LLM ➔ MCP)* | **Enum-Bound Parameters** | In Pydantic werden bekannte, statische Namespaces oder Tags nicht als freier String (`str`), sondern als striktes `Enum` definiert. Das LLM kann so systemseitig keine nicht-existenten Bereiche halluzinieren. |
| | **Compound Action Chaining** | Das JSON-Schema erlaubt dem LLM, eine Liste von Operationen (List-Merging) in einem einzigen Tool-Call zu übergeben (z. B. `[{"action": "create"}, {"action": "link"}]`). Reduziert teure Roundtrips massiv. |
| | **Format Forcing (Auto-Correction)** | Das LLM nutzt versehentlich Standard-Markdown (`**text**` statt `//text//`). Statt einen Validierungsfehler zum LLM zurückzuwerfen, normalisiert der Server harmlose Syntax-Patzer via Regex stumm im Hintergrund. |
| **Stabilität & System-Sicherheit** | **Schema-Enforced Sandboxing** | Schreib-Tools führen standardmäßig einen lokalen Dry-Run aus (`dry_run=True`), es sei denn, das LLM übergibt explizit ein definiertes `intent="commit"` Flag im Payload. |
| | **Circuit Breaker Pattern** | Um Endlosschleifen des LLMs (z. B. ständiges Aufrufen einer fehlenden Seite) zu verhindern, blockiert der MCP nach 3 identischen Aufrufen das Tool temporär und zwingt das LLM über einen System-Prompt zu einer neuen Strategie. |
| | **Lock-State Awareness** | Der MCP prüft lokal die `.lock`-Files von DokuWiki, bevor er einen Schreib-Prompt an das LLM freigibt, um zu verhindern, dass das LLM Tokens für das Generieren eines Textes verschwendet, der aufgrund eines gelockten Files nicht gespeichert werden kann. |