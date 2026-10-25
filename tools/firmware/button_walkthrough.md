# Verifica guidata dei pulsanti Vimar

Dalla radice del progetto, nel terminale del devcontainer:

```sh
work/smpclient-venv/bin/python tools/firmware/button_walkthrough.py \
  --address "$VIMAR_BLE_ADDRESS" --main-hash "$VIMAR_MAIN_SMP_HASH" \
  --recovery-hash "$VIMAR_RECOVERY_SMP_HASH"
```

Il firmware nel profilo simulato e il bond BlueZ del Vimar devono essere già presenti.
Imposta le tre variabili locali con l’indirizzo BLE del tuo dispositivo e gli hash
SMP delle due immagini attese (SHA-256 della regione firmata, non dell’intero file).
Lo script richiede esplicitamente questi valori per ogni prova reale; non modifica firmware, associazioni, configurazione
Bluetooth o uscita luce. Il comando SMP di reset viene usato soltanto per tornare
all'applicazione dopo aver verificato il contenuto della recovery.

Mantieni l'attuale collegamento da banco e la molletta SWD. I pulsanti da premere
sono quelli del **Vimar**, non BUTTON 1/RESET del DK. Per il test all'accensione
si interrompe soltanto l'alimentazione USB del DK/Vimar; la chiavetta Bluetooth del
PC deve restare collegata. Non serve coordinarsi con la chat.

La sequenza è:

1. Controllo BLE dell'applicazione simulata, senza comandi alla luce.
2. Premi Invio per armare; attendi **ORA**, poi tieni UP e DOWN insieme per almeno
   sei secondi e rilasciali. Il monitor ascolta già quando compare il segnale.
3. Lo script verifica il servizio di recovery autenticato e gli hash di entrambe
   le immagini. Conferma se hai eseguito il gesto indicato. Rilascia tutti i
   pulsanti e premi Invio per rientrare nell'applicazione.
4. Premi Invio per armare il secondo test; attendi **ORA**. Scollega l'USB di
   alimentazione, tieni UP, ricollega l'USB e mantieni UP fino al messaggio di rilascio della guida.
5. Segue lo stesso controllo BLE e il ritorno guidato all'applicazione.

`SALTA` evita una prova e viene registrato come prova incompleta. `Ctrl+C` annulla
e conserva i risultati parziali. Il timeout predefinito è 180 secondi per ciascuna attesa BLE, compreso
il controllo iniziale dell’app e il ritorno dalla recovery. La guida mostra
i tentativi di riconnessione e li registra nel log. Puoi usare `--timeout 300`
se preferisci più tempo. Non viene misurata la durata effettiva
della pressione: il tempo include lettura delle istruzioni e riconnessione BLE.

Per leggere le istruzioni senza collegarsi al dispositivo:

```sh
work/smpclient-venv/bin/python tools/firmware/button_walkthrough.py --plan
```

Ogni esecuzione crea una nuova cartella ignorata
`experiments/vimar-button-check-<timestamp>/`, contenente:

- `events.jsonl`: eventi e risposte dell'operatore con timestamp UTC;
- `results.json`: riepilogo aggiornato dopo ogni fase, con hash, osservazioni e
  stato distinto per prova superata, saltata, non confermata, fallita o annullata.

Puoi scegliere una cartella nuova con `--output percorso`. I risultati già
esistenti non vengono sovrascritti. Codici di uscita: 0 entrambe superate,
2 incompleto, 1 errore, 130 annullamento.

Un errore BLE o un timeout non valgono come prova dei pulsanti. Dopo un errore
non vengono inviati ulteriori reset: il Vimar potrebbe essere ancora in
recovery, oppure essersi già riavviato se hai interrotto la fase di ritorno.
Gli eventi `reset_request_sending` e `reset_acknowledged` distinguono questi casi. Conserva la cartella indicata e condividi l'esito prima di ripetere
operazioni manuali. Non avviare altri client BLE contemporaneamente alla guida.

Il firmware non espone gli eventi delle singole pressioni: questa guida verifica
i due ingressi recovery, non toggle, dimmerazione, polarità dei singoli pulsanti,
LED o effetti sulla luce. La conferma dell'operatore è registrata separatamente
dall'osservazione automatica BLE.
