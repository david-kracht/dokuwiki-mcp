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