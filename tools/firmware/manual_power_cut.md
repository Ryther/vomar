# Prova manuale di perdita di alimentazione sul DK

Dal terminale **del devcontainer**, nella radice del repository:

```sh
work/smpclient-venv/bin/python tools/firmware/manual_power_cut.py --address "$VIMAR_DK_BLE_ADDRESS" \
  --image "$VIMAR_DK_IMAGE" --image-sha256 "$VIMAR_DK_IMAGE_SHA256" \
  --recovery-hash "$VIMAR_DK_RECOVERY_SMP_HASH"
```

Lo script usa il BlueZ del PC tramite il D-Bus già condiviso col container e
l'associazione BLE esistente. Il Vimar deve restare scollegato. La destinazione
è l’indirizzo DK esplicito passato con `--address`; imposta le variabili locali
per il tuo DK isolato e la sua build. Sono verificati l’hash SMP atteso della
recovery attiva e lo SHA-256 atteso dell’intero file MAIN prima dell’upload.

1. Entra nel recupero con B1 + RESET, rilascia B1 e preparati sul cavo USB.
2. Premi Invio nel terminale per iniziare.
3. Quando compare **STACCA ORA LA USB DEL DK**, scollega subito il cavo.
   L'upload continua dopo il segnale; il beep dipende dalle impostazioni del terminale.
4. Lascia il DK spento finché lo script chiede conferma. Conferma soltanto se
   hai visto che si è spento completamente.
5. Quando richiesto, ricollega la USB **senza B1** e premi Invio. Lo script
   verifica che sia ripartita automaticamente la stessa recovery BLE.

La soglia predefinita è 65536 byte confermati; `--signal-at` permette valori
da 4096 a 262144. Se l'upload arriva al 90% senza interruzioni, lo script lo
ferma e non valida la prova. Ctrl+C annulla senza reset o ripristino automatico.
In caso di errore, il DK può avere un'app incompleta e richiedere B1 + RESET.

Il DK resta in recovery al termine: occorre ripristinare l'app principale via
BLE con la procedura di upload già usata nelle prove del 19 ottobre.
Lo script non modifica bootloader o recovery e non invia comandi SWD.

Gli eventi, l'hash del file trasmesso, l'ultimo offset confermato e la conferma
dell'operatore sono registrati in `experiments/dk-manual-power-cut-*/events.jsonl`.
Una disconnessione BLE da sola non conferma la perdita di alimentazione.
La temporizzazione manuale non dimostra un'interruzione nel preciso istante
di una scrittura flash. Il segnale parte dopo un ACK e durante l'upload
successivo, non da una misura dell'attività del controller flash.

Verifica senza hardware:

```sh
python -m unittest discover -s tools/firmware/tests -p test_manual_power_cut.py
```
