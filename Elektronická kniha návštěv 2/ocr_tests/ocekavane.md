# Očekávané chování po opravách (checklist)

Odškrtává se po spuštění runneru proti opravenému `ocr_processor`
(sloupec „after"). Vztahuje se hlavně na **čisté** obrázky; degradace mohou
kvalitu snížit, ale nesmí vytvořit **cizí identitu**.

## Extrakce jména/příjmení

- [ ] `obcanka` → jméno **Jan** / příjmení **Novák** (nesmí regresí zmizet)
- [ ] `ridicak_se_slovy` → jméno **Jan** / příjmení **Novák**
- [ ] `ridicak_jen_cisla` → jméno **Jan** / příjmení **Novák** (jen „1." / „2." bez slov)
- [ ] `personalausweis` → jméno **Hans** / příjmení **Müller**
      (německé „Name" = PŘÍJMENÍ, „Vorname" = jméno; **NESMÍ být prohozeno!**)
- [ ] `ceske_jmeno_ss` → příjmení **Müller** / jméno **Weiß**
      (ß správně, ne „Weib")
- [ ] `zdravotni_ehic_zadni` → jméno **Jan** / příjmení **Novák**

## Bezpečnost whitelistu (nejdůležitější)

- [ ] `zdravotni_predni_pohromade` → **NIKDY** nesmí vrátit „Simon"/„Pistora"
      ani jinou osobu z whitelistu (ideálně Jan/Novák nebo prázdno; hlavně
      žádná cizí identita)
- [ ] `zdravotni_predni_oddelene` → **NIKDY** „Simon"/„Pistora" ani jiná cizí
      identita (ideálně Jan/Novák nebo prázdno)

## Poznámka k baseline (before)

Aktuální stav (viz `vysledky_before.md`) chybu ukazuje: i s
`OCR_STRICT_WHITELIST=1` vrací `zdravotni_predni_*` osobu **Simon / Pistora**
z whitelistu, přestože na kartě je Novák Jan. To je přesně to, co má oprava
odstranit.
