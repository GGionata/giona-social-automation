# Procedura dell'esecuzione automatica

Questa è la procedura che il task programmato esegue ogni giorno poco prima delle 08:00 e delle 13:00 (Europe/Rome). Nessuno segue l'esecuzione: niente domande, si prende la lettura più ragionevole e la si dichiara nel messaggio finale.

Vincoli assoluti:
- Non pubblicare mai nulla sui social e non chiamare API di pubblicazione.
- Non modificare il sito WordPress: solo letture pubbliche dalla REST API.
- Italiano, mai emoji, mai il trattino lungo, nei testi e nei messaggi.

Dati fissi:
- Repository: https://github.com/GGionata/giona-social-automation (lavorare in `~/giona-social-automation`)
- Google Sheet calendario: id `1-J-DsBXfCD_kbzi1YgN8cdign6kG14cwJMMuFt0l1fY`, foglio `Calendario`, intestazione in riga 1, colonne A:N

## Passo 1. Preparazione

Se il clone non riesce per permessi, chiama lo strumento `add_repo` con owner `GGionata`, repo `giona-social-automation`, access `push`, poi riprova una volta.

```bash
cd ~ && rm -rf giona-social-automation && git clone --depth 1 https://github.com/GGionata/giona-social-automation && cd giona-social-automation
python3 -c "import PIL" 2>/dev/null || pip install --break-system-packages Pillow
python3 gsa.py status
```

Se il clone fallisce, fermati e segnala il problema nel messaggio finale: senza database non si lavora.

## Passo 2. Leggi il foglio e applica le modifiche dell'utente

1. Con il connettore Google Sheets chiama `get_values` su `Calendario!A1:N400`.
2. Scrivi il campo `values` della risposta, identico, in `/tmp/sheet.json` (array JSON di righe). Non riscrivere i testi a memoria: copia la risposta.
3. `python3 gsa.py sheet-import /tmp/sheet.json`

Se il foglio è vuoto o illeggibile, salta questo passo e segnalalo.

## Passo 3. Nuovi articoli

`python3 gsa.py fetch`

## Passo 4. Bozze da riscrivere

`python3 gsa.py review`

Per ogni bozza restituita:
- stato `da rivedere`: riscrivi il testo seguendo `nota_utente` e `linee-guida.md`;
- stato `bloccato`: correggi soltanto i `problemi` indicati, toccando il resto il meno possibile.

Scrivi il nuovo testo in un file con il segnaposto `{link}` al posto del link e lancia `python3 gsa.py edit <ID> <file>`. Massimo due tentativi per bozza; se resta bloccata, segnalala.

## Passo 5. Nuove bozze

`python3 gsa.py next`

Se `articolo` è `null`, salta al passo 6.

Altrimenti:
1. Leggi `linee-guida.md` per intero.
2. Se `riserva_evergreen` è `true`, valuta se l'argomento è ancora attuale e utile: se non lo è, `python3 gsa.py skip <ID> "<motivo>"` e rilancia `next` (al massimo tre volte).
3. Leggi `content_text` dell'articolo, scegli cinque idee diverse e scrivi le cinque bozze in `/tmp/bozze.json` nel formato indicato nelle linee guida. Evita le aperture in `aperture_recenti_da_non_ripetere`.
4. `python3 gsa.py save /tmp/bozze.json`
5. Per ogni post in stato `bloccato`, correggi con `edit` come al passo 4.

Un solo articolo per esecuzione.

## Passo 6. Aggiorna il foglio

1. `python3 gsa.py sheet-export > /tmp/export.json`
2. Con Google Sheets `batch_clear_values` su `Calendario!A2:N400`.
3. `update_values` su `Calendario!A1` con il contenuto di `/tmp/export.json` (righe identiche, nessuna modifica a mano).

## Passo 7. Report del lunedì

Solo nell'esecuzione del mattino di lunedì: `python3 gsa.py report --week $(date -d yesterday +%F)` per la settimana appena chiusa.

## Passo 8. Salva

```bash
python3 gsa.py calendar
git add -A && git commit -m "Esecuzione $(date +%F\ %H:%M)" && git push origin HEAD:main
```

Se il push viene rifiutato, `git pull --rebase origin main` e riprova una volta. Un push fallito va sempre segnalato: le modifiche non salvate si perdono.

## Passo 9. Messaggio finale

Invia un messaggio con `SendUserMessage` solo se c'è qualcosa da sapere; un'esecuzione senza novità termina senza messaggi.

Contenuto, in quest'ordine e solo le parti presenti:
1. **Post di oggi** (solo esecuzione del mattino, da `python3 gsa.py today`): ora, canale, stato. Se è `approvato`, il testo completo in un blocco di codice pronto da copiare e il link all'immagine se presente. Se non è approvato, dillo chiaramente.
2. **Nuove bozze pronte**: titolo dell'articolo, le date delle cinque uscite, link al foglio https://docs.google.com/spreadsheets/d/1-J-DsBXfCD_kbzi1YgN8cdign6kG14cwJMMuFt0l1fY/edit
3. **Problemi**: bozze bloccate, link non funzionanti, immagini mancanti, errori di sincronizzazione o di push.
4. **Report**: se generato, il percorso del file e il riepilogo in tre righe.
