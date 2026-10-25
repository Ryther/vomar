# Misurare l'avvio BLE del Vimar

Avvia nel terminale del devcontainer, dalla radice del progetto:

```sh
work/smpclient-venv/bin/python tools/firmware/measure_boot.py --address "$VIMAR_BLE_ADDRESS"
```

Ferma il monitor SWD e gli altri client BLE. Lascia il cablaggio e la posizione
attuali; usa soltanto l'alimentazione da banco già in uso. Non premere i tasti
del Vimar durante questa prova. La guida distingue il Vimar dal DK tramite
l’indirizzo esatto passato con `--address`. Imposta la variabile locale sul tuo dispositivo.

Lo script:

1. Verifica la risposta autenticata dell'applicazione attualmente accesa. Non
   spegnere prima che venga richiesto. Se non risponde, la misura non parte.
2. Dopo il tuo Invio, mostra **ORA SPEGNI**. Spegni e premi Invio per confermare.
3. Chiede di lasciare la USB scollegata almeno **120 secondi**. Mostra ogni cinque
   secondi il tempo trascorso, quello minimo restante e da quanto non riceve annunci
   dal Vimar. Richiede almeno **10 secondi consecutivi senza annunci**: ogni nuovo
   annuncio fa ripartire questo conteggio. Verifica gli annunci prima dello
   scollegamento e ricontrolla il silenzio prima del segnale ACCENDI. Il silenzio
   radio non equivale a una verifica elettrica dello spegnimento.
4. Chiede di prepararti, poi mostra **ORA ACCENDI**. Riaccendi senza premere tasti
   e premi subito Invio per registrare la conferma. Il monitoraggio è già attivo.
5. Rileva il primo annuncio del Vimar, ferma la scansione e si collega al dispositivo
   appena rilevato per leggere la console autenticata. Se BlueZ segnala una
   connessione pendente, annulla quella del solo Vimar e riprova senza rimuovere
   il bond o cambiare lo stato dell’adattatore.
   Questi eventi vengono misurati anche se non hai ancora premuto Invio.
6. Mostra i tempi come intervalli: il segnale e il tuo Invio delimitano la
   riaccensione manuale. Questi limiti valgono se hai riacceso dopo il segnale e
   prima dell'Invio. Il ritardo dell'adattatore/scansione e quello della connessione
   restano inclusi: non sono tempi elettrici né tempi puri del bootloader.
7. Confronta l'uptime prima e dopo, con timestamp attorno alla richiesta BLE, per
   verificare un nuovo avvio del kernel. La risposta BLE da sola non dimostra che
   il dispositivo sia stato spento. Se non conferma il riavvio, l'esito resta
   `restart_not_confirmed`, non una misura di avvio riuscita.

La guida non riavvia autonomamente il Vimar, non aggiorna firmware, non cambia
associazioni Bluetooth, non usa SWD e non invia comandi alla luce.

Default: massimo300 secondi per l'attesa iniziale e per annuncio/risposta dopo il
segnale ACCENDI. Puoi modificarlo con `--timeout 600`. Per leggere solo il piano,
senza Bluetooth, usa `--plan`.

I file sono in una nuova cartella ignorata `experiments/vimar-boot-timing-<UTC>/`:

- `events.jsonl`: timestamp UTC e monotonic, segnali, conferme, tentativi e risposte;
- `results.json`: fasi e misure, uptime e stato finale, aggiornato durante la prova.

`Ctrl+C` interrompe e salva lo stato. In caso di errore nessun reset o ripristino
è automatico. Codici di uscita:0 misura completata con nuovo avvio osservato,
2 riavvio non confermato,1 errore/timeout,130 annullamento. La misura riguarda un
singolo ciclo, non dimostra affidabilità su tutti gli avvii. Nessuna rilevazione
della recovery viene trattata come risposta dell'applicazione principale.

La pausa minima è configurabile con `--off-seconds 120`; il silenzio richiesto con
`--quiet-seconds 10`. I valori predefiniti rendono automatica l’attesa proposta
per la prova della carica residua: non sono tempi di scarica elettrica garantiti.
Durante la pausa non vengono aperte connessioni BLE: il monitor resta in scansione.
Un timeout non autorizza il segnale ACCENDI. JSON/JSONL conservano conteggio degli
annunci, ultimo annuncio e progressi; `electrical_power_off_confirmed` resta falso.

Sul DK è stata individuata una pila a bottone: **escluderla prima della prova**,
altrimenti scollegare la USB può lasciare alimentato il Vimar da VDD. Non usare
l’attesa come tentativo di scaricare la pila.

I rilevamenti provengono dai callback Bleak/BlueZ, che possono includere cambiamenti
alle proprietà cached oltre ai dati radio. La dicitura storica `first_advertisement`
nei JSON identifica quel callback, non un timestamp HCI certificato. Il confronto
dell’uptime e le risposte autenticate restano le evidenze per il nuovo kernel.

Se la connessione espone il servizio SMP della recovery invece della console
principale, la guida termina subito con `recovery_detected` (codice2). Non continua
fino al timeout e non riavvia il dispositivo. Nella recovery il LED temporaneo
è spento: questo esito indica una radio raggiungibile con l'app principale non
attiva, non uno spegnimento. Gli hash delle immagini si verificano separatamente.
