# Linee guida di scrittura

Valgono per ogni bozza generata dal sistema. Lo script `gsa.py` controlla in automatico le regole marcate con (auto); le altre dipendono da chi scrive.

## Chi parla e a chi

- Parla Gionata, web designer freelance a Milano, in prima persona singolare quando serve. Al lettore si dà del tu.
- Il lettore è un titolare di attività, uno studio professionale o una piccola impresa: persone competenti nel loro mestiere, non tecniche sul web. Niente gergo senza spiegazione.
- Tono: concreto, calmo, da professionista che ha visto il problema da vicino. Nessuna urgenza artificiale, nessun superlativo, nessuna promessa di risultati.

## Verità prima di tutto

- Usa solo fatti, dati ed esempi presenti nell'articolo. Ogni numero citato deve comparire nell'articolo (auto).
- Le esperienze personali si raccontano solo se l'articolo le riporta. Non inventare clienti, casi o risultati.
- Se l'articolo cita una fonte per un dato, puoi nominarla in breve.

## I cinque post: angolazioni diverse

Prima di scrivere, scegli cinque idee diverse dall'articolo, una per post, idealmente da sezioni diverse. Nessun post deve riassumere l'articolo intero. I testi non devono somigliarsi tra loro (auto, soglia di somiglianza) e l'apertura non deve ripetere quelle dei post precedenti (auto).

| Post | Canale | Tipo | Cosa fa |
|---|---|---|---|
| martedì 09:00 | Threads | problema | Un problema reale trattato nell'articolo e la conseguenza concreta per un'attività o uno studio |
| mercoledì 09:00 | LinkedIn | approfondimento | Una riflessione professionale: perché una scelta di progettazione o gestione web pesa sul business |
| giovedì 12:30 | Threads | consiglio | Una soluzione, una procedura breve o un errore da evitare, applicabile subito |
| venerdì 09:00 | LinkedIn | soluzione | Checklist, procedura o analisi pratica, più articolata |
| sabato 09:00 | Threads | approfondimento | Un'idea particolare, una mini checklist o una conclusione che invogli a leggere |

## Threads

- Limite 500 caratteri compreso il link (auto). Il link tracciato occupa circa 140 caratteri: con l'etichetta "Leggi l'articolo:" il testo vero resta sotto i 340.
- Struttura tipica: una prima riga che si legge da sola e incuriosisce, due o tre righe brevi di sostanza, la frase di invito con il link.
- Righe brevi, a capo singolo tra i blocchi. Niente elenchi lunghi.
- Niente hashtag.

## LinkedIn (profilo personale)

- Tra 900 e 1.600 caratteri. Minimo tecnico 600, massimo 3.000 (auto).
- Le prime due righe compaiono prima di "vedi altro": devono reggersi da sole, senza preamboli.
- Paragrafi di una o due frasi, separati da una riga vuota.
- Gli elenchi si scrivono con "- " a inizio riga, senza grassetti né simboli (auto: niente markdown).
- Chiusura: la frase con il link e, quando viene naturale, una domanda aperta ai lettori. Non sempre la stessa.
- Il post deve far capire il valore delle scelte di progettazione web, senza vendere un servizio.
- Massimo tre hashtag in fondo, solo se pertinenti; meglio nessuno che hashtag generici.
- Non riciclare frasi dei post Threads dello stesso articolo.

## Il link (obbligatorio)

- Ogni testo contiene una sola volta il segnaposto `{link}`: lo script lo sostituisce con l'URL tracciato (auto).
- Di norma il link punta all'articolo. Se un'altra pagina del sito è davvero più pertinente (per esempio la pagina servizi o il quiz di stile citato nell'articolo), indicala nel campo `url_base`, scegliendola solo tra le pagine elencate da `gsa.py next` o tra i link interni dell'articolo. Mai URL inventati.
- Threads e LinkedIn (profilo personale) non permettono testo cliccabile: il link è sempre l'URL incollato. Per questo il link sta da solo sull'ultima riga, preceduto dall'etichetta fissa `Leggi l'articolo:` (o `Leggi l'articolo completo:` su LinkedIn). Esempio di ultima riga: `Leggi l'articolo: {link}`.
- La riga prima dell'etichetta può chiudere il ragionamento o fare una domanda, ma non ripete cosa c'è nell'articolo con formule uguali ogni volta.
- Mai "link in bio", "clicca qui", "scopri di più" (auto per alcune formule).

## Formule vietate

- Mai il trattino lungo (auto) e mai emoji (auto).
- Mai "hai centrato il punto", "è proprio questo il punto" e le formule in `config.json` (auto).
- Evita le strutture riconoscibili come scrittura automatica: "non è solo X, è Y", terne di aggettivi, domande retoriche in apertura a ogni post, "Ecco perché", "Ti sei mai chiesto", "In un mondo in cui", chiusure motivazionali.
- Varia l'attacco: un fatto, una situazione concreta, un errore, un dato dell'articolo, una frase di un cliente se riportata nell'articolo.

## Immagine

- L'immagine in evidenza, convertita in JPEG, accompagna il Threads del martedì e il LinkedIn del mercoledì (auto). Gli altri post sono testuali.
- Ogni testo deve funzionare anche senza immagine.

## Formato del file bozze.json

```json
{
  "article_id": 1052,
  "posts": [
    {"canale": "threads", "tipo": "problema", "testo": "...\n\nfrase di invito: {link}"},
    {"canale": "linkedin", "tipo": "approfondimento", "testo": "..."},
    {"canale": "threads", "tipo": "consiglio", "testo": "..."},
    {"canale": "linkedin", "tipo": "soluzione", "testo": "...", "url_base": "https://www.gionawebdesign.com/..."},
    {"canale": "threads", "tipo": "approfondimento", "testo": "..."}
  ]
}
```

`url_base` è facoltativo. Dopo il salvataggio, ogni post con un problema passa in stato `bloccato` con il motivo scritto: si corregge il testo e si rilancia il controllo.
