# Giona Social Automation

Trasforma ogni nuovo articolo di https://www.gionawebdesign.com/blog in cinque bozze social da pubblicare a mano:

| Giorno | Ora | Canale | Contenuto | Immagine |
|---|---|---|---|---|
| martedì | 09:00 | Threads | problema e conseguenze | sì |
| mercoledì | 09:00 | LinkedIn (profilo personale) | approfondimento professionale | sì |
| giovedì | 12:30 | Threads | consiglio pratico | no |
| venerdì | 09:00 | LinkedIn | soluzione, checklist o analisi | no |
| sabato | 09:00 | Threads | approfondimento | no |

Il sistema non pubblica mai e non modifica il sito: legge la REST API pubblica di WordPress, prepara testi, link tracciati e immagini, e aspetta l'approvazione.

## Come funziona

- **Task programmato** nel cloud di Claude, ogni giorno alle 07:57 e alle 12:57 (Europe/Rome). Gira anche a computer spento, segue [PROCEDURA.md](PROCEDURA.md).
- **Database SQLite** in `data/gsa.sqlite`: articoli, bozze, link, immagini, date, stati, modifiche manuali, registro delle esecuzioni. Ogni esecuzione lo aggiorna e lo salva in questo repository.
- **Google Sheet** [Giona Social Automation - Calendario](https://docs.google.com/spreadsheets/d/1-J-DsBXfCD_kbzi1YgN8cdign6kG14cwJMMuFt0l1fY/edit): qui si approva, si corregge e si segna come pubblicato. Mostra le ultime due settimane, il futuro e le bozze aperte; lo storico completo resta nel database.
- **Immagini**: copia JPEG dell'immagine in evidenza in `images/<id articolo>/`. Gli originali WebP su WordPress non vengono toccati.
- **Calendario** sempre aggiornato in [calendario.md](calendario.md), **report settimanali** in `reports/`.

## Ciclo di vita di una bozza

`da approvare` → `approvato` → `pubblicato` (lo segni tu dopo l'uscita)

- `da rivedere`: scrivi nella colonna Note cosa cambiare, alla prossima esecuzione il testo viene riscritto.
- `bloccato`: un controllo automatico è fallito, il motivo è nella colonna Problemi. Viene corretto in automatico o puoi correggerlo tu nel foglio.
- `scartato`: il post non esce.

## Coda degli articoli

- Un articolo per settimana, cinque post.
- Più articoli nuovi in attesa escono in ordine di pubblicazione, dal meno recente.
- I 25 articoli pubblicati prima dell'avvio sono **riserva evergreen**: si usano solo nelle settimane senza articoli nuovi, dal meno recente, saltando quelli non più attuali e quelli già promossi negli ultimi 120 giorni.

## Controlli automatici

Ogni bozza viene bloccata se:
- manca il link o la pagina non risponde 200, è in noindex o ha un canonical diverso;
- supera 500 caratteri su Threads o 3.000 su LinkedIn (o ne ha meno di 600 su LinkedIn);
- contiene il trattino lungo, emoji, markdown, segnaposto o formule vietate (`config.json`);
- cita un numero che non compare nell'articolo;
- somiglia troppo a un'altra bozza dello stesso articolo o riprende un'apertura già usata;
- l'immagine prevista non è JPEG, supera 8 MB o ha proporzioni non ammesse;
- c'è più di un post nello stesso giorno.

## Link tracciati (GA4)

`utm_source` = threads o linkedin, `utm_medium` = social, `utm_campaign` = blog_articolo, `utm_content` = canale_tipo (per esempio `threads_problema`). L'articolo si distingue dalla pagina di destinazione. In GA4: Acquisizione traffico, filtro Campagna sessione = blog_articolo.

## Comandi

```bash
python3 gsa.py status                  # situazione rapida
python3 gsa.py fetch                   # cerca nuovi articoli
python3 gsa.py next                    # articolo da trasformare in bozze
python3 gsa.py save bozze.json         # salva le 5 bozze (formato in linee-guida.md)
python3 gsa.py edit ID testo.txt       # corregge una bozza, {link} = link tracciato
python3 gsa.py review                  # bozze da riscrivere
python3 gsa.py check                   # ricontrolla tutto
python3 gsa.py today [--date AAAA-MM-GG]
python3 gsa.py skip ID "motivo"        # esclude un articolo
python3 gsa.py report [--week AAAA-MM-GG]
python3 gsa.py calendar
```

Requisiti: Python 3.9 o superiore e Pillow (`pip install Pillow`). Nessuna credenziale: la REST API di WordPress è pubblica.

## Avvio manuale

Dall'app Claude: apri le attività programmate e avvia "Bozze social gionawebdesign" con Esegui ora. Oppure, in una conversazione: "esegui la procedura in PROCEDURA.md del repository giona-social-automation".

Da un computer:

```bash
git clone https://github.com/GGionata/giona-social-automation && cd giona-social-automation
pip install Pillow
python3 gsa.py status
```

## Modifiche frequenti

- Orari e canali: `slots` in `config.json` (giorno 0 = lunedì).
- Formule vietate e limiti: `banned_phrases` e `limits` in `config.json`.
- Tono e struttura dei testi: `linee-guida.md`.
- Orario delle esecuzioni: impostazioni del task programmato.

## Risoluzione dei problemi

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| Nessuna bozza dopo un articolo nuovo | articolo pubblicato dopo le 13:00, o settimana già occupata | arriva alla prossima esecuzione; verifica con `status` la prossima settimana libera |
| Bozza bloccata per "numero non presente" | il testo cita un dato non scritto così nell'articolo | riscrivi il numero come nell'articolo o toglilo |
| "link risponde 404" o "noindex" | slug cambiato o pagina non indicizzabile | correggi la pagina su WordPress, poi `check` |
| Articolo senza immagine | immagine in evidenza assente o non pubblica | il post esce solo testo, oppure imposta un'immagine su WordPress |
| Modifiche nel foglio non recepite | stato scritto a mano fuori dal menu | usa il menu a tendina della colonna Stato |
| Messaggio "push fallito" | conflitto sul repository | la volta successiva si riallinea; se si ripete, controlla l'ultimo commit su GitHub |

## Struttura

```
gsa.py            motore (CLI, solo libreria standard + Pillow)
config.json       calendario, limiti, formule vietate
linee-guida.md    regole di scrittura
PROCEDURA.md      istruzioni del task programmato
data/gsa.sqlite   database
images/           copie JPEG
reports/          report settimanali
calendario.md     calendario leggibile
```
