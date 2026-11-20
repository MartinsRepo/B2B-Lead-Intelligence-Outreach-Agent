# GDPR / DSGVO Privacy & Transparency Information (Art. 13 & Art. 14 GDPR)

> **Document Purpose:** Mandatory pre-production data protection & transparency notice (*Datenschutzinformationen nach Art. 13 und Art. 14 DSGVO*) for the **B2B Lead Intelligence & Outreach Agent**.

---

## 1. Overview & Architectural Privacy-by-Design Principles (Art. 25 GDPR)

The **B2B Lead Intelligence & Outreach Agent** is engineered specifically for **corporate entity intelligence** (B2B company news, press releases, technology stack headers/assets, and aggregated engineering hiring needs). In accordance with **Art. 5(1)(c) GDPR (Data Minimization)** and **Art. 25 GDPR (Data Protection by Design and by Default)**, the system implements five technical safeguards prior to production operation:

1. **Automated Personal Data (PII) Filtering (`src/lead_agent/privacy.py`):**
   - **DOM-Level Stripping (`strip_personal_dom_elements`):** Removes `<author>`, `<address>`, `.author`, `.byline`, `.vcard`, `.team-member`, `.recruiter`, `.contact-person`, `.press-contact`, and author `<meta>` tags from HTML pages before text extraction.
   - **Schema-Level Filtering:** Explicitly ignores JSON-LD `@type: "Person"` objects during structured data extraction (`src/lead_agent/tools/research_engine.py`).
   - **Regex PII Redaction (`scrub_personal_data`):** Automatically scrubs email addresses (`[REDACTED_EMAIL]`), telephone/mobile/fax numbers (`[REDACTED_PHONE]`), personal LinkedIn profile URLs (`linkedin.com/in/...` → `[REDACTED_PERSONAL_PROFILE]`), HR/press contact names (`[REDACTED_CONTACT_PERSON]`), and honorific person names (`[REDACTED_PERSON_NAME]`) before any text is sent to an LLM or stored in a `LeadReport`.
   - **Input Guardrail Block on Personal Profiles (`is_personal_profile_url`):** Rejects individual person profile URLs (`linkedin.com/in/...`, `linkedin.com/pub/...`) at the input guardrail while allowing corporate pages.
2. **Data Minimization on Careers & Corporate Pages (`minimize_corporate_text`):**
   - Extracts only job titles and technical skill keywords (`MAX_CAREERS_EXCERPT_CHARS = 600`) from `/careers` and `/jobs` pages while stripping recruiter contact details and application portals.
3. **Storage Limitation, TTL & Automated Deletion (`compute_retention_timestamps`, `is_timestamp_expired`):**
   - No persistent database of scraped pages is kept by default. Every generated `LeadReport` is stamped with `created_at_utc` and an automatic expiration timestamp `expires_at_utc` (default TTL: `3600` seconds / `60` minutes, configurable from 5 to 1440 minutes). Expired reports are automatically purged from the session state, and users can trigger an immediate **Art. 17 GDPR Erase** via the UI sidebar.
4. **Right to Object & Domain Blocklist (`OptOutBlocklistManager`, Art. 21 GDPR):**
   - Supports domain-level and subdomain-level opt-out blocklisting via the `GDPR_OPT_OUT_DOMAINS` environment variable, optional JSON file persistence, and the Streamlit UI Control Plane. Any opted-out domain is immediately blocked at the Input Guardrail, Web Scraper, Research Engine, and Session Renderer.
5. **Art. 13 / Art. 14 GDPR Transparency Notice (`get_art14_outreach_footer`):**
   - Every generated `OutreachPitch` includes an automated Art. 14 GDPR transparency and Art. 21 opt-out notice in `report.outreach.art14_transparency_notice`.

---

## 2. English Privacy Notice (Articles 13 & 14 GDPR)

### 2.1 Controller & Contact Details (Art. 13(1)(a)-(b), Art. 14(1)(a)-(b) GDPR)
- **Controller:** `[Insert Operating Company Legal Name, Address, Email, Phone]`
- **Data Protection Officer (DPO):** `[Insert DPO Name / Contact Email, e.g., privacy@your-company.example]`

### 2.2 Purposes and Legal Basis of Processing (Art. 13(1)(c)-(d), Art. 14(1)(c), Art. 14(2)(b) GDPR)
- **Purpose:** Automated analysis of publicly accessible corporate websites, press releases, technology headers/assets, and aggregated job postings to understand a target company's strategic technology needs and prepare relevant B2B corporate outreach.
- **Legal Basis:** **Art. 6(1)(f) GDPR (Legitimate Interests)**. Our legitimate interest lies in conducting informed, relevant B2B business development and corporate communications while strictly excluding natural persons' private profiles and scrubbing incidental personal identifiers (PII) prior to language model processing.

### 2.3 Categories of Data & Source of Data (Art. 14(1)(d), Art. 14(2)(f) GDPR)
- **Processed Categories:** Public corporate metadata (company name, domain, industry, public press release headlines, HTTP server/asset technology fingerprints, and open engineering role titles).
- **Excluded / Redacted Categories:** Natural persons' names, direct email addresses, phone numbers, author bylines, and personal social media profiles are automatically filtered out at ingestion.
- **Source of Data:** Publicly accessible corporate web pages (`https://<target-domain>`), official corporate RSS/Atom feeds, and public press wire feeds.

### 2.4 Recipients & Sub-Processors (Art. 13(1)(e)-(f), Art. 14(1)(e)-(f) GDPR)
- Sanitized, PII-scrubbed corporate text snippets are transmitted to **OpenAI (OpenAI Ireland Ltd. / OpenAI, L.L.C.)** via the OpenAI API solely for temporary inference and structured JSON synthesis under an enterprise Data Processing Addendum (DPA) and EU Standard Contractual Clauses (SCCs) where applicable, with API zero-data-retention / no-training controls enabled.

### 2.5 Retention & Deletion Periods (Art. 13(2)(a), Art. 14(2)(a), Art. 5(1)(e) GDPR)
- **Transient Processing:** Raw HTML and HTTP responses are held strictly in volatile memory during the pipeline run (typically `<15` seconds) and discarded immediately after structured extraction.
- **Session Report TTL:** Generated `LeadReport` objects carry an automated expiration timestamp (`expires_at_utc`, default **60 minutes**) after which they are automatically purged from the active UI session.
- **Opt-Out Blocklist Retention:** Domains added to the **Art. 21 GDPR Opt-Out Blocklist** are retained strictly as normalized corporate domain strings (e.g., `example.com`) to ensure permanent compliance with the objection.

### 2.6 Data Subject Rights (Art. 13(2)(b)-(d), Art. 14(2)(c)-(e), Art. 15–21 GDPR)
Under the GDPR, affected parties have the right to:
- **Access (Art. 15 GDPR)**, **Rectification (Art. 16 GDPR)**, **Erasure / "Right to be Forgotten" (Art. 17 GDPR)**, and **Restriction of Processing (Art. 18 GDPR)**.
- **Right to Object (Art. 21 GDPR):** Any organization or individual may object to the processing of their domain or data at any time. Adding the domain to `GDPR_OPT_OUT_DOMAINS` or the UI blocklist immediately halts all future scraping and outreach generation and purges active session data.
- **Right to Lodge a Complaint (Art. 77 GDPR):** You have the right to lodge a complaint with a data protection supervisory authority (*Datenschutzaufsichtsbehörde*).

---

## 3. Deutsche Datenschutzinformationen nach Art. 13 und Art. 14 DSGVO

### 3.1 Verantwortlicher und Datenschutzbeauftragter (Art. 13 Abs. 1 lit. a, b / Art. 14 Abs. 1 lit. a, b DSGVO)
- **Verantwortlicher:** `[Firmenname, Anschrift, E-Mail, Telefonnummer des Betreibers eintragen]`
- **Datenschutzbeauftragter:** `[Name / Kontaktadresse, z. B. datenschutz@ihr-unternehmen.example]`

### 3.2 Zwecke und Rechtsgrundlage der Verarbeitung (Art. 13 Abs. 1 lit. c, d / Art. 14 Abs. 1 lit. c, Abs. 2 lit. b DSGVO)
- **Verarbeitungszweck:** Automatisierte Auswertung öffentlich zugänglicher Unternehmenswebseiten, Pressemitteilungen, technischer Header-/Script-Signale sowie aggregierter Stellenprofile zur Vorbereitung sachbezogener B2B-Geschäftsanbahnungen.
- **Rechtsgrundlage:** **Art. 6 Abs. 1 lit. f DSGVO (Berechtigtes Interesse)**. Unser berechtigtes Interesse besteht in der sachgerechten Vorbereitung von B2B-Unternehmenskontakten. Durch technische Vorfilterung (`src/lead_agent/privacy.py`) werden personenbezogene Daten (Namen, E-Mail-Adressen, Telefonnummern, persönliche Profile) bereits vor der KI-Verarbeitung automatisiert entfernt (*Privacy by Design*, Art. 25 DSGVO).

### 3.3 Kategorien von Daten und Datenquellen (Art. 14 Abs. 1 lit. d, Abs. 2 lit. f DSGVO)
- **Datenquellen:** Öffentlich abrufbare Unternehmenswebseiten, offizielle Unternehmens-Newsrooms/RSS-Feeds und öffentliche Pressemeldungen.
- **Datensparsamkeit:** Personenbezogene Kontaktdaten von Mitarbeitenden, Recruitern oder Autoren werden durch DOM-Filter (`<author>`, `<address>`, `.recruiter`, `.contact-person`) und reguläre Ausdrücke (`[REDACTED_EMAIL]`, `[REDACTED_PHONE]`, `[REDACTED_CONTACT_PERSON]`) vor der Weiterverarbeitung herausgefiltert.

### 3.4 Speicherbegrenzung, Lösch- und Aufbewahrungsfristen (Art. 5 Abs. 1 lit. e, Art. 13/14 Abs. 2 lit. a DSGVO)
- **Flüchtige Verarbeitung:** Abgerufene Webseiteninhalte werden ausschließlich im Arbeitsspeicher während des Analyselaufs verarbeitet und nicht dauerhaft gespeichert.
- **Automatische Löschfrist (TTL):** Jeder erzeugte `LeadReport` erhält einen verbindlichen Ablaufzeitstempel (`expires_at_utc`, Standard: **60 Minuten**). Nach Ablauf dieser Frist oder bei Betätigung der Schaltfläche **„Immediate Art. 17 GDPR Erase“** werden die Sitzungsdaten vollständig gelöscht.

### 3.5 Widerspruchsrecht nach Art. 21 DSGVO & Sperrlistenmechanismus
- Gegen die Verarbeitung kann jederzeit formfrei Widerspruch eingelegt werden (Art. 21 DSGVO).
- Die betreffende Domain wird in die technische Sperrliste (`OptOutBlocklistManager` / `GDPR_OPT_OUT_DOMAINS`) aufgenommen, wodurch sämtliche künftigen Abrufe, Analysen und Kontaktentwürfe für diese Domain und ihre Subdomains technisch blockiert werden.

### 3.6 Muster-Transparenzhinweis für die B2B-Erstansprache (Art. 14 Abs. 3 lit. b DSGVO)
> *„Datenschutzhinweis nach Art. 14 DSGVO: Der fachliche Kontext dieser Nachricht basiert ausschließlich auf öffentlich zugänglichen Unternehmensinformationen Ihrer Organisation (keine Verarbeitung personenbezogener Profile). Sie können einer künftigen Kontaktaufnahme jederzeit nach Art. 21 DSGVO widersprechen; Ihre Unternehmensdomain wird dann dauerhaft auf unsere Sperrliste gesetzt.“*
