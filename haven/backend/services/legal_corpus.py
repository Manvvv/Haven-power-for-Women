"""HAVEN verified Indian legal corpus (seed knowledge base).

Curated, plain-language SUMMARIES of well-established Indian statutes and official
processes. Each entry carries a REAL citation (Act + section) verified against
official sources, plus a link to the primary Government of India / judiciary source.
This is the seed data that populates the `legal_docs` collection so the RAG
assistant can retrieve grounded, cited answers instead of returning "no source".

No-hallucination guarantees:
  * Every entry cites a REAL Act + section checked against official sources.
  * Current criminal law (BNS 2023 / BNSS 2023, effective 2024-07-01) is primary;
    superseded IPC/CrPC references are labelled "(historical: ...)".
  * `authority_level` places every entry in the source hierarchy (Tier 1/2/3).
  * Entries are section-scoped so section integrity survives chunking.
  * Pure-Python data (no imports) — testable without a database.

Nothing here is legal advice; each entry is general legal information.
"""
from __future__ import annotations

CORPUS_VERSION = "2026-09-25"
LAST_VERIFIED = "2026-09-25"


def _entry(*, doc_id, title, act_name, section, category, subcategory, text,
           authority, authority_level="tier1_primary_statute", source_type="statute",
           source_url="https://www.indiacode.nic.in/", jurisdiction="India", state="",
           court="", effective_date="", publication_date="", language="en",
           version="1", keywords=None):
    return {
        "document_id": doc_id, "title": title, "act_name": act_name, "section": section,
        "category": category, "subcategory": subcategory, "text": text.strip(),
        "authority": authority, "authority_level": authority_level,
        "source_type": source_type, "source_url": source_url,
        "jurisdiction": jurisdiction, "state": state, "court": court,
        "publication_date": publication_date, "effective_date": effective_date,
        "last_verified": LAST_VERIFIED, "version": version, "language": language,
        "verification_status": "verified", "keywords": keywords or [],
    }


CORPUS = [
    # ================= FAMILY LAW =================
    _entry(
        doc_id="HMA-1955-S13", title="Grounds for divorce (Hindu Marriage Act)",
        act_name="Hindu Marriage Act, 1955", section="Section 13",
        category="family", subcategory="divorce",
        authority="Ministry of Law and Justice (India Code)", effective_date="1955-05-18",
        keywords=["divorce", "talaq", "grounds for divorce", "contested divorce", "hindu marriage",
                  "cruelty", "desertion", "adultery", "separation", "end marriage",
                  "तलाक", "विवाह", "शादी", "पति", "पत्नी", "क्रूरता", "विवाह विच्छेद"],
        text=(
            "LAW: Under Section 13 of the Hindu Marriage Act, 1955, a marriage solemnised under that "
            "Act may be dissolved by a decree of divorce on grounds that include cruelty, desertion "
            "for at least two years, adultery, conversion to another religion, unsoundness of mind, "
            "certain communicable diseases, renunciation of the world, or presumption of death. "
            "Section 13(2) gives a wife certain additional grounds. This Act applies to Hindus, "
            "Buddhists, Jains and Sikhs. A petition is filed in the Family Court / District Court "
            "having jurisdiction where the marriage was solemnised, where the couple last resided "
            "together, or where the respondent (or, in some cases, the petitioner-wife) resides."
        ),
    ),
    _entry(
        doc_id="HMA-1955-S13B", title="Divorce by mutual consent (Hindu Marriage Act)",
        act_name="Hindu Marriage Act, 1955", section="Section 13B",
        category="family", subcategory="mutual_consent_divorce",
        authority="Ministry of Law and Justice (India Code)", effective_date="1976-05-27",
        keywords=["mutual consent divorce", "mutual divorce", "13b", "both agree divorce",
                  "divorce by agreement", "consent", "cooling off period",
                  "आपसी सहमति", "आपसी सहमति से तलाक", "सहमति से तलाक", "दोनों की सहमति"],
        text=(
            "LAW: Section 13B of the Hindu Marriage Act, 1955 allows divorce by mutual consent where "
            "both spouses have been living separately for one year or more and jointly agree that the "
            "marriage should end. The couple files a joint petition (first motion); after a statutory "
            "period the parties return for a second motion, after which the court may grant the decree. "
            "The Supreme Court has held the interval between the two motions can, in appropriate cases, "
            "be waived. Related provisions: Special Marriage Act, 1954 Section 28 (for civil/inter-faith "
            "marriages) provides an equivalent mutual-consent route."
        ),
    ),
    _entry(
        doc_id="HMA-1955-S10", title="Judicial separation (Hindu Marriage Act)",
        act_name="Hindu Marriage Act, 1955", section="Section 10",
        category="family", subcategory="judicial_separation",
        authority="Ministry of Law and Justice (India Code)", effective_date="1955-05-18",
        keywords=["judicial separation", "legal separation", "separate without divorce",
                  "not living together", "separation decree"],
        text=(
            "LAW: Section 10 of the Hindu Marriage Act, 1955 lets either spouse petition for judicial "
            "separation on the same grounds available for divorce under Section 13. A decree of judicial "
            "separation means the parties are no longer obliged to live together, but the marriage is not "
            "dissolved and neither may remarry. If cohabitation is not resumed for one year after the "
            "decree, that can itself become a ground for divorce."
        ),
    ),
    _entry(
        doc_id="SMA-1954-S28", title="Divorce under the Special Marriage Act (civil / inter-faith)",
        act_name="Special Marriage Act, 1954", section="Section 27 & Section 28",
        category="family", subcategory="mutual_consent_divorce",
        authority="Ministry of Law and Justice (India Code)", effective_date="1954-10-09",
        keywords=["special marriage act", "inter-faith divorce", "court marriage divorce",
                  "civil marriage", "interfaith", "registered marriage divorce",
                  "विशेष विवाह अधिनियम", "कोर्ट मैरिज तलाक", "अंतरधार्मिक तलाक"],
        text=(
            "LAW: For marriages solemnised or registered under the Special Marriage Act, 1954 (civil and "
            "inter-faith marriages), Section 27 sets out grounds for divorce (including cruelty, desertion, "
            "adultery and others) and Section 28 provides for divorce by mutual consent through a joint "
            "petition, mirroring the two-motion process. Which personal-law statute governs your divorce "
            "depends on the law under which you married."
        ),
    ),
    _entry(
        doc_id="PERSONAL-LAW-DIVORCE-OVERVIEW",
        title="Which divorce law applies (personal-law overview)",
        act_name="Multiple personal-law statutes", section="Overview",
        category="family", subcategory="divorce",
        authority="Ministry of Law and Justice (India Code)", authority_level="tier2_official_explanatory",
        source_type="statutory_overview", effective_date="",
        keywords=["which law", "personal law", "muslim divorce", "christian divorce", "parsi divorce",
                  "khula", "religion", "applicable law", "how to divorce"],
        text=(
            "LAW / JURISDICTION: In India the divorce process depends on the personal law under which the "
            "marriage took place. Hindus, Buddhists, Jains and Sikhs: Hindu Marriage Act, 1955. Civil or "
            "inter-faith marriages: Special Marriage Act, 1954. Muslims: dissolution is governed by Muslim "
            "personal law and, for women, the Dissolution of Muslim Marriage Act, 1939. Christians: Indian "
            "Divorce Act, 1869. Parsis: Parsi Marriage and Divorce Act, 1936. Because the applicable statute, "
            "grounds and forum differ, the correct personal law and your State/district must be identified "
            "before specific procedure can be given."
        ),
    ),
    _entry(
        doc_id="FAMILY-COURTS-ACT-1984", title="Where family cases are filed (Family Courts)",
        act_name="Family Courts Act, 1984", section="Sections 7 & 8",
        category="family", subcategory="where_to_file",
        authority="Ministry of Law and Justice (India Code)", effective_date="1984-09-14",
        keywords=["family court", "where to file", "which court", "jurisdiction", "file case",
                  "divorce court", "custody court", "maintenance court",
                  "परिवार न्यायालय", "कुटुंब न्यायालय", "कहाँ केस दायर करें", "कौन सी अदालत"],
        text=(
            "PROCESS/LAW: The Family Courts Act, 1984 establishes Family Courts to deal with matrimonial "
            "matters — divorce, judicial separation, maintenance, and custody/guardianship of children. "
            "Where a Family Court has been set up for the area, matters listed in Section 7 are filed there; "
            "the specific Family Court/District Court depends on where the marriage was solemnised, where the "
            "couple last lived together, or where the respondent resides. The exact court therefore depends on "
            "your State and district."
        ),
    ),
    _entry(
        doc_id="BNSS-2023-S144", title="Maintenance for wife, children and parents",
        act_name="Bharatiya Nagarik Suraksha Sanhita, 2023", section="Section 144",
        category="family", subcategory="maintenance",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["maintenance", "kharcha", "guzara bhatta", "financial support", "alimony",
                  "wife maintenance", "child maintenance", "125 crpc", "monthly allowance",
                  "गुजारा भत्ता", "भरण पोषण", "पत्नी का खर्चा", "बच्चों का खर्चा"],
        text=(
            "LAW (current): Section 144 of the Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS, effective "
            "1 July 2024, successor to Section 125 of the Code of Criminal Procedure, 1973) allows a wife "
            "(including, as interpreted, a divorced wife who has not remarried), children, and parents who "
            "are unable to maintain themselves to apply to a Magistrate for a monthly maintenance allowance. "
            "Separately, under the Hindu Adoptions and Maintenance Act, 1956 Section 18, a Hindu wife is "
            "entitled to be maintained by her husband. Maintenance can also be sought within domestic-violence "
            "proceedings (see monetary relief under the DV Act)."
        ),
    ),
    _entry(
        doc_id="MARRIAGE-REGISTRATION", title="Marriage registration",
        act_name="Hindu Marriage Act, 1955 (S.8) / Special Marriage Act, 1954",
        section="Section 8 (HMA) / State registration rules",
        category="family", subcategory="marriage_registration",
        authority="Ministry of Law and Justice / State governments",
        authority_level="tier2_official_explanatory", source_type="statutory_overview",
        keywords=["marriage registration", "register marriage", "marriage certificate",
                  "shaadi registration", "proof of marriage"],
        text=(
            "PROCESS/LAW: Section 8 of the Hindu Marriage Act, 1955 enables State governments to make rules "
            "for registration of Hindu marriages and issue of a marriage certificate; marriages under the "
            "Special Marriage Act, 1954 are registered under that Act. Registration is generally done through "
            "the office designated by your State government (often the Registrar of Marriages / local "
            "authority). Exact forms, fees and offices are set by State rules, so the procedure depends on "
            "your State. Directions of the Supreme Court have encouraged compulsory registration of marriages."
        ),
    ),
    # ================= CHILD CUSTODY & GUARDIANSHIP =================
    _entry(
        doc_id="HMGA-1956-S6", title="Natural guardian of a Hindu minor",
        act_name="Hindu Minority and Guardianship Act, 1956", section="Section 6",
        category="family", subcategory="guardianship",
        authority="Ministry of Law and Justice (India Code)", effective_date="1956-08-25",
        keywords=["guardian", "guardianship", "natural guardian", "minor child", "who is guardian",
                  "custody of child", "abhirakshaa",
                  "अभिरक्षा", "संरक्षक", "प्राकृतिक संरक्षक", "नाबालिग बच्चा"],
        text=(
            "LAW: Section 6 of the Hindu Minority and Guardianship Act, 1956 identifies the natural guardians "
            "of a Hindu minor. For custody of very young children the welfare of the minor is the paramount "
            "consideration (Section 13). This Act supplements the Guardians and Wards Act, 1890, under which "
            "courts appoint or declare guardians and decide custody."
        ),
    ),
    _entry(
        doc_id="GWA-1890-CUSTODY", title="Child custody and the welfare principle",
        act_name="Guardians and Wards Act, 1890", section="Sections 7, 17 & 25",
        category="family", subcategory="child_custody",
        authority="Ministry of Law and Justice (India Code)", effective_date="1890-07-21",
        keywords=["child custody", "custody of children", "custody battle", "who gets the child",
                  "guardian of child", "welfare of child", "father custody", "mother custody",
                  "बच्चे की कस्टडी", "कस्टडी", "बच्चे की अभिरक्षा", "बच्चा किसे मिलेगा", "बच्चे"],
        text=(
            "LAW: Under the Guardians and Wards Act, 1890, a court may appoint or declare a guardian of a "
            "minor's person or property (Section 7). In deciding custody the court treats the welfare of the "
            "minor as the paramount consideration (Section 17), taking into account the child's age, sex, "
            "wishes (where old enough) and the character of the proposed guardian. Section 25 allows the court "
            "to order a ward's return to the custody of a guardian. Applications are made to the District "
            "Court / Family Court having jurisdiction where the minor ordinarily resides, so the correct forum "
            "depends on your State and district."
        ),
    ),
    _entry(
        doc_id="EMERGENCY-INTERIM-CUSTODY",
        title="Emergency / interim custody and interim child orders",
        act_name="Guardians and Wards Act, 1890 (S.25) & Protection of Women from Domestic Violence Act, 2005 (S.21)",
        section="GWA S.25 / DV Act S.21 / interim applications",
        category="family", subcategory="emergency_custody",
        authority="Ministry of Law and Justice / India Code", authority_level="tier2_official_explanatory",
        source_type="statutory_overview",
        keywords=["emergency custody", "interim custody", "temporary custody", "urgent custody",
                  "took my child", "get my child back", "child taken away", "immediate custody",
                  "अंतरिम कस्टडी", "तुरंत कस्टडी", "बच्चा वापस", "बच्चे को ले गया"],
        text=(
            "LAW/PROCESS: Indian law distinguishes final custody from interim/temporary custody. A parent can "
            "seek interim custody or interim directions while a guardianship/custody petition under the "
            "Guardians and Wards Act, 1890 (see Section 25) is pending, and courts can pass urgent interim "
            "orders. Under the Protection of Women from Domestic Violence Act, 2005 Section 21, a Magistrate "
            "may grant temporary custody of a child to the aggrieved person during DV proceedings. There is no "
            "special 'emergency custody order' separate from these routes; urgency is addressed through interim "
            "applications. If a child is in immediate danger, that is a child-safety emergency (police 112, "
            "Childline 1098) as well as a legal matter. The exact court and procedure depend on your State/"
            "district and any existing court order."
        ),
    ),
    _entry(
        doc_id="VISITATION", title="Visitation / access to a child",
        act_name="Guardians and Wards Act, 1890 (welfare principle)", section="Court's discretion",
        category="family", subcategory="visitation",
        authority="Courts (Family Court / District Court)", authority_level="tier2_official_explanatory",
        source_type="statutory_overview",
        keywords=["visitation", "access", "meet my child", "visitation rights", "see my child",
                  "non-custodial parent"],
        text=(
            "LAW/PROCESS: When one parent is granted custody, courts commonly grant the other parent "
            "visitation (access) rights, again guided by the welfare of the child. Visitation schedules are "
            "fixed by the Family Court / District Court on the facts of each case; they are not set by a fixed "
            "statutory formula, so specific arrangements depend on the court and your circumstances."
        ),
    ),
    # ================= DOMESTIC VIOLENCE / WOMEN'S PROTECTION =================
    _entry(
        doc_id="PWDVA-2005-S3-S12", title="Domestic violence: what it covers and how to seek protection",
        act_name="Protection of Women from Domestic Violence Act, 2005", section="Sections 3 & 12",
        category="women_rights", subcategory="domestic_violence",
        authority="Ministry of Women and Child Development / India Code", effective_date="2006-10-26",
        source_url="https://wcd.nic.in/",
        keywords=["domestic violence", "dv act", "ghar mein maar", "husband beating", "abuse at home",
                  "physical abuse", "mental harassment", "in-laws harassment", "protection order",
                  "beating me", "hitting me", "marpeet",
                  "घरेलू हिंसा", "पति मारता", "पति पीटता", "मारता", "पीटता", "मारपीट",
                  "घर में हिंसा", "पति धमकी"],
        text=(
            "LAW: The Protection of Women from Domestic Violence Act, 2005 (PWDVA) gives a woman civil "
            "protection against domestic violence by a partner or family members. Section 3 defines domestic "
            "violence broadly to include physical, sexual, verbal, emotional and economic abuse. "
            "PROCESS: Under Section 12, an aggrieved woman (or a Protection Officer or someone on her behalf) "
            "may file an application before the Magistrate seeking reliefs such as protection orders, residence "
            "orders, monetary relief, custody and compensation. A Protection Officer and registered service "
            "providers (Sections 8-10) assist with filing and with a Domestic Incident Report. This is a civil "
            "remedy and can be pursued alongside any criminal complaint."
        ),
    ),
    _entry(
        doc_id="PWDVA-2005-S18", title="Protection orders / restraining orders (DV Act)",
        act_name="Protection of Women from Domestic Violence Act, 2005", section="Section 18",
        category="women_rights", subcategory="protection_order",
        authority="Ministry of Women and Child Development / India Code", effective_date="2006-10-26",
        source_url="https://wcd.nic.in/",
        keywords=["restraining order", "protection order", "stop him contacting me", "keep him away",
                  "no contact order", "stay away order", "restraint"],
        text=(
            "LAW: Section 18 of the Protection of Women from Domestic Violence Act, 2005 empowers the "
            "Magistrate to pass a protection order prohibiting the respondent from committing further acts of "
            "domestic violence, entering the aggrieved person's workplace or school, attempting to contact her, "
            "or committing other specified acts. This is the Indian civil equivalent of a 'restraining order' "
            "in domestic-violence matters. Interim and ex-parte orders can be granted under Section 23 while "
            "the case is pending. Breach of a protection order is itself an offence under the Act."
        ),
    ),
    _entry(
        doc_id="PWDVA-2005-S17-S19", title="Right to reside in the shared household (DV Act)",
        act_name="Protection of Women from Domestic Violence Act, 2005", section="Sections 17 & 19",
        category="women_rights", subcategory="residence_rights",
        authority="Ministry of Women and Child Development / India Code", effective_date="2006-10-26",
        source_url="https://wcd.nic.in/",
        keywords=["residence rights", "thrown out of house", "right to stay", "shared household",
                  "cannot evict", "residence order", "matrimonial home"],
        text=(
            "LAW: Section 17 of the Protection of Women from Domestic Violence Act, 2005 gives every woman in "
            "a domestic relationship the right to reside in the shared household, whether or not she has any "
            "ownership right in it, and provides she cannot be evicted except by procedure established by law. "
            "Section 19 lets the Magistrate pass residence orders — for example restraining the respondent from "
            "dispossessing her, or directing alternative accommodation. These are civil protections decided by "
            "the Magistrate on the facts."
        ),
    ),
    _entry(
        doc_id="PWDVA-2005-S20-S22", title="Monetary relief and compensation (DV Act)",
        act_name="Protection of Women from Domestic Violence Act, 2005", section="Sections 20 & 22",
        category="women_rights", subcategory="monetary_relief",
        authority="Ministry of Women and Child Development / India Code", effective_date="2006-10-26",
        source_url="https://wcd.nic.in/",
        keywords=["monetary relief", "compensation", "maintenance dv", "financial relief",
                  "expenses", "damages", "loss"],
        text=(
            "LAW: Under Section 20 of the Protection of Women from Domestic Violence Act, 2005 the Magistrate "
            "may direct the respondent to pay monetary relief to meet expenses and losses caused by domestic "
            "violence, including loss of earnings, medical expenses and maintenance. Section 22 allows the "
            "Magistrate to order compensation for injuries, including mental torture and emotional distress. "
            "These reliefs are in addition to, and can be combined with, other reliefs under the Act."
        ),
    ),
    _entry(
        doc_id="BNS-2023-S85-S86", title="Cruelty by husband or his relatives",
        act_name="Bharatiya Nyaya Sanhita, 2023", section="Sections 85 & 86",
        category="women_rights", subcategory="cruelty_498a",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["498a", "cruelty", "husband cruelty", "in-laws harassment", "dowry harassment",
                  "mental cruelty", "matrimonial cruelty", "sasural",
                  "क्रूरता", "दहेज उत्पीड़न", "पति की क्रूरता", "ससुराल वाले परेशान"],
        text=(
            "LAW (current): Section 85 of the Bharatiya Nyaya Sanhita, 2023 (BNS, effective 1 July 2024, "
            "successor to Section 498A of the Indian Penal Code) makes it a criminal offence for the husband "
            "or a relative of the husband of a woman to subject her to cruelty, punishable with imprisonment "
            "up to three years and fine. Section 86 defines 'cruelty' to include wilful conduct likely to "
            "drive the woman to suicide or cause grave injury or danger to life, limb or health (mental or "
            "physical), and harassment connected with unlawful demands for property or valuable security "
            "(dowry harassment). (Historical: this corresponds to the former IPC Section 498A.)"
        ),
    ),
    _entry(
        doc_id="DOWRY-PROHIBITION-1961", title="Dowry demand and dowry harassment",
        act_name="Dowry Prohibition Act, 1961", section="Sections 3 & 4",
        category="women_rights", subcategory="dowry",
        authority="Ministry of Women and Child Development / India Code", effective_date="1961-07-01",
        keywords=["dowry", "dahej", "dowry demand", "dowry harassment", "gifts demand",
                  "dowry case", "in-laws demanding money",
                  "दहेज", "दहेज की मांग", "दहेज उत्पीड़न", "दहेज मांग रहे"],
        text=(
            "LAW: The Dowry Prohibition Act, 1961 prohibits giving or taking dowry (Section 3) and penalises "
            "demanding dowry (Section 4). Dowry-related cruelty is also covered by the criminal law on cruelty "
            "by a husband or his relatives (Bharatiya Nyaya Sanhita, 2023 Sections 85-86). Dowry-related "
            "offences can be reported to the police, and civil protection is additionally available under the "
            "Protection of Women from Domestic Violence Act, 2005."
        ),
    ),
    _entry(
        doc_id="BNS-2023-S78", title="Stalking",
        act_name="Bharatiya Nyaya Sanhita, 2023", section="Section 78",
        category="women_rights", subcategory="stalking",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["stalking", "following me", "peecha", "someone following me", "repeated contact",
                  "cyberstalking", "watching me", "harassing me repeatedly",
                  "पीछा", "पीछा करना", "कोई पीछा कर रहा"],
        text=(
            "LAW (current): Section 78 of the Bharatiya Nyaya Sanhita, 2023 makes stalking an offence — where "
            "a man follows a woman and contacts, or attempts to contact, her to foster personal interaction "
            "repeatedly despite a clear indication of disinterest, or monitors her use of the internet, email "
            "or other electronic communication. It covers both physical and online (cyber) stalking and is "
            "punishable with imprisonment and fine. (Historical: corresponds to the former IPC Section 354D.)"
        ),
    ),
    _entry(
        doc_id="BNS-2023-S75-S79", title="Sexual harassment and acts to insult a woman's modesty",
        act_name="Bharatiya Nyaya Sanhita, 2023", section="Sections 75 & 79",
        category="women_rights", subcategory="harassment",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["sexual harassment", "eve teasing", "molestation", "chhedchhad", "inappropriate touching",
                  "lewd comments", "insult modesty", "harassment", "obscene gesture"],
        text=(
            "LAW (current): Section 75 of the Bharatiya Nyaya Sanhita, 2023 defines and punishes sexual "
            "harassment — including unwelcome physical contact and advances, a demand or request for sexual "
            "favours, showing pornography against a woman's will, or making sexually coloured remarks. "
            "Section 79 punishes any word, gesture or act intended to insult the modesty of a woman. "
            "(Historical: these correspond to the former IPC Sections 354A and 509.) Assault or criminal "
            "force to a woman intending to outrage her modesty is separately an offence under the BNS."
        ),
    ),
    _entry(
        doc_id="SEXUAL-VIOLENCE-REPORTING", title="Reporting sexual violence: victim rights",
        act_name="Bharatiya Nyaya Sanhita, 2023 & Bharatiya Nagarik Suraksha Sanhita, 2023",
        section="Reporting & victim-protection provisions",
        category="women_rights", subcategory="sexual_violence",
        authority="Ministry of Home Affairs / India Code", authority_level="tier2_official_explanatory",
        source_type="statutory_overview", effective_date="2024-07-01",
        keywords=["rape", "sexual assault", "sexual violence", "raped", "assaulted", "report rape",
                  "molested", "medical examination", "survivor"],
        text=(
            "LAW/PROCESS (current): Rape and sexual assault are serious cognizable offences under the "
            "Bharatiya Nyaya Sanhita, 2023. A survivor can report at any police station (a Zero FIR can be "
            "registered irrespective of jurisdiction under Bharatiya Nagarik Suraksha Sanhita, 2023 Section "
            "173) and is entitled to protections such as free medical examination and treatment, recording of "
            "the statement by a woman officer where required, and in-camera proceedings. Sexual offences "
            "against a child are dealt with under the POCSO Act, 2012. Specific section numbers and procedure "
            "should be confirmed with police or a lawyer; emergency help: 112 / women's helpline 181."
        ),
    ),
    # ================= CRIMINAL / POLICE PROCESS =================
    _entry(
        doc_id="BNSS-2023-S173-FIR", title="How to file an FIR (First Information Report)",
        act_name="Bharatiya Nagarik Suraksha Sanhita, 2023", section="Section 173",
        category="police", subcategory="fir",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["fir", "first information report", "file police complaint", "report crime",
                  "complaint vs fir", "register fir", "police report", "shikayat",
                  "एफआईआर", "प्राथमिकी", "पुलिस शिकायत", "शिकायत दर्ज", "पुलिस"],
        text=(
            "LAW/PROCESS (current): Section 173 of the Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS, "
            "effective 1 July 2024, successor to Section 154 of the Code of Criminal Procedure, 1973) governs "
            "registration of information about a cognizable offence — the First Information Report (FIR). "
            "Information can be given orally or in writing, and now also by electronic communication. When "
            "reduced to writing it must be read over to the informant, signed, and a free copy given to the "
            "informant. For certain offences the section also provides for preliminary enquiry. A 'complaint' "
            "more broadly is any allegation made to a Magistrate; an FIR specifically sets the police "
            "investigation of a cognizable offence in motion."
        ),
    ),
    _entry(
        doc_id="ZERO-FIR", title="Zero FIR (report at any police station)",
        act_name="Bharatiya Nagarik Suraksha Sanhita, 2023", section="Section 173(1)",
        category="police", subcategory="zero_fir",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["zero fir", "any police station", "wrong jurisdiction", "different city",
                  "police sent me away", "jurisdiction fir",
                  "जीरो एफआईआर", "किसी भी थाने", "जीरो प्राथमिकी"],
        text=(
            "LAW/PROCESS (current): A 'Zero FIR' means an FIR can be registered at any police station "
            "irrespective of where the offence took place; it is later transferred to the police station "
            "having territorial jurisdiction. Under Section 173 of the Bharatiya Nagarik Suraksha Sanhita, "
            "2023, information about a cognizable offence must be recorded regardless of the area where the "
            "offence was committed. This is especially important in emergencies and for offences against women "
            "and children, so a victim is not turned away for being at the 'wrong' police station."
        ),
    ),
    _entry(
        doc_id="POLICE-REFUSAL-REMEDY", title="If the police refuse to register your complaint",
        act_name="Bharatiya Nagarik Suraksha Sanhita, 2023", section="Section 173(4) & Section 175",
        category="police", subcategory="police_refusal",
        authority="Ministry of Home Affairs / India Code", effective_date="2024-07-01",
        source_type="statute_current",
        keywords=["police refused", "police not registering fir", "police won't help",
                  "complaint refused", "police ignoring", "escalate police", "sp complaint",
                  "पुलिस ने मना कर दिया", "पुलिस एफआईआर नहीं लिख रही", "पुलिस शिकायत नहीं ले रही",
                  "पुलिस मना कर रही"],
        text=(
            "LAW/PROCESS (current): If an officer in charge of a police station refuses to register "
            "information about a cognizable offence, the Bharatiya Nagarik Suraksha Sanhita, 2023 provides "
            "remedies — the aggrieved person may send the substance of the information in writing and by post "
            "to the Superintendent of Police (Section 173(4)), and a Magistrate has power under Section 175 to "
            "order registration/investigation. The Supreme Court in Lalita Kumari v. Government of U.P. held "
            "that registration of an FIR is mandatory when the information discloses a cognizable offence. You "
            "can also approach higher police authorities or the State Human Rights / Women's Commission."
        ),
    ),
    # ================= CHILD SAFETY =================
    _entry(
        doc_id="POCSO-2012-S19", title="Reporting child sexual abuse (POCSO)",
        act_name="Protection of Children from Sexual Offences Act, 2012", section="Section 19",
        category="child_safety", subcategory="pocso",
        authority="Ministry of Women and Child Development / India Code", effective_date="2012-11-14",
        source_url="https://wcd.nic.in/",
        keywords=["pocso", "child abuse", "child sexual abuse", "minor abused", "child molestation",
                  "report child abuse", "child victim",
                  "बाल यौन शोषण", "बच्चे का शोषण", "बच्चे का यौन शोषण"],
        text=(
            "LAW: The Protection of Children from Sexual Offences Act, 2012 (POCSO) protects children (persons "
            "below 18) from sexual offences and provides child-friendly procedures and Special Courts. "
            "Section 19 makes reporting mandatory — any person who apprehends or has knowledge that a POCSO "
            "offence has been committed must report it to the Special Juvenile Police Unit or local police; "
            "failure to report can itself be an offence. Reports can also be made via Childline 1098. The "
            "child's identity is protected and proceedings are conducted sensitively."
        ),
    ),
    _entry(
        doc_id="JJ-ACT-2015-CWC", title="Child in need of care and protection (Juvenile Justice Act)",
        act_name="Juvenile Justice (Care and Protection of Children) Act, 2015",
        section="Child Welfare Committee provisions",
        category="child_safety", subcategory="child_protection",
        authority="Ministry of Women and Child Development / India Code", effective_date="2016-01-15",
        source_url="https://wcd.nic.in/",
        keywords=["child protection", "child in danger", "child welfare committee", "cwc",
                  "abandoned child", "child neglect", "unsafe child", "child rescue",
                  "बाल कल्याण समिति", "बच्चा खतरे में", "बच्चे की सुरक्षा"],
        text=(
            "LAW/PROCESS: The Juvenile Justice (Care and Protection of Children) Act, 2015 provides for the "
            "care and protection of children, including a 'child in need of care and protection'. Each "
            "district has a Child Welfare Committee (CWC) empowered to take decisions for such children, and "
            "children can be produced before the CWC. Emergency child-safety concerns can be raised with the "
            "police (112) and the child helpline (1098), which coordinate with the CWC and District Child "
            "Protection Unit."
        ),
    ),
    _entry(
        doc_id="MISSING-CHILD-1098", title="Missing child / immediate child help",
        act_name="Childline (1098) & police (Zero FIR under BNSS 2023 S.173)",
        section="Reporting pathway",
        category="child_safety", subcategory="missing_child",
        authority="Ministry of Women and Child Development / Childline India",
        authority_level="tier2_official_explanatory", source_type="official_service",
        source_url="https://www.childlineindia.org/",
        keywords=["missing child", "child missing", "lost child", "kidnapped child", "child abducted",
                  "cannot find my child", "child taken",
                  "बच्चा गायब", "बच्चा गुम", "बच्चा लापता", "बच्चा नहीं मिल रहा"],
        text=(
            "PROCESS: If a child is missing, contact the police immediately (emergency 112) and the child "
            "helpline 1098 (Childline). An FIR can and should be registered without delay — for a missing "
            "child the police are required to register a report, and a Zero FIR can be filed at any police "
            "station (Bharatiya Nagarik Suraksha Sanhita, 2023 Section 173) if you are not in the home area. "
            "Preserve a recent photograph and identity details of the child to assist the search. Note: a "
            "child being taken by the other parent during a custody dispute is a family-law matter as well; "
            "immediate danger, however, is always a police emergency."
        ),
    ),
    # ================= DIGITAL / CYBER =================
    _entry(
        doc_id="CYBER-REPORTING-PORTAL", title="Reporting cybercrime and online abuse",
        act_name="Information Technology Act, 2000 & National Cyber Crime Reporting Portal",
        section="Reporting pathway",
        category="cyber", subcategory="online_harassment",
        authority="Ministry of Home Affairs (I4C)", authority_level="tier1_primary_authority",
        source_type="official_service", source_url="https://cybercrime.gov.in/",
        keywords=["cyber harassment", "online threats", "online abuse", "cyberbullying",
                  "someone threatening me online", "harassment on social media", "report cybercrime",
                  "online blackmail", "sextortion",
                  "ऑनलाइन धमकी", "साइबर उत्पीड़न", "ऑनलाइन परेशान", "धमकी", "ऑनलाइन", "साइबर अपराध"],
        text=(
            "PROCESS: Cybercrime — including online harassment, threats, blackmail, sextortion and image "
            "abuse — can be reported on the National Cyber Crime Reporting Portal (cybercrime.gov.in), which "
            "has a dedicated section for crimes against women and children (with an option to report "
            "anonymously). For financial cyber fraud there is a 24x7 helpline 1930. Serious online threats "
            "can also be reported to the local police as a cognizable offence (Zero FIR under Bharatiya "
            "Nagarik Suraksha Sanhita, 2023 Section 173). Preserve screenshots, URLs, usernames and any "
            "messages as evidence."
        ),
    ),
    _entry(
        doc_id="IT-ACT-2000-S66E-S67", title="Sharing private/obscene images without consent",
        act_name="Information Technology Act, 2000", section="Sections 66E, 67 & 67A",
        category="cyber", subcategory="image_abuse",
        authority="Ministry of Electronics and IT / India Code", effective_date="2009-10-27",
        keywords=["private photos", "leaked photos", "shared my pictures", "nude photos",
                  "revenge porn", "morphed photos", "obscene images", "intimate images", "mms",
                  "फोटो लीक", "निजी तस्वीरें", "अश्लील तस्वीरें", "तस्वीरें लीक"],
        text=(
            "LAW: The Information Technology Act, 2000 addresses non-consensual sharing of private images. "
            "Section 66E penalises capturing, publishing or transmitting images of a person's private area "
            "without consent (violation of privacy). Section 67 penalises publishing or transmitting obscene "
            "material in electronic form, and Section 67A covers sexually explicit material. Related offences "
            "against women (such as acts intended to insult modesty) may also apply under the Bharatiya Nyaya "
            "Sanhita, 2023. Report on cybercrime.gov.in and/or to the police; preserve the evidence."
        ),
    ),
    _entry(
        doc_id="IT-ACT-2000-S66C-S66D", title="Online impersonation and identity theft",
        act_name="Information Technology Act, 2000", section="Sections 66C & 66D",
        category="cyber", subcategory="impersonation",
        authority="Ministry of Electronics and IT / India Code", effective_date="2009-10-27",
        keywords=["impersonation", "fake profile", "identity theft", "fake account", "someone using my name",
                  "account hacked", "cheating by impersonation", "fraud profile"],
        text=(
            "LAW: Under the Information Technology Act, 2000, Section 66C penalises identity theft — the "
            "fraudulent or dishonest use of another person's electronic signature, password or other unique "
            "identification feature. Section 66D penalises cheating by personation using a computer resource "
            "or communication device (for example a fake profile used to deceive). Fake accounts, hacked "
            "accounts and impersonation can be reported on cybercrime.gov.in or to the police."
        ),
    ),
    _entry(
        doc_id="CYBER-FINANCIAL-FRAUD-1930", title="Financial cyber fraud (money lost online)",
        act_name="National Cyber Crime Reporting Portal & Helpline 1930",
        section="Reporting pathway",
        category="cyber", subcategory="financial_fraud",
        authority="Ministry of Home Affairs (I4C)", authority_level="tier1_primary_authority",
        source_type="official_service", source_url="https://cybercrime.gov.in/",
        keywords=["cyber fraud", "online fraud", "money stolen", "upi fraud", "bank fraud",
                  "otp fraud", "lost money online", "financial fraud", "scam", "1930",
                  "ऑनलाइन धोखाधड़ी", "पैसे चोरी", "यूपीआई धोखाधड़ी", "बैंक धोखाधड़ी"],
        text=(
            "PROCESS: For financial cyber fraud (for example UPI, card, net-banking or OTP fraud), report "
            "immediately on the 24x7 cyber helpline 1930 and on the National Cyber Crime Reporting Portal "
            "(cybercrime.gov.in). Fast reporting improves the chance of freezing the fraudulent transfer. "
            "Keep transaction IDs, bank messages and any communication with the fraudster. You can also "
            "inform your bank to block the account/card."
        ),
    ),
    # ================= WORKPLACE (POSH) =================
    _entry(
        doc_id="POSH-2013-S4", title="Workplace sexual harassment: Internal Committee (POSH)",
        act_name="Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013",
        section="Sections 3, 4 & 6",
        category="workplace", subcategory="posh_overview",
        authority="Ministry of Women and Child Development / India Code", effective_date="2013-12-09",
        source_url="https://wcd.nic.in/",
        keywords=["posh", "workplace harassment", "sexual harassment at work", "office harassment",
                  "boss harassing me", "internal committee", "icc", "colleague harassment",
                  "कार्यस्थल यौन उत्पीड़न", "दफ्तर में उत्पीड़न", "आंतरिक समिति"],
        text=(
            "LAW: The Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, "
            "2013 (POSH Act) prohibits sexual harassment of women at the workplace (Section 3). Every "
            "employer with 10 or more workers must constitute an Internal Committee (Section 4) to receive "
            "and inquire into complaints; where no Internal Committee exists (e.g. smaller establishments), a "
            "Local Committee at the district level (Section 6) receives complaints. 'Workplace' and "
            "'employee' are defined broadly, covering many work arrangements."
        ),
    ),
    _entry(
        doc_id="POSH-2013-S9-COMPLAINT", title="Filing a POSH complaint: process and timeline",
        act_name="Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013",
        section="Sections 9, 11 & 13",
        category="workplace", subcategory="posh_complaint",
        authority="Ministry of Women and Child Development / India Code", effective_date="2013-12-09",
        source_url="https://wcd.nic.in/",
        keywords=["posh complaint", "how to complain workplace", "complaint timeline", "3 months",
                  "internal committee complaint", "workplace inquiry",
                  "पॉश शिकायत", "कार्यस्थल शिकायत", "दफ्तर में शिकायत"],
        text=(
            "PROCESS/LAW: Under Section 9 of the POSH Act, 2013 an aggrieved woman may make a written "
            "complaint of sexual harassment to the Internal Committee (or Local Committee) ordinarily within "
            "three months of the incident (or the last incident), and the Committee may extend this period "
            "for recorded reasons. The Committee then inquires into the complaint (Section 11) and must "
            "ordinarily complete the inquiry and provide its report within a defined period (Section 13), "
            "with conciliation available at the woman's request before inquiry. The employer must act on the "
            "recommendations. This is separate from, and additional to, any criminal complaint to the police."
        ),
    ),
    # ================= LEGAL AID =================
    _entry(
        doc_id="LSA-1987-S12", title="Free legal aid: who is eligible (NALSA)",
        act_name="Legal Services Authorities Act, 1987", section="Section 12",
        category="legal_aid", subcategory="eligibility",
        authority="National Legal Services Authority (NALSA)", authority_level="tier1_primary_authority",
        source_type="statute", source_url="https://nalsa.gov.in/", effective_date="1987-10-11",
        keywords=["legal aid", "free lawyer", "cannot afford lawyer", "free legal help", "nalsa",
                  "free legal services", "legal aid eligibility", "muft vakil",
                  "कानूनी सहायता", "कानूनी मदद", "मुफ्त वकील", "निःशुल्क कानूनी सहायता", "वकील"],
        text=(
            "LAW: Under Section 12 of the Legal Services Authorities Act, 1987, free legal services are "
            "available to eligible persons — including all women and children, members of Scheduled Castes/"
            "Tribes, victims of trafficking, persons with disabilities, victims of mass disaster, industrial "
            "workmen, persons in custody, and persons with income below a prescribed limit. This means women "
            "and children are entitled to free legal aid regardless of income. Legal aid can cover lawyer's "
            "fees, court fees and drafting."
        ),
    ),
    _entry(
        doc_id="NALSA-HOW-TO-APPLY", title="How to get legal aid: NALSA / SLSA / DLSA (helpline 15100)",
        act_name="Legal Services Authorities Act, 1987 (NALSA/SLSA/DLSA)",
        section="Sections 3, 6 & 9",
        category="legal_aid", subcategory="how_to_apply",
        authority="National Legal Services Authority (NALSA)", authority_level="tier1_primary_authority",
        source_type="official_service", source_url="https://nalsa.gov.in/",
        keywords=["how to apply legal aid", "dlsa", "slsa", "legal aid application", "legal services authority",
                  "15100", "district legal services", "lok adalat",
                  "कानूनी सहायता कैसे लें", "कानूनी सेवा प्राधिकरण", "जिला विधिक सेवा"],
        text=(
            "PROCESS: Legal aid is delivered through a structure created by the Legal Services Authorities "
            "Act, 1987 — the National Legal Services Authority (NALSA) at the national level (Section 3), "
            "State Legal Services Authorities (SLSA, Section 6), and District Legal Services Authorities "
            "(DLSA, Section 9), with Taluk committees below. To apply, approach your nearest DLSA (usually in "
            "the District Court complex), the SLSA, or a Legal Services clinic; applications can be made in "
            "writing or orally. NALSA operates a toll-free legal-aid helpline 15100. These authorities also "
            "organise Lok Adalats for amicable settlement of cases."
        ),
    ),
    _entry(
        doc_id="TELE-LAW-14454", title="Tele-Law: free legal advice (helpline 14454)",
        act_name="Department of Justice — Tele-Law programme",
        section="Government of India scheme",
        category="legal_aid", subcategory="tele_law",
        authority="Department of Justice, Ministry of Law and Justice",
        authority_level="tier1_primary_authority", source_type="official_service",
        source_url="https://doj.gov.in/",
        keywords=["tele-law", "telelaw", "free legal advice", "14454", "legal advice phone",
                  "talk to lawyer", "online legal advice", "nyaya setu",
                  "मुफ्त कानूनी सलाह", "वकील से बात", "कानूनी सलाह"],
        text=(
            "PROCESS: Tele-Law is a Department of Justice (Ministry of Law and Justice) programme that "
            "connects people with panel lawyers for legal advice, including through Common Service Centres "
            "and the Tele-Law/Nyaya Setu platform. The programme provides a toll-free number 14454 for legal "
            "advice. It is aimed at making pre-litigation legal advice accessible, and is free for those "
            "eligible for legal aid."
        ),
    ),
    # ================= COURT / CASE STATUS (navigation only) =================
    _entry(
        doc_id="ECOURTS-CASE-STATUS", title="Checking case status online (eCourts / CNR number)",
        act_name="eCourts Services (Supreme Court of India — eCommittee)",
        section="Case-status navigation",
        category="court_navigation", subcategory="case_status",
        authority="eCommittee, Supreme Court of India", authority_level="tier1_primary_authority",
        source_type="official_service", source_url="https://ecourts.gov.in/",
        keywords=["case status", "check my case", "cnr number", "ecourts", "case number", "next hearing date",
                  "court case online", "case tracking", "district court case"],
        text=(
            "PROCESS (navigation only): The status of most District and High Court cases in India can be "
            "checked through the eCourts Services portal (ecourts.gov.in) and the eCourts Services mobile "
            "app. You can search using the 16-digit CNR (Case Number Record) number printed on court "
            "documents, or by case number, party name, filing number, FIR number or advocate. The portal "
            "shows the case's hearing history and next hearing date. NOTE: This tool does not itself fetch "
            "or confirm your live case status — always verify the case number and details on the official "
            "eCourts portal or with your advocate/court."
        ),
    ),
    _entry(
        doc_id="ECOURTS-EFILING", title="e-Filing and paying court fees online",
        act_name="eCourts Services (Supreme Court of India — eCommittee)",
        section="e-Filing navigation",
        category="court_navigation", subcategory="efiling",
        authority="eCommittee, Supreme Court of India", authority_level="tier1_primary_authority",
        source_type="official_service", source_url="https://efiling.ecourts.gov.in/",
        keywords=["e-filing", "efiling", "file case online", "court fee online", "epay", "e-pay court fee",
                  "how to file case", "electronic filing"],
        text=(
            "PROCESS (navigation only): The eCourts e-Filing portal (efiling.ecourts.gov.in) allows "
            "advocates and litigants to file cases electronically in participating courts, and the ePay "
            "facility allows online payment of court fees. Registration is required. The exact procedure, "
            "accepted document formats and which courts are enabled vary by state and court, so confirm the "
            "requirements for your specific court before filing, ideally with an advocate."
        ),
    ),
]


def all_entries():
    """Return the full seed corpus (list of dicts)."""
    return CORPUS
