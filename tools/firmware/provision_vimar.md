# Flashing Vimar30805, un dispositivo alla volta

Questa procedura sostituisce FLASH del solo nRF52840; non riprogramma il
controller di potenza. Usare solo il dimmer da banco collegato al DK, senza rete
230V. Non collegare il DK al dimmer già installato e alimentato dalla rete.

## Avvio

Dalla radice del repository, chiudere gli altri monitor SWD:

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /percorso/release/pair.json
```

Configura `VIMAR_DK_DEVICE_ID` con le due parole FICR DEVICEID del DK locale,
nel formato `UID0:UID1` (otto cifre esadecimali per parola, in ordine di
indirizzo). Ripeti `--dk-id` per ogni DK collegabile; in alternativa imposta
`VIMAR_DK_DEVICE_IDS` con lo stesso elenco separato da virgole. Non inserire
l’UID del dimmer in questo elenco di esclusione. Senza un elenco locale
configurato il programma termina prima di accedere all’hardware.

Lo script attende tre letture identiche del target esterno, esclude tutti i DK configurati e
mostra UID/IEEE candidato. Dopo il backup cerca anche la rappresentazione
little-endian del candidato nella FLASH originale e registra gli offset. Questo
riscontro locale non decodifica il record Zigbee attivo: se disponibile, un
inventario Z2M o l'indirizzo già registrato conferma l'associazione al dispositivo.
La sola lettura identifica un nRF52840, non prova il modello commerciale.

Per ciascun UID crea una sessione in `experiments/provisioning/UID/timestamp/`:

1. ferma il target per due copie coerenti di FLASH1MiB, UICR e FICR;
2. confronta le copie, registra SHA256 e crea `stock-backup.zip`;
3. genera il ripristinatore BLE dal backup del dispositivo, bootstrap firmato e
   bootloader con autorizzazione corrispondente; verifica firme, limiti, LDO e
   controlli noti contro scritture UICR;
4. crea `ble-stock-restore.zip` **prima** di consentire il flash;
5. prepara la coppia main/recupero OTA firmata e qualificata selezionata, con storage inizializzato;
6. mostra il piano e chiede di digitare l'IEEE prima della scrittura;
7. verifica di nuovo UID, snapshot originale, UICR e immagini; programma i settori
   necessari senza recover o mass erase; rilegge tutta FLASH e UICR;
8. richiede l'avvio solo dopo verifica completa, conservando tutti i risultati.

I build specifici del ripristino richiedono alcuni minuti per dispositivo. Il
firmware applicazione è riutilizzato, mentre ripristinatore e autorizzazione sono
specifici per UID e backup. Nessuna chiave privata è inclusa negli ZIP.

## Preparazione e ripresa

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /percorso/release/pair.json --prepare-only
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /percorso/release/pair.json --resume /percorso/sessione
```

`--prepare-only` lascia il target fermato. Anche in caso di errore può rimanere
fermato: il messaggio indica il dossier da controllare. I backup completati non
vengono sovrascritti; i tentativi incompleti vengono conservati in `partial/`.
Ripresa di preparazione/contatto supportata; dopo una scrittura parziale lo
snapshot originale potrebbe non coincidere e la ripresa si ferma per diagnosi,
senza cancellazioni automatiche. Dopo un flash già verificato ma prima del boot
lo script segnala lo stato e lascia decidere l'operatore.

Uso non interattivo, solo dopo autorizzazione del dispositivo specifico:

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --ota-release /percorso/release/pair.json --expected-id UID0:UID1 --yes
```

Non esiste più un firmware predefinito implicito. `--ota-release` seleziona una
coppia verificata tramite il manifest schema1 di `ota_release.py`: main, recovery
e rapporto di qualifica hanno percorsi relativi al manifest e SHA-256 vincolati.
Le firme e i quattro controlli fisici previsti vengono verificati prima di accedere
al DK. Non selezionare automaticamente il file più recente in una cartella.

Il percorso precedente rimane disponibile solo selezionando esplicitamente
`--main /percorso/immagine.hex`: usa il recupero BLE precedente e **non** installa
la coppia necessaria per OTA Zigbee. Non usarlo per aggirare la qualifica OTA.

Per il solo backup, senza scegliere firmware o avviare build:

```sh
python tools/firmware/provision_vimar.py --serial SERIAL_DK --dk-id "$VIMAR_DK_DEVICE_ID" --backup-only
```

Il backup richiede un arresto temporaneo del processore per ottenere copie
coerenti; non programma né cancella FLASH/UICR. Un nuovo tentativo può riprendere
lo stesso dossier con `--resume`, senza sovrascrivere le copie già verificate.

## Configurazione locale e distribuzione del sorgente

Impostare una volta `VIMAR_JLINK_SERIAL` e `VIMAR_OTA_RELEASE` permette di lanciare
lo script senza ripetere quei due argomenti. Lo script non richiede accesso a
Zigbee2MQTT: legge FICR e ricava un IEEE candidato usando la convenzione stock.
Il confronto con un inventario Z2M è una conferma esterna dell'associazione
IEEE/nome, non una dipendenza del backup o un lettore dello storage Zigbee stock.

I percorsi di build e firma sono configurabili tramite variabili d'ambiente:

| Variabile | Contenuto |
| --- | --- |
| `VIMAR_NCS_WORKSPACE` | Workspace SDK inizializzato dal manifest west del progetto |
| `VIMAR_BUILD_PYTHON` | Eseguibile Python con dipendenze di build e imgtool |
| `VIMAR_WEST` | Eseguibile west dell'ambiente SDK |
| `VIMAR_SIGNING_PRIVATE_KEY` | Percorso della propria chiave privata ECDSA-P256 |
| `VIMAR_SIGNING_PUBLIC_KEY` | Percorso della corrispondente chiave pubblica |

Usare percorsi assoluti. I default di build rimangono sotto `work/` e
`firmware/keys/`; nessuna chiave privata viene inclusa negli ZIP. L'ambiente che
esegue lo script richiede `intelhex`; quello di build deve avere anche le
dipendenze della versione SDK fissata in `firmware/west.yml`.
Una release firmata da una chiave diversa richiede il relativo loader: non
mescolare pacchetti di ripristino memorizzati e nuove chiavi. La cache del
ripristino rifiuta una chiave pubblica diversa da quella configurata.

La pubblicazione GitHub del sorgente rimane distinta dalla qualifica hardware.
Prima della pubblicazione occorrono licenza scelta dal titolare, dipendenze e
attribuzioni, prova da checkout pulito e controllo dei file inclusi. Non pubblicare
backup stock, ZIP di ripristino per dispositivo, cookie, credenziali, chiavi
private o dump; `inputs/`, `experiments/` e `work/` restano privati e ignorati.
Lo stato corrente non equivale a una distribuzione pubblica già pronta.

## Verifiche successive e conservazione

Lo script verifica programmazione e avvio richiesto, **non** dichiara verificati
join, avvio autonomo senza debugger, prova fisica della lampada o ripristino BLE
completo. Il join su L1 resta una fase separata con finestra esplicita. Prima di
montare il dispositivo verificare recupero BLE, ingresso e ritorno all'applicazione,
join/rejoin e funzioni fisiche secondo checklist. Per dispositivi già registrati in
Zigbee2MQTT occorrono nuova intervista **e riconfigurazione** del converter
(`bridge/request/device/interview`, poi `bridge/request/device/configure`,
entrambi con `id` uguale al solo IEEE target). La sola intervista può lasciare
il cluster personalizzato non registrato sul server e produrre
`UNSUPPORTED_CLUSTER vimarDimmer`.

Salvare in cloud entrambi gli ZIP della sessione. Contengono dati privati del
dispositivo/rete: conservarli come backup privati. Il README dentro il pacchetto
BLE descrive come entrare nel recupero e riportare l'intera FLASH originale.
Quel ripristino sostituisce il nostro firmware e richiede autorizzazione esplicita.
La presenza del pacchetto validato non equivale a una prova fisica di ripristino
sul singolo dispositivo. Il backup originale rimane anche ripristinabile via SWD.

Dipendenze: OpenOCD, J-Link visibile, SDK/workspace e chiave di sviluppo già presenti,
`work/ncs-venv`, `work/smpclient-venv` con intelhex. Un lock impedisce due istanze
dello script; altri debugger/monitor vanno comunque chiusi.
