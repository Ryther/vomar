# Confronto guidato del fade-in del dimmer

Dal terminale del progetto/devcontainer:

```sh
python tools/firmware/fade_walkthrough.py --ieee "$VIMAR_ZIGBEE_IEEE" --url "$VIMAR_Z2M_WS_URL"
```

Imposta le variabili locali con l’IEEE esatto del tuo dimmer e l’URL WebSocket
dell’API Zigbee2MQTT (`ws://` o `wss://`). Ogni prova reale richiede `--ieee` e
`--url`; non esiste un dispositivo o server predefinito. Aggiungi `--origin` se
il proxy lo richiede. Il cookie locale viene letto da
`work/private/z2m-cookie.txt`, oppure dal percorso indicato con `--cookie`.
Non inserire credenziali in chat.

Prima controlla identità, raggiungibilità e parametri. Se il dispositivo non
risponde, non invia comandi alla lampada. Timer, transizione o spegnimento
automatico attivi interrompono la preparazione senza cambiare configurazione.

Invio autorizza **il singolo comando descritto nel terminale**. Dopo la prima
accensione annota il salto e l’eventuale attesa. Nella seconda prova conferma
prima che la luce sia stabile al minimo; soltanto un altro Invio avvia la salita.
La permanenza al minimo dipende dal tempo impiegato per annotare e confermare,
non è limitata a mezzo secondo. Le due rampe usano lo stesso livello finale.

Il livello finale è quello inizialmente memorizzato; se è al minimo usa32,3%
(limitato al massimo configurato). Puoi specificarlo:

```sh
python tools/firmware/fade_walkthrough.py --ieee "$VIMAR_ZIGBEE_IEEE" --url "$VIMAR_Z2M_WS_URL" --target-percent 35
```

Al termine puoi ripristinare stato e livello iniziali, sempre con conferme
prima dei comandi. Per ripristinare il livello memorizzato quando la condizione
iniziale era OFF può essere necessario applicare prima quel livello a lampada
accesa, poi spegnere; il terminale descrive entrambi i passaggi.

`q`, `stop` o Ctrl+C interrompono senza altri comandi né ripristino automatico.
La luce rimane nello stato raggiunto. Non modificare i parametri o usare altri
controlli durante il confronto.

Il programma non aggiorna firmware e non scrive parametri. Stato e luminosità
della lampada cambiano durante le prove e il firmware può memorizzarli normalmente.
I riscontri di uscita sono stime software, non misure ottiche.

Risultati e osservazioni sono salvati subito in una cartella nuova sotto
`experiments/fade-walkthrough/`; il percorso compare nel terminale. I file non
contengono il cookie. Dopo la prova basta comunicare «fatto» per farli analizzare.

Anteprima senza rete o comandi:

```sh
python tools/firmware/fade_walkthrough.py --dry-run
```

## Serie con pause brevi al minimo

Per confrontare il riferimento da spento con tre pause aggiuntive al minimo:

```sh
python tools/firmware/fade_walkthrough.py --ieee "$VIMAR_ZIGBEE_IEEE" --url "$VIMAR_Z2M_WS_URL" --startup-holds-ms 100,300,1000 --target-percent 32.3
```

Questa modalità richiede schema5, monitor P0.31 attivo/valido e non bloccato,
ritardo iniziale0 e una rampa di salita non nulla. Usa il normale OFF della
lampada; non richiede interruzioni di corrente. Non cambia firmware o parametri.

Prima esegue il riferimento OFF→32,3%. Poi, per ogni pausa, chiede Invio per
spegnere senza rampa e attendere3secondi. Un altro Invio autorizza la sequenza
descritta: ON diretto al minimo, conferma software, pausa aggiuntiva, salita
allo stesso32,3% con la stessa rampa. Al termine annoti il risultato. Durante
la sequenza usa Ctrl+C per fermare immediatamente altri comandi; `q` funziona
quando il terminale richiede una risposta.

100/300/1000ms sono attese **dopo la conferma software**, non permanenze fisiche
esatte della lampada. Il tempo di consegna e riscontro Zigbee si somma. I file
registrano il ritardo di conferma del minimo, l'attesa aggiuntiva osservata sul
PC e l'intervallo tra le richieste: non sono misure ottiche né timestamp dei
comandi sul dispositivo. Non usare questi valori come calibrazione esatta.

Se il minimo non viene confermato, lo stato cambia durante la pausa, il monitor
non è più pronto o aumenta il conteggio degli interventi, la salita non viene
inviata. Nessun ripristino automatico dopo un'interruzione. Il ripristino finale
di stato e luminosità rimane guidato e separato dalle prove.

Puoi aggiungere `--dry-run` al comando per vedere la sequenza senza collegarti.
