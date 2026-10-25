import {Zcl} from 'zigbee-herdsman';
import * as exposes from 'zigbee-herdsman-converters/lib/exposes';
import * as m from 'zigbee-herdsman-converters/lib/modernExtend';

const CLUSTER_ID = 0xfc00;
const CLUSTER_NAME = 'vimarDimmer';

const ACTIONS = ['toggle', 'on', 'off', 'timed_on', 'event_only', 'disabled', 'bypass_on', ...[1, 2, 3, 4].map((n) => `timed_on_${n}`), ...[1, 2, 3, 4].map((n) => `timed_toggle_${n}`)];
const SETTING_PRESENTATION = {
    initial_on_delay_ms: ['Ritardo prima dell’accensione', 'Attesa locale prima di iniziare ad accendere; lo stato Zigbee viene aggiornato subito. Zero elimina l’attesa.', 0],
    rise_transition_ms: ['Durata aumento luminosità', 'Rampa locale verso un livello maggiore, inclusa l’accensione. Zero applica subito. Le transizioni di livello Zigbee esplicite hanno precedenza.', 0],
    fall_transition_ms: ['Durata diminuzione luminosità', 'Rampa locale verso un livello minore, incluso lo spegnimento. Zero applica subito. Le transizioni di livello Zigbee esplicite hanno precedenza.', 0],
    min_level: ['Luminosità minima regolabile', 'Limite inferiore in modalità dimmable, scala 1–254. Non impedisce lo spegnimento.', 1],
    max_level: ['Luminosità massima regolabile', 'Limite superiore in modalità dimmable, scala 1–254. Il livello fisso ha un’impostazione indipendente.', 254],
    double_click_window_ms: ['Finestra doppio clic', 'Tempo massimo fra due pressioni sullo stesso lato. Ritarda la classificazione del clic singolo.', 150],
    long_press_ms: ['Soglia pressione lunga', 'Tempo di pressione necessario per iniziare la regolazione locale della luminosità.', 500],
    level_step_period_ms: ['Intervallo regolazione tenendo premuto', 'Tempo tra incrementi di luminosità durante una pressione lunga.', 50],
    level_step: ['Passo di luminosità', 'Variazione su scala 1–254 per ogni incremento durante una pressione lunga.', 3],
    short_press_mode: ['Comportamento clic singolo', 'symmetric_toggle: entrambi i lati commutano; directional: UP accende, DOWN spegne; custom: usa le azioni separate.', 'symmetric_toggle'],
    single_up_action: ['Azione clic UP', 'Azione locale del clic UP, usata solo quando il comportamento clic singolo è custom.', 'toggle'],
    single_down_action: ['Azione clic DOWN', 'Azione locale del clic DOWN, usata solo quando il comportamento clic singolo è custom.', 'toggle'],
    double_up_action: ['Azione doppio clic UP', 'Azione locale del doppio clic UP; event_only invia soltanto un evento per le automazioni.', 'event_only'],
    double_down_action: ['Azione doppio clic DOWN', 'Azione locale del doppio clic DOWN; event_only invia soltanto un evento per le automazioni.', 'event_only'],
    timer_duration_s: ['Durata accensione temporizzata', 'Durata del conto alla rovescia avviato dall’azione timed_on; un nuovo timed_on lo riavvia.', 600],
    custom_power_on_behavior: ['Comportamento al ritorno della corrente', 'local applica subito la scelta locale; await_zigbee attende un comando fino alla scadenza di ripristino.', 'local'],
    power_on_fallback: ['Stato dopo un’interruzione di corrente', 'Stato locale all’avvio o alla scadenza dell’attesa Zigbee: spento, acceso o stato precedente.', 'previous'],
    power_on_level: ['Luminosità di accensione dopo blackout', 'Livello usato quando il ripristino richiede l’accensione; scala 1–254.', 254],
    zigbee_restore_timeout_s: ['Attesa ripristino da Zigbee', 'Tempo massimo di attesa di un comando dopo l’avvio quando è selezionato await_zigbee.', 10],
    auto_off_mode: ['Spegnimento automatico', 'disabled: disattivato; every_on: avvio da ogni comando ON; physical_on_only: avvio soltanto dai pulsanti.', 'disabled'],
    auto_off_duration_s: ['Tempo prima dello spegnimento automatico', 'Durata del conto alla rovescia automatico. OFF lo cancella; bypass_on lo esclude fino al prossimo OFF.', 600],
    output_mode: ['Modalità uscita lampada', 'dimmable regola la luminosità; fixed_level usa il livello fisso e lascia le pressioni lunghe come soli eventi.', 'dimmable'],
    reporting_mode: ['Origine dello stato riportato', 'Sul Vimar è disponibile optimistic: stato stimato dai comandi applicati, senza misura della luce o conferma dal circuito di potenza.', 'optimistic'],
    fixed_level: ['Livello nella modalità fissa', 'Luminosità usata per ogni accensione quando la modalità uscita è fixed_level; 254 corrisponde al massimo.', 254],
    led_on_mode: ['Intensità LED a lampada accesa', 'fixed: intensità fissa, regolata dalla luce LED a lampada accesa. follow_level: aumenta con il dimming; inverse_level: diminuisce. Nei due modi dinamici il cursore della luce regola il massimo.', 'fixed'],
    led_on_min_intensity: ['LED acceso: minimo dinamico', 'Intensità al minimo dimming in follow_level, al massimo dimming in inverse_level. Non deve superare il massimo dinamico; abbassare il cursore sotto questo valore riduce anche il minimo.', 0],
    led_on_max_intensity: ['LED acceso: massimo dinamico', 'Limite superiore nei modi follow_level e inverse_level; coincide con il cursore della luce LED a lampada accesa nei modi dinamici. Non usato in fixed.', 100],
};
for (const [profile, state, rgb] of [['on', 'accesa', [0, 255, 0]], ['off', 'spenta', [0, 0, 255]]]) {
    for (const [i, color] of ['red', 'green', 'blue'].entries()) SETTING_PRESENTATION[`led_${profile}_${color}`] =
        [`LED a lampada ${state}: ${['rosso', 'verde', 'blu'][i]}`, `Componente del colore automatico del LED a lampada ${state}, scala 0–255.`, rgb[i]];
    SETTING_PRESENTATION[`led_${profile}_intensity`] = [`LED a lampada ${state}: intensità`, `Intensità del profilo automatico LED a lampada ${state}. Un override temporaneo ha priorità.`, 10];
}
for (const name of ['single_up_action', 'single_down_action', 'double_up_action', 'double_down_action']) {
    SETTING_PRESENTATION[name][1] += ' event_only pubblica l’evento classificato senza agire sulla lampada; disabled sopprime anche quell’evento Zigbee. timed_on è l’alias legacy del timer 1: accende e riavvia il conto alla rovescia senza rimappare la scelta salvata. timed_on_N accende e riavvia il timer N; timed_toggle_N accende da OFF, spegne e cancella da ON.';
}
SETTING_PRESENTATION.ramp_start_level = ['Luminosità iniziale rampa', 'Livello iniziale della rampa OFF→ON: zero parte da spento; un valore maggiore parte da questo livello, limitato al target. Solo con rampa non nulla; soglia fisica minima non calibrata.', 0];
SETTING_PRESENTATION.ramp_end_level = ['Luminosità finale rampa', 'Ultimo livello acceso prima di OFF: zero termina a spento; un valore maggiore termina qui prima dello spegnimento, limitato al livello iniziale. Solo con rampa non nulla; soglia fisica minima non calibrata.', 0];
for (const n of [2, 3, 4]) SETTING_PRESENTATION[`timer_${n}_duration_s`] = [`Durata timer ${n}`, 'Modello riutilizzabile dalle azioni dei pulsanti.', 600];
const setting = (name, zclName, ID, type, options = {}) => ({
    name, zclName, ID, type, access: 'STATE_SET_GET', category: 'config',
    label: SETTING_PRESENTATION[name]?.[0], default: SETTING_PRESENTATION[name]?.[2],
    description: `${SETTING_PRESENTATION[name]?.[1] ?? name} Default: ${SETTING_PRESENTATION[name]?.[2]}.`, ...options,
});
const diagnostic = (name, zclName, ID, type, options = {}) => ({
    name, zclName, ID, type, access: 'STATE_GET', category: 'diagnostic',
    description: `Current ${name.replaceAll('_', ' ')}`, writable: false, ...options,
});

const ATTRIBUTE_METADATA = Object.freeze([
    diagnostic('schema_version', 'schemaVersion', 0x0000, 'numeric', {zclType: 'u16'}),
    diagnostic('capabilities', 'capabilities', 0x0001, 'numeric', {zclType: 'u32'}),
    setting('double_click_window_ms', 'doubleClickWindowMs', 0x0100, 'numeric', {min: 50, max: 600, unit: 'ms', zclType: 'u16'}),
    setting('long_press_ms', 'longPressMs', 0x0101, 'numeric', {min: 150, max: 2000, unit: 'ms', zclType: 'u16'}),
    setting('level_step_period_ms', 'levelStepPeriodMs', 0x0102, 'numeric', {min: 50, max: 500, unit: 'ms', zclType: 'u16'}),
    setting('level_step', 'levelStep', 0x0103, 'numeric', {min: 1, max: 50}),
    setting('short_press_mode', 'shortPressMode', 0x0104, 'enum', {values: ['directional', 'symmetric_toggle', 'custom']}),
    setting('initial_on_delay_ms', 'initialOnDelayMs', 0x0105, 'numeric', {min: 0, max: 60000, unit: 'ms', zclType: 'u32'}),
    setting('rise_transition_ms', 'riseTransitionMs', 0x0106, 'numeric', {min: 0, max: 60000, unit: 'ms', zclType: 'u32'}),
    setting('fall_transition_ms', 'fallTransitionMs', 0x0107, 'numeric', {min: 0, max: 60000, unit: 'ms', zclType: 'u32'}),
    setting('ramp_start_level', 'rampStartLevel', 0x0108, 'numeric', {min: 0, max: 254, minSchema: 4}),
    setting('ramp_end_level', 'rampEndLevel', 0x0109, 'numeric', {min: 0, max: 254, minSchema: 4}),
    setting('single_up_action', 'singleUpAction', 0x0110, 'enum', {values: ACTIONS}),
    setting('single_down_action', 'singleDownAction', 0x0111, 'enum', {values: ACTIONS}),
    setting('double_up_action', 'doubleUpAction', 0x0112, 'enum', {values: ACTIONS}),
    setting('double_down_action', 'doubleDownAction', 0x0113, 'enum', {values: ACTIONS}),
    setting('timer_duration_s', 'timerDurationS', 0x0200, 'numeric', {min: 1, max: 86400, unit: 's', zclType: 'u32'}),
    setting('custom_power_on_behavior', 'powerOnBehavior', 0x0201, 'enum', {values: ['local', 'await_zigbee']}),
    setting('power_on_fallback', 'powerOnFallback', 0x0202, 'enum', {values: ['off', 'on', 'previous']}),
    setting('power_on_level', 'powerOnLevel', 0x0203, 'numeric', {min: 1, max: 254}),
    setting('zigbee_restore_timeout_s', 'zigbeeRestoreTimeoutS', 0x0204, 'numeric', {min: 1, max: 300, unit: 's', zclType: 'u16'}),
    setting('auto_off_mode', 'autoOffMode', 0x0205, 'enum', {values: ['disabled', 'every_on', 'physical_on_only']}),
    setting('auto_off_duration_s', 'autoOffDurationS', 0x0206, 'numeric', {min: 1, max: 86400, unit: 's', zclType: 'u32'}),
    ...[2, 3, 4].map((n) => setting(`timer_${n}_duration_s`, `timer${n}DurationS`, 0x0205 + n, 'numeric', {min: 1, max: 86400, unit: 's', zclType: 'u32', minSchema: 4})),
    setting('output_mode', 'outputMode', 0x0300, 'enum', {values: ['dimmable', 'fixed_level', 'stock_switch']}),
    setting('reporting_mode', 'reportingMode', 0x0301, 'enum', {values: ['optimistic', 'acknowledged', 'physical']}),
    setting('fixed_level', 'fixedLevel', 0x0302, 'numeric', {min: 1, max: 254}),
    setting('min_level', 'minLevel', 0x0303, 'numeric', {min: 1, max: 254}),
    setting('max_level', 'maxLevel', 0x0304, 'numeric', {min: 1, max: 254}),
    setting('led_on_red', 'ledOnR', 0x0400, 'numeric', {min: 0, max: 255}),
    setting('led_on_green', 'ledOnG', 0x0401, 'numeric', {min: 0, max: 255}),
    setting('led_on_blue', 'ledOnB', 0x0402, 'numeric', {min: 0, max: 255}),
    setting('led_on_intensity', 'ledOnIntensity', 0x0403, 'numeric', {min: 0, max: 100, unit: '%'}),
    setting('led_off_red', 'ledOffR', 0x0404, 'numeric', {min: 0, max: 255}),
    setting('led_off_green', 'ledOffG', 0x0405, 'numeric', {min: 0, max: 255}),
    setting('led_off_blue', 'ledOffB', 0x0406, 'numeric', {min: 0, max: 255}),
    setting('led_off_intensity', 'ledOffIntensity', 0x0407, 'numeric', {min: 0, max: 100, unit: '%'}),
    setting('led_on_mode', 'ledOnMode', 0x0408, 'enum', {values: ['fixed', 'follow_level', 'inverse_level']}),
    setting('led_on_min_intensity', 'ledOnMin', 0x0409, 'numeric', {min: 0, max: 100, unit: '%'}),
    setting('led_on_max_intensity', 'ledOnMax', 0x040a, 'numeric', {min: 0, max: 100, unit: '%'}),
    diagnostic('led_runtime_red', 'ledRuntimeR', 0x0500, 'numeric', {min: 0, max: 255}),
    diagnostic('led_runtime_green', 'ledRuntimeG', 0x0501, 'numeric', {min: 0, max: 255}),
    diagnostic('led_runtime_blue', 'ledRuntimeB', 0x0502, 'numeric', {min: 0, max: 255}),
    diagnostic('led_runtime_intensity', 'ledRuntimeIntensity', 0x0503, 'numeric', {min: 0, max: 100, unit: '%'}),
    diagnostic('led_runtime_effect', 'ledRuntimeEffect', 0x0504, 'enum', {values: ['steady', 'slow_blink']}),
    diagnostic('led_override_active', 'ledOverrideActive', 0x0505, 'binary', {zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('target_state', 'targetOn', 0x0600, 'binary', {zclType: 'bool', valueOn: 'ON', valueOff: 'OFF'}),
    diagnostic('target_level', 'targetLevel', 0x0601, 'numeric', {min: 0, max: 254}),
    diagnostic('timer_active', 'timerActive', 0x0602, 'binary', {zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('restore_pending', 'restorePending', 0x0603, 'binary', {zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('fault_code', 'faultCode', 0x0604, 'numeric', {min: 0, max: 255}),
    diagnostic('auto_off_bypassed', 'autoOffBypassed', 0x0605, 'binary', {zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('timer_remaining_s', 'timerRemainingS', 0x0606, 'numeric', {unit: 's', zclType: 'u32'}),
    diagnostic('applied_output_on', 'appliedOutputOn', 0x0607, 'binary', {zclType: 'bool', valueOn: 'ON', valueOff: 'OFF',
        description: 'Stato dell’ultimo comando di uscita applicato; stima software, senza misura della lampada'}),
    diagnostic('applied_output_level', 'appliedOutputLevel', 0x0608, 'numeric', {min: 0, max: 254,
        description: 'Livello dell’ultimo comando di uscita applicato durante la rampa; zero quando spento, senza misura fisica'}),
    diagnostic('transition_active', 'transitionActive', 0x0609, 'binary', {zclType: 'bool', valueOn: true, valueOff: false,
        description: 'Ritardo o rampa locale in corso; lo stato standard Zigbee descrive già il comando accettato'}),
    diagnostic('p031_enabled', 'p031Enabled', 0x0700, 'binary', {minSchema: 5, label: 'Monitor P0.31 attivo', zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('p031_raw_level', 'p031RawLevel', 0x0701, 'numeric', {minSchema: 5, label: 'Livello elettrico P0.31', min: 0, max: 1, description: 'Livello digitale; consultare anche validità e qualificazione. HIGH non identifica da solo un guasto termico o di corrente.'}),
    diagnostic('p031_sample_valid', 'p031SampleValid', 0x0702, 'binary', {minSchema: 5, label: 'Campione P0.31 valido', zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('p031_low_qualified', 'p031LowQualified', 0x0703, 'binary', {minSchema: 5, label: 'LOW P0.31 qualificato', zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('p031_signal_inhibit', 'p031SignalInhibit', 0x0704, 'binary', {minSchema: 5, label: 'Inibizione dal segnale P0.31', zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('p031_output_blocked', 'p031OutputBlocked', 0x0705, 'binary', {minSchema: 5, label: 'Uscita bloccata dalla protezione', zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('p031_notification', 'p031Notification', 0x0706, 'binary', {minSchema: 5, label: 'Segnalazione P0.31 memorizzata', zclType: 'bool', valueOn: true, valueOff: false}),
    diagnostic('p031_trip_count', 'p031TripCount', 0x0707, 'numeric', {minSchema: 5, label: 'Interventi P0.31', zclType: 'u32'}),
    diagnostic('p031_max_sample_gap_ms', 'p031MaxSampleGapMs', 0x0708, 'numeric', {minSchema: 5, label: 'Massimo intervallo tra campioni P0.31', zclType: 'u32', unit: 'ms'}),
    diagnostic('p031_monitor_uptime_s', 'p031MonitorUptimeS', 0x0709, 'numeric', {minSchema: 5, label: 'Tempo attivo del monitor P0.31', zclType: 'u32', unit: 's'}),
    diagnostic('last_boot_reason', 'lastBootReason', 0x070a, 'enum', {minSchema: 5, label: 'Ultimo ingresso nel firmware', values: ['none', 'recovery_unknown', 'zigbee_recovery_request', 'physical_chord_request', 'ota_install_request', 'ota_completed', 'main_start', 'boot_selector_observed'], description: 'Ingresso e precedente richiesta registrata, se disponibile; una richiesta non dimostra da sola la causa del reset.'}),
    diagnostic('last_reset_flags', 'lastResetFlags', 0x070b, 'numeric', {minSchema: 5, label: 'Flag hardware del riavvio', zclType: 'u32', description: 'Flag raw disponibili all’ingresso; il bootloader può averli già modificati. Zero non prova un blackout.'}),
    diagnostic('boot_sequence', 'bootSequence', 0x070c, 'numeric', {minSchema: 5, label: 'Numero progressivo avvii', zclType: 'u32'}),
    diagnostic('ota_contract', 'otaContract', 0x070d, 'text', {minSchema: 6, zclType: 'octetStr', label: 'Compatibilità aggiornamento', description: 'Contratto atomico di sola lettura: versione, campione RAM e digest della recovery verificata. Il campione non identifica la causa di un reset.'}),
    diagnostic('fault_diagnostic_status', 'faultDiagStatus', 0x0800, 'numeric', {minSchema: 7, zclType: 'u32', label: 'Stato diagnostica riavvii', description: 'Bit: 1 cattura pronta; 2 rapporto presente; 4 salvato; 8 errore memoria; 16 cattura precedente da conservare; 32 rapporto di una build precedente, non attribuito alla build corrente.'}),
    ...Array.from({length: 8}, (_, i) => diagnostic(`fault_diagnostic_${i}`, `faultDiag${i}`, 0x0801+i, 'text',
        {minSchema: 7, zclType: 'octetStr', internal: true, description: 'Frammento diagnostico di sola lettura, formato binario versionato con CRC e identità build.'})),
]);

const ATTRIBUTE_IDS = Object.freeze(Object.fromEntries(ATTRIBUTE_METADATA.map((item) => [item.name, item.ID])));
const byPublicName = new Map(ATTRIBUTE_METADATA.map((item) => [item.name, item]));
const byZclName = new Map(ATTRIBUTE_METADATA.map((item) => [item.zclName, item]));

const PERCENT_SETTINGS = ['min_level', 'max_level', 'fixed_level', 'power_on_level', 'level_step', 'ramp_start_level', 'ramp_end_level'];
const aliases = new Map(PERCENT_SETTINGS.map((name) => [`${name}_percent`, name]));
aliases.set('timer_1_duration_s', 'timer_duration_s');
function schemaVersion(device) {
    return Number(device?.getEndpoint?.(1)?.getClusterAttributeValue?.(CLUSTER_NAME, 'schemaVersion') ?? 0);
}
const toPercent = (value) => Math.round(value * 1000 / 254) / 10;
function publicState(metadata, value) {
    const decoded=decodeValue(metadata,value);
    if((metadata.name==='ota_contract' || metadata.internal) && decoded===undefined)return {};
    const result = {[metadata.name]: decoded};
    if (PERCENT_SETTINGS.includes(metadata.name)) result[`${metadata.name}_percent`] = toPercent(value);
    if (metadata.name === 'timer_duration_s') result.timer_1_duration_s = value;
    return result;
}

function encodeValue(metadata, value) {
    if (metadata.type === 'enum') {
        const encoded = metadata.values.indexOf(value);
        if (encoded < 0) throw new RangeError(`${metadata.name} is invalid`);
        return encoded;
    }
    if (metadata.type === 'numeric') {
        if (!Number.isInteger(value)) throw new RangeError(`${metadata.name} must be an integer`);
        if (metadata.min !== undefined && (value < metadata.min || value > metadata.max)) {
            throw new RangeError(`${metadata.name} must be ${metadata.min}..${metadata.max}`);
        }
    }
    return value;
}

function decodeValue(metadata, value) {
    if(metadata.internal) return Buffer.isBuffer(value) && value.length===32 ? value.toString('hex') : undefined;
    if (metadata.name === 'ota_contract') {
        if (!Buffer.isBuffer(value) || value.length !== 43 || value[0] !== 1 || value[1] !== 2 || ![0, 1].includes(value[2])) return undefined;
        if (value[2] === 0 && value.subarray(11).some((byte) => byte !== 0)) return undefined;
        return 'v1:' + value.toString('base64url');
    }
    if (metadata.type === 'enum') return metadata.values[Number(value)];
    if (metadata.type === 'binary') return value ? metadata.valueOn : metadata.valueOff;
    return value;
}

function ledOverridePayload(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('led_override must be an object');
    const fields = {red: [0, 255], green: [0, 255], blue: [0, 255], intensity: [0, 100], duration_ms: [0, 0xffffffff]};
    const allowed = new Set([...Object.keys(fields), 'effect']);
    for (const key of Object.keys(input)) if (!allowed.has(key)) throw new RangeError(`unsupported led_override key: ${key}`);
    for (const [key, [min, max]] of Object.entries(fields)) {
        if (!Number.isInteger(input[key]) || input[key] < min || input[key] > max) throw new RangeError(`${key} must be ${min}..${max}`);
    }
    const effects = ['steady', 'slow_blink'];
    const effect = effects.indexOf(input.effect);
    if (effect < 0) throw new RangeError('effect is invalid');
    return {r: input.red, g: input.green, b: input.blue, intensity: input.intensity, effect, durationMs: input.duration_ms};
}

const LED_RUNTIME_ATTRIBUTES = ['ledRuntimeR', 'ledRuntimeG', 'ledRuntimeB',
    'ledRuntimeIntensity', 'ledRuntimeEffect', 'ledOverrideActive'];

function rgbToHs(r, g, b) {
    const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
    let hue = 0;
    if (delta) {
        if (max === r) hue = ((g - b) / delta) % 6;
        else if (max === g) hue = (b - r) / delta + 2;
        else hue = (r - g) / delta + 4;
        hue = (hue * 60 + 360) % 360;
    }
    return {hue: Math.round(hue * 100) / 100, saturation: max ? Math.round(delta / max * 10000) / 100 : 0};
}

function hsToRgb(color) {
    const h = color?.hue ?? color?.h, s = color?.saturation ?? color?.s;
    if (!Number.isFinite(h) || h < 0 || h > 360 || !Number.isFinite(s) || s < 0 || s > 100) {
        throw new RangeError('LED color requires hue 0..360 and saturation 0..100');
    }
    const chroma = s / 100, x = chroma * (1 - Math.abs((h / 60) % 2 - 1));
    const sectors = [[chroma, x, 0], [x, chroma, 0], [0, chroma, x], [0, x, chroma], [x, 0, chroma], [chroma, 0, x]];
    return sectors[Math.floor(h / 60) % 6].map((v) => Math.round((v + 1 - chroma) * 255));
}

function percentageMessage(message) {
    if (message.brightness_percent === undefined) return message;
    if (message.brightness !== undefined) throw new Error('Specify brightness or brightness_percent, not both');
    const percent = message.brightness_percent;
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) throw new RangeError('brightness_percent must be 0..100');
    const result = {...message, brightness: Math.round(percent * 254 / 100)};
    delete result.brightness_percent;
    return result;
}

function ledLightState(data) {
    if (!LED_RUNTIME_ATTRIBUTES.every((name) => data[name] !== undefined)) return {};
    const r = data.ledRuntimeR, g = data.ledRuntimeG, b = data.ledRuntimeB;
    const color = rgbToHs(r, g, b);
    return {state_led: data.ledRuntimeIntensity > 0 && (r || g || b) ? 'ON' : 'OFF',
        brightness_led: Math.round(data.ledRuntimeIntensity * 254 / 100), brightness_percent_led: data.ledRuntimeIntensity,
        color_led: {...color, h: color.hue, s: color.saturation}, color_mode_led: 'hs',
        effect_led: data.ledOverrideActive ? ['steady', 'slow_blink'][data.ledRuntimeEffect] : 'automatic'};
}

const PROFILE_ATTRIBUTES = {
    led_off: ['ledOffR', 'ledOffG', 'ledOffB', 'ledOffIntensity'],
    led_on: ['ledOnR', 'ledOnG', 'ledOnB', 'ledOnIntensity', 'ledOnMode', 'ledOnMin', 'ledOnMax'],
};

function profileLightState(data, endpoint) {
    const attributes = PROFILE_ATTRIBUTES[endpoint];
    if (!attributes.every((name) => data[name] !== undefined)) return {};
    const [r, g, b] = attributes.map((name) => data[name]);
    const intensity = endpoint === 'led_on' && data.ledOnMode !== 0 ? data.ledOnMax : data[attributes[3]];
    const color = rgbToHs(r, g, b);
    return {[`state_${endpoint}`]: intensity > 0 && (r || g || b) ? 'ON' : 'OFF',
        [`brightness_${endpoint}`]: Math.round(intensity * 254 / 100), [`brightness_percent_${endpoint}`]: intensity,
        [`color_${endpoint}`]: {...color, h: color.hue, s: color.saturation},
        [`color_mode_${endpoint}`]: 'hs'};
}

function profileLightConverter(endpoint) {
    return {key: ['state', 'brightness', 'brightness_percent', 'color'], endpoints: [endpoint],
        convertGet: async (entity) => entity.read(CLUSTER_NAME, PROFILE_ATTRIBUTES[endpoint], {}),
        convertSet: async (entity, key, value, meta) => {
            const message = percentageMessage({...(meta?.message ?? {[key]: value})});
            for (const name of Object.keys(message)) {
                if (!['state', 'brightness', 'color'].includes(name)) throw new Error(`Unsupported profile light option: ${name}`);
            }
            if (typeof message.state === 'string') message.state = message.state.toUpperCase();
            if (message.state !== undefined && !['ON', 'OFF', 'TOGGLE'].includes(message.state)) throw new RangeError('Invalid profile state');
            if (message.brightness !== undefined && (!Number.isInteger(message.brightness) || message.brightness < 0 || message.brightness > 254)) {
                throw new RangeError('Profile brightness must be 0..254');
            }
            const rgb = message.color === undefined ? null : hsToRgb(message.color);
            const names = PROFILE_ATTRIBUTES[endpoint];
            const current = await entity.read(CLUSTER_NAME, names, {});
            if (!names.every((name) => Number.isInteger(current[name]))) throw new Error('LED profile feedback unavailable');
            const dynamic = endpoint === 'led_on' && current.ledOnMode !== 0;
            const intensityName = dynamic ? 'ledOnMax' : names[3];
            const attributes = rgb ? Object.fromEntries(names.slice(0, 3).map((name, i) => [name, rgb[i]])) : {};
            let intensity = message.brightness === undefined ? current[intensityName] : Math.round(message.brightness * 100 / 254);
            const wasOn = current[intensityName] > 0 && names.slice(0, 3).some((name) => current[name] > 0);
            const state = message.state === 'TOGGLE' ? (wasOn ? 'OFF' : 'ON') : message.state;
            if (state === 'OFF') intensity = 0;
            else if (state === 'ON' && intensity === 0 && message.brightness !== 0) intensity = 10;
            if (state === 'ON' && !rgb && names.slice(0, 3).every((name) => current[name] === 0)) {
                for (const name of names.slice(0, 3)) attributes[name] = 255;
            }
            if (message.brightness !== undefined || state !== undefined) attributes[intensityName] = intensity;
            // Lowering the dynamic ceiling also lowers the minimum, in a separate
            // request, so each firmware-validated write preserves min <= max.
            if (dynamic && attributes.ledOnMax !== undefined && current.ledOnMin > intensity) {
                await entity.write(CLUSTER_NAME, {ledOnMin: intensity}, {});
            }
            if (Object.keys(attributes).length) await entity.write(CLUSTER_NAME, attributes, {});
            // Publish only read responses; a failed write must not become state.
            await entity.read(CLUSTER_NAME, names, {});
        }};
}

function ledLightConverter() {
    return {key: ['state', 'brightness', 'brightness_percent', 'color', 'effect'], endpoints: ['led'],
        convertGet: async (entity) => entity.read(CLUSTER_NAME, LED_RUNTIME_ATTRIBUTES, {}),
        convertSet: async (entity, key, value, meta) => {
            const message = percentageMessage({...(meta?.message ?? {[key]: value})});
            if (typeof message.state === 'string') message.state = message.state.toUpperCase();
            if (message.effect === 'automatic') {
                if (Object.keys(message).some((name) => name !== 'effect')) throw new Error('automatic LED mode must be sent separately');
                await entity.command(CLUSTER_NAME, 'clearLedOverride', {}, {disableDefaultResponse: false});
                return;
            }
            if (message.brightness !== undefined && (!Number.isInteger(message.brightness) || message.brightness < 0 || message.brightness > 254)) {
                throw new RangeError('LED brightness must be 0..254');
            }
            if (message.state !== undefined && !['ON', 'OFF', 'TOGGLE'].includes(message.state)) throw new RangeError('invalid LED state');
            if (message.effect !== undefined && !['steady', 'slow_blink'].includes(message.effect)) throw new RangeError('invalid LED effect');
            const rgb = message.color !== undefined ? hsToRgb(message.color) : null;
            // Always read the controller output: command echoes must not replace device feedback.
            const current = await entity.read(CLUSTER_NAME, LED_RUNTIME_ATTRIBUTES, {});
            if (!LED_RUNTIME_ATTRIBUTES.every((name) => current[name] !== undefined)) throw new Error('LED runtime feedback unavailable; update device firmware');
            const [r, g, b] = rgb ?? [current.ledRuntimeR, current.ledRuntimeG, current.ledRuntimeB];
            let intensity = message.brightness === undefined ? current.ledRuntimeIntensity : Math.round(message.brightness * 100 / 254);
            const on = message.state === 'TOGGLE' ? !current.ledRuntimeIntensity : message.state !== 'OFF';
            if (!on) intensity = 0;
            else if (message.state && !intensity && message.brightness !== 0) intensity = 10;
            const effect = message.effect === undefined ? current.ledRuntimeEffect : ['steady', 'slow_blink'].indexOf(message.effect);
            await entity.command(CLUSTER_NAME, 'applyLedOverride', {r, g, b, intensity, effect, durationMs: 0}, {disableDefaultResponse: false});
        }};
}

function ordinaryLightConverter(standard) {
    return {key: ['state', 'brightness', 'brightness_percent'], convertSet: async (entity, key, value, meta) => {
        if (['led', 'led_off', 'led_on'].includes(meta?.endpoint_name)) throw new Error('Unsupported LED light command');
        const message = percentageMessage({...(meta?.message ?? {[key]: value})});
        if (typeof message.state === 'string') message.state = message.state.toUpperCase();
        // ZBOSS owns explicitly requested transitions and the standard timed-on commands.
        if (message.transition !== undefined || message.on_time !== undefined || message.off_wait_time !== undefined) {
            const fallback = standard.toZigbee?.find((c) => c.key?.includes(key === 'brightness_percent' ? 'brightness' : key));
            if (!fallback) throw new Error('Standard light command unavailable');
            return fallback.convertSet(entity, key === 'brightness_percent' ? 'brightness' : key,
                key === 'brightness_percent' ? message.brightness : value, {...meta, message});
        }
        if (message.state !== undefined && !['ON', 'OFF', 'TOGGLE'].includes(message.state)) throw new RangeError('invalid lamp state');
        let requested = message.brightness;
        if (message.brightness_percent !== undefined) {
            const percent = message.brightness_percent;
            if (!Number.isFinite(percent) || percent < 0 || percent > 100) throw new RangeError('brightness_percent must be 0..100');
            requested = Math.round(percent * 254 / 100);
        }
        if (requested !== undefined && (!Number.isInteger(requested) || requested < 0 || requested > 254)) throw new RangeError('brightness must be 0..254');
        let level = requested;
        if (!level) {
            level = meta?.state?.brightness;
            if (!Number.isInteger(level) || level < 1 || level > 254) level = (await entity.read('genLevelCtrl', ['currentLevel'], {})).currentLevel;
            if (!Number.isInteger(level) || level < 1 || level > 254) throw new Error('Remembered lamp brightness unavailable');
        }
        let on = message.state !== 'OFF' && requested !== 0;
        if (message.state === 'TOGGLE') {
            let previous = meta?.state?.state;
            if (!['ON', 'OFF'].includes(previous)) previous = (await entity.read('genOnOff', ['onOff'], {})).onOff ? 'ON' : 'OFF';
            on = previous !== 'ON';
        }
        await entity.command(CLUSTER_NAME, 'setOutput', {on, level}, {disableDefaultResponse: false});
    }, convertGet: async (entity, key) => entity.read(key === 'state' ? 'genOnOff' : 'genLevelCtrl',
        [key === 'state' ? 'onOff' : 'currentLevel'], {})};
}

const eventNames = ['press', 'single', 'double', 'long', 'release', 'timer_expired', 'restore_request', 'state_correction', 'fault'];
function decodeEvent(data) {
    const type = Number(data.type); const side = Number(data.side);
    if (!Number.isInteger(type) || type < 0 || type >= eventNames.length || ![0, 1].includes(side)) throw new RangeError('invalid event');
    const suffix = type <= 4 ? `_${side === 0 ? 'up' : 'down'}` : '';
    return {action: `${eventNames[type]}${suffix}`, action_sequence: Number(data.sequenceId) >>> 0,
        action_held_ms: Number(data.heldMs) >>> 0, action_effective_state: data.effectiveOn ? 'ON' : 'OFF',
        action_effective_level: Number(data.effectiveLevel), action_data: Number(data.data)};
}

function clusterDefinition(T) {
    const types = {u8: T.UINT8 ?? 'UINT8', u16: T.UINT16 ?? 'UINT16', u32: T.UINT32 ?? 'UINT32', bool: T.BOOLEAN ?? 'BOOLEAN', octetStr: T.OCTET_STR ?? 'OCTET_STR'};
    const attributes = Object.fromEntries(ATTRIBUTE_METADATA.map((item) => [item.zclName,
        {name: item.zclName, ID: item.ID, type: types[item.zclType ?? 'u8'], write: item.writable !== false,
            ...(item.min !== undefined ? {min: item.min} : {}), ...(item.max !== undefined ? {max: item.max} : {})}]));
    const u8 = types.u8, u16 = types.u16, u32 = types.u32, bool = types.bool;
    return {name: CLUSTER_NAME, ID: CLUSTER_ID, attributes, commands: {
        clearLedOverride: {name: 'clearLedOverride', ID: 0, parameters: []},
        applyLedOverride: {name: 'applyLedOverride', ID: 1, parameters: [
            {name: 'r', type: u8}, {name: 'g', type: u8}, {name: 'b', type: u8},
            {name: 'intensity', type: u8}, {name: 'effect', type: u8}, {name: 'durationMs', type: u32}]},
        requestSnapshot: {name: 'requestSnapshot', ID: 2, parameters: []},
        bypassOn: {name: 'bypassOn', ID: 3, parameters: []},
        enterRecovery: {name: 'enterRecovery', ID: 4, parameters: []},
        setOutput: {name: 'setOutput', ID: 5, parameters: [{name: 'on', type: bool}, {name: 'level', type: u8}]},
    }, commandsResponse: {event: {name: 'event', ID: 0, parameters: [
        {name: 'type', type: u8}, {name: 'side', type: u8}, {name: 'sequenceId', type: u32},
        {name: 'heldMs', type: u32}, {name: 'effectiveOn', type: bool},
        {name: 'effectiveLevel', type: u8}, {name: 'data', type: u16}]}}};
}

function exposeDescriptors(device) {
    const schema = schemaVersion(device);
    const attributes = ATTRIBUTE_METADATA.filter((item) => !item.internal && (item.minSchema ?? 0) <= schema && !PERCENT_SETTINGS.includes(item.name))
        .map(({ID, zclType, writable, ...item}) => ({...item}));
    for (const name of PERCENT_SETTINGS) {
        const item = byPublicName.get(name);
        if ((item.minSchema ?? 0) > schema) continue;
        attributes.push({...item, name: `${name}_percent`, min: toPercent(item.min), max: toPercent(item.max),
            default: toPercent(item.default), unit: '%', step: 0.1,
            description: `${SETTING_PRESENTATION[name][1]} Percentuale. Default: ${toPercent(item.default)}%.`});
    }
    if (schema >= 4) {
        const timer = attributes.find((item) => item.name === 'timer_duration_s');
        timer.name = 'timer_1_duration_s'; timer.label = 'Durata timer 1';
    }
    for (const item of attributes) if (item.values === ACTIONS) item.values = schema >= 4 ? ACTIONS : ACTIONS.slice(0, 7);
    if (device?.modelID !== 'Vimar30805-DK') {
        attributes.find((item) => item.name === 'output_mode').values = ['dimmable', 'fixed_level'];
        Object.assign(attributes.find((item) => item.name === 'reporting_mode'),
            {values: ['optimistic'], access: 'STATE_GET', category: 'diagnostic'});
    }
    const actionValues = eventNames.flatMap((name, index) => index <= 4 ? [`${name}_up`, `${name}_down`] : [name]);
    for (const item of attributes) {
        if (/^led_(on|off)_(red|green|blue|intensity)$/.test(item.name)) item.homeassistant = {enabledByDefault: false};
    }
    return [...attributes,
        ...['led_off', 'led_on'].map((endpoint) => ({name: endpoint, type: 'light', endpoint,
            homeassistant: {entityCategory: 'config', enabledByDefault: true, name: endpoint === 'led_off' ? 'LED a lampada spenta' : 'LED a lampada accesa'},
            description: endpoint === 'led_off' ? 'Colore e intensità del profilo automatico a lampada spenta; non accende la lampada.' :
                'Profilo automatico a lampada accesa. Intensità: valore fisso oppure massimo in modalità dinamica; abbassare il massimo riduce anche il minimo se necessario.'})),
        {homeassistant: {entityCategory: 'config', enabledByDefault: false, name: 'LED override manuale avanzato'}, name: 'led', type: 'light', endpoint: 'led', description: 'LED del pulsante: colore e intensità indipendenti dalla lampada'},
        {name: 'effect_led', type: 'enum', access: 'STATE_SET_GET', values: ['automatic', 'steady', 'slow_blink'],
            description: 'Automatic restores the configured LED profiles; other effects override them until cleared'},
        {name: 'action', type: 'enum', values: actionValues, access: 'STATE', category: 'diagnostic'},
        ...['action_sequence', 'action_held_ms', 'action_effective_level', 'action_data'].map((name) =>
            ({name, type: 'numeric', access: 'STATE', category: 'diagnostic'})),
        {name: 'action_effective_state', type: 'enum', values: ['ON', 'OFF'], access: 'STATE', category: 'diagnostic'},
        {name: 'led_override', type: 'composite', access: 'SET', features: [
            {name: 'red', type: 'numeric', min: 0, max: 255}, {name: 'green', type: 'numeric', min: 0, max: 255},
            {name: 'blue', type: 'numeric', min: 0, max: 255}, {name: 'intensity', type: 'numeric', min: 0, max: 100, unit: '%'},
            {name: 'effect', type: 'enum', values: ['steady', 'slow_blink']},
            {name: 'duration_ms', type: 'numeric', min: 0, max: 0xffffffff, unit: 'ms'}]},
        ...[
            ['clear_led_override', 'Ripristina profilo LED automatico',
                'Rimuove la regolazione LED temporanea e torna ai profili configurati per lampada accesa e spenta. Non modifica la lampada.'],
            ['request_snapshot', 'Aggiorna diagnostica',
                'Richiede un nuovo rapporto dello stato e della diagnostica del dimmer. Non modifica la lampada.'],
            ['bypass_on', 'Accendi senza spegnimento automatico',
                'Accende la lampada escludendo lo spegnimento automatico fino al prossimo OFF. Non cambia la configurazione salvata.'],
            ['enter_recovery', 'Attiva modalità Bluetooth',
                'Riavvia in modalità Bluetooth per aggiunta, aggiornamento o ripristino. Zigbee e i normali comandi dei tasti restano sospesi durante la sessione.'],
        ].map(([name, label, description]) =>
            ({name, label, description, type: 'enum', access: 'SET', values: ['press'], category: 'config'})),
    ];
}

function buildDefinition({light, addCustomCluster, expose, dataTypes = {}}) {
    const standardLight = light({effect: false, powerOnBehavior: false});
    if (standardLight.fromZigbee) standardLight.fromZigbee = standardLight.fromZigbee.map((converter) => {
        if (converter.cluster !== 'genLevelCtrl') return converter;
        return {...converter, convert: (...args) => {
            const result = converter.convert(...args);
            return result?.brightness === undefined ? result : {...result,
                brightness_percent: Math.round(result.brightness * 1000 / 254) / 10};
        }};
    });
    const settings = ATTRIBUTE_METADATA.filter((item) => item.writable !== false);
    const settingConverter = {key: [...settings.map((item) => item.name), ...aliases.keys()],
        convertSet: async (entity, key, value, meta) => {
            const requested = Object.entries(meta?.message ?? {[key]: value})
                .filter(([name]) => byPublicName.get(aliases.get(name) ?? name)?.category === 'config');
            const attributes = Object.fromEntries(requested.map(([name, input]) => {
                const metadata = byPublicName.get(aliases.get(name) ?? name);
                const schema = schemaVersion(meta?.device);
                if ((metadata.minSchema ?? 0) > schema || (metadata.values === ACTIONS && ACTIONS.indexOf(input) >= 7 && schema < 4) || (name === 'timer_1_duration_s' && schema < 4)) throw new Error('Requires schema >= 4');
                if (name.endsWith('_percent')) {
                    if (!Number.isFinite(input) || input < toPercent(metadata.min) || input > toPercent(metadata.max)) throw new RangeError(`${name} outside percent range`);
                    input = Math.round(input * 254 / 100);
                }
                if (Object.hasOwn(meta?.message ?? {}, metadata.name) && name !== metadata.name) throw new Error('Specify raw or alias, not both');
                return [metadata.zclName, encodeValue(metadata, input)];
            }));
            const boundPairs = [['minLevel', 'maxLevel'], ['ledOnMin', 'ledOnMax']];
            const prewrites = [];
            for (const [minimum, maximum] of boundPairs) {
                if (attributes[minimum] === undefined || attributes[maximum] === undefined) continue;
                if (attributes[minimum] > attributes[maximum]) throw new RangeError('minimum must not exceed maximum');
                const current = await entity.read(CLUSTER_NAME, [minimum, maximum], {});
                if (!Number.isFinite(current[minimum]) || !Number.isFinite(current[maximum])) throw new Error('Current bounds unavailable');
                // Each firmware write is validated against the current pair. Open the
                // necessary bound first, in a separate request, before narrowing it.
                const first = attributes[minimum] <= current[minimum] ? minimum : maximum;
                prewrites.push({[first]: attributes[first]});
                delete attributes[first];
            }
            for (const values of prewrites) await entity.write(CLUSTER_NAME, values, {});
            if (Object.keys(attributes).length) await entity.write(CLUSTER_NAME, attributes, {});
            return {state: Object.fromEntries(requested)};
        }, convertGet: async (entity, key) => {
            const metadata = byPublicName.get(aliases.get(key) ?? key); await entity.read(CLUSTER_NAME, [metadata.zclName], {});
        }};
    const diagnosticGet = {key: ATTRIBUTE_METADATA.filter((item) => item.writable === false).map((item) => item.name),
        // A mounted device can retain the older custom-cluster name registry
        // after a converter reload. Wire IDs remain stable across versions.
        convertGet: async (entity, key) => entity.read(CLUSTER_NAME, [byPublicName.get(key).ID], {})};
    const profileCache = new WeakMap();
    const fromZigbee = [{cluster: CLUSTER_NAME, type: ['commandEvent'], convert: (_model, msg) => decodeEvent(msg.data)},
        {cluster: CLUSTER_NAME, type: ['attributeReport', 'readResponse'], convert: (_model, msg, _publish, _options, meta) => {
            const owner = msg.device ?? msg.endpoint;
            const previous = Object.fromEntries(ATTRIBUTE_METADATA.flatMap((item) => {
                const value = meta?.state?.[item.name];
                return value === undefined ? [] : [[item.zclName, encodeValue(item, value)]];
            }));
            const data = {...previous, ...(owner ? profileCache.get(owner) : {}), ...msg.data};
            if (owner) profileCache.set(owner, data);
            return {...Object.fromEntries(Object.entries(msg.data).flatMap(([name, value]) => {
                const metadata = byZclName.get(name) ?? ATTRIBUTE_METADATA.find((item) => item.ID === Number(name));
                return metadata ? Object.entries(publicState(metadata, value)) : [];
            })), ...ledLightState(msg.data), ...profileLightState(data, 'led_off'), ...profileLightState(data, 'led_on')};
        }}];
    const command = (key, name) => ({key: [key], convertSet: async (entity, _key, value) => {
        if (value === false) return;
        if (value !== true && value !== 'press') throw new Error(`${key} requires press or boolean true`);
        await entity.command(CLUSTER_NAME, name, {}, {disableDefaultResponse: false});
    }});
    const toZigbee = [settingConverter, diagnosticGet,
        {key: ['led_override'], convertSet: async (entity, _key, value) => entity.command(CLUSTER_NAME,
            'applyLedOverride', ledOverridePayload(value), {disableDefaultResponse: false})},
        command('enter_recovery', 'enterRecovery'),
        command('clear_led_override', 'clearLedOverride'), command('request_snapshot', 'requestSnapshot'), command('bypass_on', 'bypassOn')];
    return {zigbeeModel: ['Vimar30805-DK', 'Vimar30805'], ota: true, endpoint: () => ({default: 1, led: 1, led_off: 1, led_on: 1}),
        meta: {multiEndpoint: true, multiEndpointSkip: ['state', 'brightness']}, toZigbee: [profileLightConverter('led_off'), profileLightConverter('led_on'), ledLightConverter(), ordinaryLightConverter(standardLight)], model: '30805-custom', vendor: 'OpenVimar',
        description: 'Vimar 30805 custom dimmer firmware',
        extend: [addCustomCluster(CLUSTER_NAME, clusterDefinition(dataTypes)),
            standardLight,
            {isModernExtend: true, fromZigbee, toZigbee, exposes: [(device) => exposeDescriptors(device).map(expose)],
                configure: [async (device) => {
                    const endpoint = device.getEndpoint(1);
                    await endpoint.read(CLUSTER_NAME, ['schemaVersion'], {});
                    const attributes = settings.filter((item) => (item.minSchema ?? 0) <= schemaVersion(device)).map((item) => item.zclName);
                    for (let i = 0; i < attributes.length; i += 6) {
                        await endpoint.read(CLUSTER_NAME, attributes.slice(i, i + 6), {});
                    }
                }]}]};
}

const e = exposes.presets;
const ea = exposes.access;
const access = {
    STATE: ea.STATE, SET: ea.SET, STATE_GET: ea.STATE_GET,
    STATE_SET_GET: ea.ALL,
};

function primitive(descriptor) {
    const exposeAccess = access[descriptor.access];
    let result;
    if (descriptor.type === 'numeric') {
        result = e.numeric(descriptor.name, exposeAccess);
        if (descriptor.min !== undefined) result.withValueMin(descriptor.min);
        if (descriptor.max !== undefined) result.withValueMax(descriptor.max);
        if (descriptor.step !== undefined) result.withValueStep(descriptor.step);
        if (descriptor.unit !== undefined) result.withUnit(descriptor.unit);
    } else if (descriptor.type === 'enum') {
        result = e.enum(descriptor.name, exposeAccess, descriptor.values);
    } else if (descriptor.type === 'text') {
        result = e.text(descriptor.name, exposeAccess);
    } else if (descriptor.type === 'binary') {
        result = e.binary(descriptor.name, exposeAccess, descriptor.valueOn, descriptor.valueOff);
    } else {
        throw new Error(`unsupported expose type: ${descriptor.type}`);
    }
    if (descriptor.description) result.withDescription(descriptor.description);
    if (descriptor.label) result.withLabel(descriptor.label);
    if (descriptor.category) result.withCategory(descriptor.category);
    if (descriptor.homeassistant) result.withHomeAssistant(descriptor.homeassistant);
    return result;
}

function percentBrightness(light) {
    const brightness = light.features.find((feature) => feature.name === 'brightness');
    if (brightness) brightness.withProperty(light.endpoint ? `brightness_percent_${light.endpoint}` : 'brightness_percent')
        .withValueMax(100).withValueStep(0.1).withUnit('%').withLabel('Luminosità (%)');
    return light;
}

function percentLight(options) {
    const extension = m.light(options);
    for (const item of extension.exposes) if (item.type === 'light') percentBrightness(item);
    return extension;
}

function expose(descriptor) {
    if (descriptor.type === 'light') {
        const result = e.light_brightness_colorhs().withEndpoint(descriptor.endpoint).withDescription(descriptor.description);
        if (descriptor.homeassistant) result.withHomeAssistant(descriptor.homeassistant);
        return percentBrightness(result);
    }
    if (descriptor.type !== 'composite') return primitive(descriptor);
    const result = e.composite(descriptor.name, descriptor.name, access[descriptor.access]);
    for (const feature of descriptor.features) result.withFeature(primitive({...feature, access: 'SET'}));
    if (descriptor.description) result.withDescription(descriptor.description);
    if (descriptor.category) result.withCategory(descriptor.category);
    if (descriptor.homeassistant) result.withHomeAssistant(descriptor.homeassistant);
    return result;
}

export default buildDefinition({
    light: percentLight,
    addCustomCluster: m.deviceAddCustomCluster,
    expose,
    dataTypes: Zcl.DataType,
});
