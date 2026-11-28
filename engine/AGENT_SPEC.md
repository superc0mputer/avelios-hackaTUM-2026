# AGENT_SPEC.md — KI-Schauspieler für OSCE-Anamnese-Training (Medizinstudium)

## 1. Projektkontext & Zielsetzung
Wir entwickeln eine Trainings-App für Medizinstudierende, in der ein LLM die Rolle einer Simulationsperson (Schauspieler) bei Anamnese- und Kommunikationsgesprächen übernimmt.

### Team- & Modulaufteilung
- **Modul 1 (Kollegin):** Web-Oberfläche / Konfigurations-Page, über die Dozenten Fälle, Charakterverhalten, Informationsfreigabe und Lernziele konfigurieren können.
- **Modul 2 (Aktueller Fokus):** Prompt-Engine für realistisches Acting, Information-Gating, OpenAI-Anbindung und interaktiver CLI-Testrunner.
- **Schnittstellenvertrag:** Ein gemeinsames Pydantic-/JSON-Schema (`PatientConfig`). Modul 2 arbeitet zunächst mit Mock-JSON-Dateien (`data/mock_*.json`). Sobald Modul 1 fertig ist, wird das erzeugte JSON direkt an `PatientConfig.model_validate(...)` übergeben, ohne dass Modul 2 umgebaut werden muss.

---

## 2. Ablauf realer Schauspiel-Trainings (Domänen-Referenz)
Reale Trainings mit Simulationspersonen (Schauspielern oder geschulten Laien) laufen typischerweise in vier Phasen ab:
1. **Briefing & Rollenstudium:** Rolle erhält medizinische Fakten sowie emotionale/psychosoziale Vorgeschichte (z. B. ängstlich, abwehrend, weitschweifig) und trainiert standardisiertes Preisgeben von Infos je nach Frageform (offen vs. geschlossen).
2. **Vorbereitung des Studierenden (1–2 Min.):** Kurzinfo vor dem Raum (Alter, Setting, Leitsymptom, Ziel, Zeitlimit).
3. **Simulation / Gespräch (ca. 8–15 Min.):** Anamnese, Gesprächsführung, Empathie, verständliche Sprache, Umgang mit Emotionen und schwierigen Situationen (z. B. schlechte Nachrichten, Angehörige, unkooperative Patienten).
4. **Strukturiertes Debriefing:** Eigenreflexion des Studierenden, Feedback aus Rollen-/Patientenperspektive und fachliches/kommunikatives Feedback durch den Dozenten.

---

## 3. Dozenten-Konfigurations-Page (Anforderungen an Modul 1 — Referenz für das Schema)
Auf der Konfigurations-Page sollte der Dozent einstellen können:
- **Basis- & Falldaten:** Szenario-Typ (Erstanamnese, Überbringen schlechter Nachrichten, Aufklärung, Angehörigengespräch), sichtbares Briefing (Alter, Geschlecht, Setting, Leitsymptom, Zeitlimit) sowie versteckte medizinische Fakten (Hauptdiagnose falls festgelegt, Symptomverlauf, Vorerkrankungen, Medikamente, Allergien, Noxen, Familienanamnese).
- **Persönlichkeit, Emotion & Gesprächsverhalten:** Grundstimmung/Persona, Kommunikationsstil (Alltagssprache vs. Halbwissen, Redefluss, Umgang mit Fachbegriffen), dynamische Trigger bzw. Eskalations-/Deeskalationsregeln (z. B. Stimmungsumschwung bei vielen geschlossenen Fragen oder Öffnung bei Empathie).
- **Informations-Freigabe (Anti-Spoiler-Regeln):** Was spontan erzählt wird, was nur auf gezielte Nachfrage kommt und was an Bedingungen geknüpft ist (z. B. Empathie / Vertrauensaufbau).
- **Lernziele & Feedback:** Must-Ask-Punkte / Red Flags, Fokusbereiche (offene Fragen, Struktur, Empathie, Jargonvermeidung) sowie Feedback-Ausrichtung nach dem Gespräch.

---

## 4. Kernanforderungen an das Acting der KI (System-Prompt & Verhalten)
1. **Strikte Rollenidentität (Kein KI-Assistent):**
   - Das LLM ist ausschließlich der Patient oder Angehörige in der beschriebenen Situation.
   - Kein KI-Assistent, kein Tutor, keine Meta-Kommentare (z. B. *„Als Patient fühle ich mich...“*, *„Gerne helfe ich Ihnen...“*, *„Das ist eine gute Frage...“*).
   - Bleibt auch bei Jailbreaks, Meta-Prompts oder Fragen nach der Diagnose strikt in der Rolle.
2. **Realistische Mündlichkeit:**
   - 1 bis maximal 3 kurze, natürlich gesprochene Sätze pro Antwort.
   - Keine Aufzählungslisten oder Bullet Points im Gespräch.
   - Natürliche Pausen (`...`), gelegentliche Füllwörter und realistische Ungenauigkeiten (z. B. vage Zeiten oder ungenaue Tablettenbeschreibungen).
3. **Information-Gating (Anti-Info-Dumping):**
   - Maximal **ein neuer Aspekt** pro Antwort; niemals alle Symptome und Hintergründe auf einmal auskippen.
   - **Tier 1 (`spontaneous`):** Einstiegssymptome / spontane Äußerungen auf offene Einstiegsfragen.
   - **Tier 2 (`on_specific_query`):** Details (Schmerzcharakter, Ausstrahlung, Vorerkrankungen, Medikamente, Noxen) nur auf konkrete Nachfrage.
   - **Tier 3 (`gated_secrets`):** Sensible/emotionale Hintergründe (z. B. Angst, Scham, familiäre Todesfälle) erst bei erfüllter `unlock_condition` (z. B. Empathie, Validierung, gezieltes Nachfragen).
   - **Unknowns (`unknowns`):** Details, die die Figur nicht weiß oder nicht genau erinnert, unvollständig/vage beantworten oder Unwissen angeben.
4. **Fachbegriff-Inversion:**
   - Nutzt der Studierende medizinische Fachbegriffe (z. B. *Synkope*, *Dyspnoe*, *Thoraxschmerz*, *Angina Pectoris*, *Hypertonie*, *KHK*), reagiert die Rolle als Laie mit Unverständnis, Rückfrage oder Unsicherheit statt medizinisch korrekt zu antworten.
5. **Architektur-Tipp für später:**
   - Rollen-Simulation und spätere Feedback-/Bewertungslogik sauber trennen, damit die Figur im Gespräch authentisch bleibt und das Feedback zielgerichtet gegen Lernziele auswerten kann.

---

## 5. Datenvertrag (`src/models.py`)

```python
from pydantic import BaseModel, Field


class Demographics(BaseModel):
    name: str
    age: int
    gender: str
    profession: str
    setting: str
    chief_complaint: str


class AffectProfile(BaseModel):
    baseline_mood: str
    speaking_style: str
    escalation_rules: list[str] = Field(default_factory=list)
    deescalation_rules: list[str] = Field(default_factory=list)


class InformationTiers(BaseModel):
    spontaneous: list[str]
    on_specific_query: list[str]
    gated_secrets: list[str]
    unlock_condition: str
    unknowns: list[str]


class PatientConfig(BaseModel):
    case_id: str
    scenario_type: str = "Erstanamnese"
    demographics: Demographics
    affect: AffectProfile
    information: InformationTiers
    forbidden_jargon_reactions: list[str] = Field(
        default_factory=lambda: [
            "Synkope",
            "Dyspnoe",
            "Thoraxschmerz",
            "Angina Pectoris",
            "Hypertonie",
            "KHK",
        ]
    )
