# Controlli Zigbee del firmware custom

Il contratto implementato comprende LED separati, ritardi e rampe locali,
limiti di luminosità, quattro modelli timer riutilizzabili e controlli avanzati
in percentuale. Le nuove funzioni richiedono schema 4 o successivo; il
convertitore mantiene la compatibilità con 0.5.5/schema3 e abilita gli attributi
in base allo schema letto dal dispositivo.

Il firmware 1.0.0 è un candidato firmato, con prova runtime limitata sul DK e
tredici flag di qualifica fisica ancora false. Le prove storiche di distribuzione
0.5.4/0.5.5 e gli aggiornamenti successivi restano evidenza per le rispettive
versioni e percorsi; non qualificano automaticamente il nuovo set. Vedere la
[sintesi delle evidenze](research-summary.md). I numeri di test 0.5.6 riportati
più avanti sono risultati storici di quel candidato.

## Default e impostazioni salvate

I valori seguenti sono i default di un Vimar nuovo, senza configurazione
salvata. L’aggiornamento conserva le impostazioni precedenti e assegna soltanto
ai nuovi parametri i rispettivi default. La configurazione del convertitore
legge i valori dal dispositivo, senza scrivere i default. Il simulatore DK
conserva le proprie soglie 250/100/10; il profilo Vimar usa 500/50/3.

| Proprietà | Nome | Default |
|---|---|---|
| `double_click_window_ms` | Finestra doppio clic | `150` ms |
| `long_press_ms` | Soglia pressione lunga | `500` ms |
| `level_step_period_ms` | Intervallo regolazione tenendo premuto | `50` ms |
| `level_step_percent` | Passo di luminosità | `1,2` % (grezzo `3`) |
| `short_press_mode` | Comportamento clic singolo | `symmetric_toggle` |
| `initial_on_delay_ms` | Ritardo prima dell’accensione | `0` ms |
| `rise_transition_ms` | Durata aumento luminosità | `0` ms |
| `fall_transition_ms` | Durata diminuzione luminosità | `0` ms |
| `ramp_start_level_percent` | Livello iniziale rampa OFF→ON | `0` % |
| `ramp_end_level_percent` | Livello finale prima di OFF | `0` % |
| `single_up_action` | Azione clic UP | `toggle` |
| `single_down_action` | Azione clic DOWN | `toggle` |
| `double_up_action` | Azione doppio clic UP | `event_only` |
| `double_down_action` | Azione doppio clic DOWN | `event_only` |
| `timer_1_duration_s` | Durata modello timer 1 | `600` s |
| `timer_2_duration_s` | Durata modello timer 2 | `600` s |
| `timer_3_duration_s` | Durata modello timer 3 | `600` s |
| `timer_4_duration_s` | Durata modello timer 4 | `600` s |
| `custom_power_on_behavior` | Comportamento al ritorno della corrente | `local` |
| `power_on_fallback` | Stato dopo un’interruzione di corrente | `previous` |
| `power_on_level_percent` | Luminosità di accensione dopo blackout | `100` % |
| `zigbee_restore_timeout_s` | Attesa ripristino da Zigbee | `10` s |
| `auto_off_mode` | Spegnimento automatico | `disabled` |
| `auto_off_duration_s` | Tempo prima dello spegnimento automatico | `600` s |
| `output_mode` | Modalità uscita lampada | `dimmable` |
| `reporting_mode` | Origine dello stato riportato | `optimistic` |
| `fixed_level_percent` | Livello nella modalità fissa | `100` % |
| `min_level_percent` | Luminosità minima regolabile | `0,4` % |
| `max_level_percent` | Luminosità massima regolabile | `100` % |
| `led_on_red` | LED a lampada accesa: rosso | `0` |
| `led_on_green` | LED a lampada accesa: verde | `255` |
| `led_on_blue` | LED a lampada accesa: blu | `0` |
| `led_on_intensity` | LED a lampada accesa: intensità | `10` % |
| `led_off_red` | LED a lampada spenta: rosso | `0` |
| `led_off_green` | LED a lampada spenta: verde | `0` |
| `led_off_blue` | LED a lampada spenta: blu | `255` |
| `led_off_intensity` | LED a lampada spenta: intensità | `10` % |
| `led_on_mode` | Intensità LED a lampada accesa | `fixed` |
| `led_on_min_intensity` | Intensità minima LED | `0` % |
| `led_on_max_intensity` | Intensità massima LED | `100` % |

## LED del pulsante

Il convertitore offre due luci a colori nella sezione Configurazione di Home
Assistant: **LED a lampada spenta** (`led_off`) e **LED a lampada accesa**
(`led_on`). Regolano i profili automatici già salvati dal firmware0.5.4/0.5.5;
non serve un nuovo firmware. Entrambi gli endpoint logici usano l’endpoint
fisico1 e non inviano comandi all’uscita della lampada né override temporanei.
La selezione colore HS viene convertita nei tre attributi RGB del profilo.
Le proprietà MQTT sono `state_led_off`, `brightness_led_off`, `color_led_off`
e le equivalenti con suffisso `_led_on`.

Per il profilo a lampada accesa, `led_on_mode` sceglie:

- `fixed`: il cursore modifica `led_on_intensity`.
- `follow_level`: il LED aumenta con il dimming; il cursore modifica il
  **massimo dinamico**, `led_on_max_intensity`.
- `inverse_level`: il LED diminuisce con il dimming; il cursore modifica
  lo stesso **massimo dinamico**.

Il minimo dinamico rimane un controllo separato. Abbassare il cursore sotto il
minimo abbassa prima anche il minimo, con una scrittura separata, per mantenere
sempre minimo≤massimo. Quindi OFF in un modo dinamico porta entrambi a0;
un successivo ON riparte dal massimo10% con minimo0, senza ricordare il
precedente intervallo. Nel modo fisso e nel profilo spento, OFF imposta
l’intensità a0 e ON, se necessario, riparte da10%. Un profilo RGB nero legacy
viene riportato al bianco soltanto da un esplicito ON/TOGGLE verso ON.

In `follow_level` la formula firmware è
`min + ((level−1)×(max−min)+126)/253`, con divisione intera: livello1→min,
livello254→max. `inverse_level` specchia il risultato tra min e max. Il livello
è quello dello stato software accettato della lampada, non una misura fisica.
I cursori luce Zigbee2MQTT mostrano0–100%, come Home Assistant. I nuovi
alias MQTT sono `brightness_percent`, `brightness_percent_led_off` e
`brightness_percent_led_on` (anche `_led` per l’override avanzato). I vecchi
`brightness`/`brightness_led_*` rimangono su scala0–254 per compatibilità;
non inviare contemporaneamente il valore percentuale e quello grezzo.
Home Assistant continua a usare la scala254 nel protocollo JSON e mostra
la percentuale nell’interfaccia: cambiare soltanto `brightness_scale` a100
sarebbe scorretto. Il livello lampada1 corrisponde a0,4%; il livello127 a50%.
Gli attributi LED firmware restano su scala0–100%, con arrotondamento.
Gli attributi firmware conservano la propria scala grezza. I controlli avanzati
di luminosità ora espongono alias percentuali nell’interfaccia; i vecchi nomi
MQTT grezzi conservano get/set senza controlli numerici duplicati.
In modalità dinamica l’intensità fissa resta salvata ma non viene applicata.

Il vecchio endpoint `led` resta disponibile come **LED override manuale
avanzato**, mantenendo ID e proprietà `state_led`, `brightness_led`, `color_led`
e `effect_led` per le automazioni esistenti. `effect_led=automatic` rimuove
l’override; `steady` e `slow_blink` lo applicano senza scadenza. Il comando
`led_override` conserva la durata configurabile. Le letture runtime descrivono
l’uscita risolta dal controller software, separata dai due profili salvati.
Priorità: errore, override, indicazione temporanea, profilo automatico.
Modificare un profilo non rimuove un override già attivo.

Per un’automazione di prossimità, pubblicare sul topic
`zigbee2mqtt/NOME_DISPOSITIVO/set`, per esempio:

```json
{"led_override":{"red":255,"green":160,"blue":0,"intensity":25,"effect":"steady","duration_ms":15000}}
```

Il LED diventa ambra per 15 secondi, poi torna al comportamento automatico.
Il comando modifica solo lo stato runtime, senza scrivere in flash né alterare
i profili salvati. `duration_ms:0` mantiene l’override fino alla cancellazione;
`{"clear_led_override":true}` lo rimuove subito. Non cambia l’uscita lampada.


I parametri legacy e i vecchi canali RGB/intensità conservano get/set MQTT.
I canali LED RGB/intensità restano visibili in Zigbee2MQTT; i livelli lampada
grezzi sono sostituiti nell’interfaccia dagli alias percentuali. Le nuove discovery dei canali legacy e della luce
runtime sono disabilitate di default. Per eliminare i numeri duplicati anche
nelle installazioni esistenti, applicare nelle opzioni del singolo dispositivo:

```yaml
homeassistant:
  led_on_red: null
  led_on_green: null
  led_on_blue: null
  led_on_intensity: null
  led_off_red: null
  led_off_green: null
  led_off_blue: null
  led_off_intensity: null
  # Solo se la vecchia luce runtime non è usata da automazioni HA:
  light_led: null
  effect_led: null
```

Le chiavi sono gli object_id senza prefisso `number_`. La discovery di queste
vecchie entità viene rimossa; eventuali automazioni HA che le usavano vanno
migrate ai profili o ai comandi MQTT. La luce runtime `light_led` può essere rimossa dalla discovery con le ultime
due esclusioni, senza modificare i comandi MQTT. Se occorre mantenerla: `enabled_by_default=false` non disabilita entità già registrate.
Per avere soltanto due luci LED visibili senza interrompere le automazioni
runtime, nascondere quella avanzata nel registro entità HA, mantenendola
abilitata. Il convertitore da solo non può imporre questa scelta su un’entità
esistente. La configurazione HA del singolo dispositivo prevale sulla discovery.

## Ritardo, rampe e stato

I comandi normali di Zigbee2MQTT usano `setOutput`, comando custom 0x05, per
applicare i default locali. Il ritardo iniziale vale per OFF→ON; la rampa di
salita vale per aumenti e la discesa per diminuzioni e OFF. Zero significa
applicazione immediata. Una richiesta successiva sostituisce la rampa in corso;
un OFF cancella una precedente accensione ancora in attesa.

I comandi Zigbee2MQTT con `transition` esplicita conservano il percorso standard
ZBOSS. I campioni di livello di quel percorso e la regolazione tenendo premuto
non aggiungono una seconda rampa locale. I comandi di livello standard ricevuti
direttamente da binding/scene seguono il percorso ZBOSS. I default locali non
rallentano il ripristino iniziale o il passaggio al recupero.

Lo stato standard ON/OFF e brightness viene pubblicato quando il comando è
accettato, indipendentemente dal ritardo o dalla rampa. `applied_output_on`,
`applied_output_level` e `transition_active` descrivono l’ultimo comando di
uscita stimato e l’avanzamento locale. Non costituiscono conferma fisica della
lampada; gli errori di applicazione correggono lo stato e riportano un fault.

`min_level` e `max_level` limitano il livello in modalità dimmable, senza impedire
OFF. `fixed_level` resta indipendente. In modalità fissa le pressioni lunghe
emettono eventi ma non accendono né regolano la lampada. Le coppie min/max
inviate insieme vengono ordinate in richieste separate per non attraversare
intervalli invalidi; una perdita di connessione può lasciare una coppia
intermedia valida, da rileggere prima di ritentare.

## Recupero e compatibilità

Le impostazioni v4 leggono i record v1/v2/v3, conservando le scelte salvate.
Il firmware 0.5.5 non decodifica il record v4: un downgrade non conserva le
impostazioni salvate nel nuovo formato. La compatibilità descritta qui vale
per l’aggiornamento in avanti. Prima del recupero BLE viene
salvata subito la configurazione e l’ultima luminosità logica, anche dentro la
finestra di salvataggio differito. Se il salvataggio fallisce, il riavvio viene
annullato. Il formato legacy del passaggio warm resta invariato: con uscita OFF
si conserva la luminosità memorizzata; con uscita ON viene preservata l’uscita
esatta corrente. Una rampa interrotta dal recupero non riparte automaticamente.

Il convertitore mostra sul Vimar soltanto dimmable/fixed_level e reporting
optimistic; acknowledged/physical/stock_switch restano opzioni del simulatore
quando supportate. I comandi booleani con false non eseguono azioni.

## Verifica

Per il candidato 0.5.6 passano 44 test Node del convertitore e le suite firmware
host (237 test Python e 18 test C). Il pacchetto misura 253729 byte contro
253952 byte disponibili: margine 223 byte. Queste verifiche non sostituiscono
la prova fisica. Le prove OTA/avvio e la rilettura dei controlli, compresa
l’entità LED separata, completate sui tre dimmer riguardano le release
precedenti 0.5.4/0.5.5. Restano le prove visive delle rampe
configurate e la verifica dell’entità direttamente nell’interfaccia Home Assistant.
La qualifica con interruzione fisica dell’alimentazione durante l’installazione
resta separata e non è stata completata.

## Identificativo firmware Zigbee — dalla release 0.5.5

La release0.5.5 inizializza Basic `SWBuildID` (`0x4000`) con
`APP_VERSION_STRING`, generato da Zephyr dal file `VERSION`. Il controllo
in compilazione limita il testo a16caratteri. Zigbee2MQTT legge ora
`software_build_id: 0.5.5` sui tre dimmer installati, verificato sia nelle
risposte finali OTA sia dopo l’avvio. Modello, produttore e IEEE conservati.

La modifica non era inclusa nei pacchetti congelati0.5.4, che restano invariati.
Build0.5.5 firmata e verificata separatamente; dettagli
nei rapporti locali della prova 0.5.5.

## Versioni OTA mostrate da Zigbee2MQTT 2.14.1

`installed_version` è la versione OTA installata; `latest_version` è quella
individuata dall’ultima ricerca. Dopo una ricerca con immagine nuova disponibile
devono essere diverse; dopo l’aggiornamento riuscito è corretto che coincidano.
Sono numeri del formato OTA, distinti dal testo Basic `SWBuildID`.

Durante un aggiornamento avviato caricando direttamente `hex`, Z2M conserva nei
messaggi di avanzamento le versioni precedentemente in cache, senza aggiornare
`latest_version` dall’immagine scelta. Nel nostro passaggio 0.5.3→0.5.4 i log
riportavano entrambe 328448 durante il trasferimento; la risposta finale corretta
riporta `from.file_version=328448` e `to.file_version=328704`. Non significa che
fosse stata inviata la stessa versione. La verifica successiva riporta 328704.

Fonte primaria: Zigbee2MQTT tag 2.14.1,
https://github.com/Koenkk/zigbee2mqtt/blob/2.14.1/lib/extension/otaUpdate.ts,
metodi `#getEntityPublishPayload`, `#update` e ramo `payload.hex`.
Per la distribuzione generale resta da predisporre un catalogo OTA privato e
la ricerca dell’immagine prima del trasferimento, così che l’interfaccia mostri
la versione candidata. Non vengono falsificati attributi del dispositivo per
correggere il valore in cache lato Z2M.

## Controlli schema 4 — contratto implementato

Questi controlli richiedono firmware schema 4 o successivo e il convertitore
aggiornato. Il contratto è implementato; la qualifica fisica dipende dalla
versione esatta. Il candidato 1.0.0 non è qualificato per la flotta. Il
convertitore legge prima `schema_version`: con il firmware 0.5.5/schema3
continua a leggere soltanto gli attributi precedenti e nasconde le nuove
azioni e i nuovi parametri.

Quattro modelli timer indipendenti hanno durata iniziale600s ciascuno:
`timer_1_duration_s`, `timer_2_duration_s`, `timer_3_duration_s`,
`timer_4_duration_s`. Ogni azione può riutilizzare qualsiasi modello.
`timed_on_1`…`timed_on_4` accendono sempre e riavviano il conto alla rovescia;
`timed_toggle_1`…`timed_toggle_4` accendono da OFF e avviano il timer scelto,
oppure spengono da ON e cancellano il timer. Il modello1 usa lo stesso
attributo0x0200 di `timer_duration_s`: il vecchio nome MQTT e `timed_on`
(valore wire3) rimangono compatibili. La selezione legacy `timed_on` resta
visibile anche nello schema 4, senza rimappare le azioni già salvate. I nuovi valori wire sono7–10 e11–14;
i modelli2–4 usano0x0207–0x0209, UINT32. Non vengono scritti default dal
convertitore durante configure.

`event_only` pubblica l’evento della gesture classificata senza modificare la
lampada. `disabled` sopprime anche quell’evento Zigbee; non equivale a
`event_only`. Le azioni singole personalizzate richiedono
`short_press_mode=custom`.

I controlli avanzati di luminosità usano percentuali nell’interfaccia:
`min_level_percent`, `max_level_percent`, `fixed_level_percent`,
`power_on_level_percent`, `level_step_percent`. I nomi MQTT grezzi precedenti
rimangono get/set ma non sono esposti come numeri duplicati. Il passo varia
da0,4% a19,7%, equivalente a1–50 sulla scala254. La conversione arrotonda
al livello intero più vicino; le risposte riportano anche il valore grezzo.
Non inviare insieme nome grezzo e alias percentuale.

Le nuove proprietà `ramp_start_level_percent` e `ramp_end_level_percent`
usano0–100%, conservando gli alias MQTT grezzi `ramp_start_level` e
`ramp_end_level` su0–254 (attributi0x0108/0x0109, UINT8).
Il default di entrambe è0. I dispositivi nuovi usano inoltre
`power_on_fallback=previous`; gli aggiornamenti conservano il comportamento
precedentemente salvato e assegnano600s ai nuovi modelli timer.

Per le vecchie entità numeriche già registrate in Home Assistant potrebbe
servire eliminare la discovery precedente o disabilitarle nel registro:
l’aggiornamento del convertitore non modifica da solo le preferenze del
registro entità.

Con una rampa di durata non nulla, `ramp_start_level_percent` è il livello
iniziale di OFF→ON, limitato al target:0 parte da spento.
`ramp_end_level_percent` è l’ultimo livello acceso della discesa prima di OFF,
limitato al livello iniziale:0 termina a spento. Durante queste rampe il
livello può scendere sotto `min_level`; la soglia fisica minima non è ancora
calibrata. La modalità `fixed_level` conserva il livello fisso senza questo
percorso di rampa.
