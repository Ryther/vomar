import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

import {ATTRIBUTE_METADATA, CLUSTER_ID, buildDefinition, decodeEvent} from '../vimar_30805_core.js';
import {combineConverterSources} from '../build_external_converter.js';

const build = () => {
    const clusters = [];
    const definition = buildDefinition({
        light: (options) => ({kind: 'light', options}),
        addCustomCluster: (name, cluster) => (clusters.push({name, cluster}), {kind: 'cluster'}),
        expose: (descriptor) => ({...descriptor}),
    });
    const extension = definition.extend[2];
    const resolved = extension.exposes.flatMap((item) => typeof item === 'function' ? item({modelID: 'Vimar30805-DK'}) : [item]);
    return {definition, cluster: clusters[0].cluster, custom: {...extension, exposes: resolved}};
};

test('combines converter modules into one importable source', () => {
    const core = 'export const value = 7;\nexport function buildDefinition() { return value; }\n';
    const wrapper = "import {buildDefinition} from './vimar_30805_core.js';\n" +
        "import {Zcl} from 'zigbee-herdsman';\nexport default buildDefinition(Zcl);\n";
    assert.equal(combineConverterSources(core, wrapper),
        "import {Zcl} from 'zigbee-herdsman';\n\n" +
        'const value = 7;\nfunction buildDefinition() { return value; }\n\n' +
        'export default buildDefinition(Zcl);\n');
});

test('keeps the committed external converter synchronized', async () => {
    const [core, wrapper, artifact] = await Promise.all([
        readFile(new URL('../vimar_30805_core.js', import.meta.url), 'utf8'),
        readFile(new URL('../vimar_30805.js', import.meta.url), 'utf8'),
        readFile(new URL('../dist/vimar_30805.js', import.meta.url), 'utf8'),
    ]);
    assert.equal(artifact, combineConverterSources(core, wrapper));
});

test('enables the standard Zigbee OTA provider for custom firmware', () => {
    const {definition} = build();
    assert.equal(definition.ota, true);
});

test('registers all metadata and a standard light without power-on behavior', () => {
    const {definition, cluster} = build();
    assert.deepEqual(definition.zigbeeModel, ['Vimar30805-DK', 'Vimar30805']);
    assert.equal(cluster.ID, CLUSTER_ID);
    assert.equal(Object.keys(cluster.attributes).length, ATTRIBUTE_METADATA.length);
    assert.equal(cluster.attributes.autoOffDurationS.ID, 0x0206);
    assert.equal(cluster.attributes.timerRemainingS.write, false);
    assert.ok(cluster.commands.bypassOn);
    assert.deepEqual(definition.extend[1], {kind: 'light', options: {effect: false, powerOnBehavior: false}});
});

test('keeps every public property mapped to its fixed registered attribute', () => {
    const {cluster, custom} = build();
    const settings = custom.toZigbee.find((item) => item.key.includes('auto_off_mode'));
    const diagnostics = custom.toZigbee.find((item) => item.key.includes('timer_remaining_s'));
    for (const metadata of ATTRIBUTE_METADATA) {
        assert.equal(cluster.attributes[metadata.zclName].ID, metadata.ID, metadata.name);
        const converter = metadata.writable === false ? diagnostics : settings;
        assert.ok(converter.key.includes(metadata.name), metadata.name);
    }
});

test('exposes every persistent setting individually with exact metadata', () => {
    const {custom} = build();
    const byName = Object.fromEntries(custom.exposes.map((item) => [item.name, item]));
    assert.equal(byName.dimmer_configuration, undefined);
    assert.equal(custom.exposes.some((item) => item.type === 'text'), false);
    assert.equal(byName.double_click_window_ms.type, 'numeric');
    assert.equal(byName.double_click_window_ms.access, 'STATE_SET_GET');
    assert.equal(byName.double_click_window_ms.category, 'config');
    assert.equal(byName.double_click_window_ms.min, 50);
    assert.equal(byName.double_click_window_ms.max, 600);
    assert.equal(byName.double_click_window_ms.unit, 'ms');
    assert.equal(byName.double_click_window_ms.zclName, 'doubleClickWindowMs');
    assert.deepEqual(byName.auto_off_mode.values, ['disabled', 'every_on', 'physical_on_only']);
    assert.deepEqual(byName.single_up_action.values,
        ['toggle', 'on', 'off', 'timed_on', 'event_only', 'disabled', 'bypass_on']);
    assert.equal(byName.custom_power_on_behavior.zclName, 'powerOnBehavior');
    assert.equal(byName.led_on_red.max, 255);
    assert.equal(byName.led_on_min_intensity.max, 100);
    assert.equal(byName.timer_remaining_s.category, 'diagnostic');
    assert.equal(byName.timer_remaining_s.access, 'STATE_GET');
    assert.equal(byName.led_override.type, 'composite');
    assert.deepEqual(byName.led_override.features.map((feature) => feature.name),
        ['red', 'green', 'blue', 'intensity', 'effect', 'duration_ms']);
});

test('sets and gets each setting through its registered attribute', async () => {
    const {custom} = build();
    const converter = custom.toZigbee.find((item) => item.key.includes('auto_off_mode'));
    const calls = [];
    const entity = {write: async (...args) => calls.push(['write', ...args]),
        read: async (...args) => calls.push(['read', ...args])};
    assert.deepEqual(await converter.convertSet(entity, 'auto_off_mode', 'physical_on_only'),
        {state: {auto_off_mode: 'physical_on_only'}});
    await converter.convertGet(entity, 'auto_off_mode');
    assert.deepEqual(calls, [['write', 'vimarDimmer', {autoOffMode: 2}, {}],
        ['read', 'vimarDimmer', ['autoOffMode'], {}]]);
    await assert.rejects(() => converter.convertSet(entity, 'auto_off_mode', 'maybe'), /auto_off_mode/);
});

test('validates numeric settings before transmission', async () => {
    const {custom} = build();
    const converter = custom.toZigbee.find((item) => item.key.includes('auto_off_duration_s'));
    const entity = {write: async () => assert.fail('invalid value was transmitted')};
    await assert.rejects(() => converter.convertSet(entity, 'auto_off_duration_s', 0), /1\.\.86400/);
    await assert.rejects(() => converter.convertSet(entity, 'auto_off_duration_s', 1.5), /integer/);
});

test('decodes attribute reports using public typed properties', () => {
    const {custom} = build();
    const converter = custom.fromZigbee.find((item) => item.type.includes('attributeReport'));
    assert.deepEqual(converter.convert(null, {data: {autoOffMode: 1, powerOnBehavior: 1,
        targetOn: true, timerActive: false, timerRemainingS: 9}}), {
        auto_off_mode: 'every_on', custom_power_on_behavior: 'await_zigbee',
        target_state: 'ON', timer_active: false, timer_remaining_s: 9});
});

test('maps typed LED override and all runtime triggers', async () => {
    const {custom} = build();
    const commands = [];
    const entity = {command: async (...args) => commands.push(args)};
    const led = custom.toZigbee.find((item) => item.key.includes('led_override'));
    await led.convertSet(entity, 'led_override', {red: 255, green: 2, blue: 3,
        intensity: 100, effect: 'steady', duration_ms: 500});
    for (const [key, command] of [['clear_led_override', 'clearLedOverride'],
        ['request_snapshot', 'requestSnapshot'], ['bypass_on', 'bypassOn']]) {
        const converter = custom.toZigbee.find((item) => item.key.includes(key));
        await converter.convertSet(entity, key, true);
        assert.equal(commands.at(-1)[1], command);
    }
    assert.deepEqual(commands[0], ['vimarDimmer', 'applyLedOverride',
        {r: 255, g: 2, b: 3, intensity: 100, effect: 0, durationMs: 500},
        {disableDefaultResponse: false}]);
});

test('decodes event metadata under dedicated action names', () => {
    const event = decodeEvent({type: 4, side: 1, sequenceId: 0xffffffff,
        heldMs: 0xffffffff, effectiveOn: true, effectiveLevel: 254, data: 65535});
    assert.deepEqual(event, {action: 'release_down', action_sequence: 0xffffffff,
        action_held_ms: 0xffffffff, action_effective_state: 'ON',
        action_effective_level: 254, action_data: 65535});
});

test('recovery trigger uses its dedicated command and ignores false', async () => {
    const {cluster, custom} = build();
    assert.equal(cluster.commands.enterRecovery.ID, 4);
    const converter=custom.toZigbee.find((item)=>item.key.includes('enter_recovery'));
    const calls=[];const entity={command:async(...args)=>calls.push(args)};
    await converter.convertSet(entity,'enter_recovery',false);assert.equal(calls.length,0);
    await converter.convertSet(entity,'enter_recovery',true);
    assert.deepEqual(calls,[['vimarDimmer','enterRecovery',{}, {disableDefaultResponse:false}]]);
});

test('uses application endpoint1 even when a migrated device retains other endpoints', () => {
    const {definition} = build();
    const migrated = {endpoints: [{ID: 242}, {ID: 1}]};
    assert.equal(definition.endpoint(migrated).default, 1);
});

test('keeps full-scale RGB components valid in real zigbee-herdsman attribute decoding', async (t) => {
    const {createRequire} = await import('node:module');
    const require = createRequire(import.meta.url);
    let zcl;
    try {
        zcl = require('../../../experiments/zigbee-ota-migration-20261020/zh-10.9.2-source/npm/package/dist/zspec/zcl/utils.js');
    } catch (error) {
        if (error.code === 'MODULE_NOT_FOUND') return t.skip('Version-pinned Zigbee2MQTT decoder evidence not present');
        throw error;
    }
    const clusters = [];
    const definition = buildDefinition({
        light: (options) => ({options}), addCustomCluster: (name, cluster) => (clusters.push(cluster), {}),
        expose: (descriptor) => descriptor, dataTypes: {UINT8: 0x20, UINT16: 0x21, UINT32: 0x23, BOOLEAN: 0x10},
    });
    const attributes = clusters[0].attributes;
    for (const key of ['ledOnR', 'ledOnG', 'ledOnB', 'ledOffR', 'ledOffG', 'ledOffB']) {
        assert.equal(zcl.processAttributePostRead(attributes[key], 255), 255, `${key} must not become NaN/null`);
        assert.equal(zcl.processAttributeWrite(attributes[key], 255), 255);
    }
    const decoder = definition.extend[2].fromZigbee.find((item) => item.type.includes('readResponse'));
    assert.equal(JSON.stringify(decoder.convert({}, {data: {ledOnG: zcl.processAttributePostRead(attributes.ledOnG, 255)}})), '{"led_on_green":255}');
});

test('routes native LED light commands atomically without operating the lamp', async () => {
    const {definition} = build();
    const led = definition.toZigbee?.find((c) => c.endpoints?.includes('led'));
    assert.ok(led, 'dedicated LED endpoint converter required before standard light converters');
    assert.equal(definition.endpoint().led, 1);
    const calls = [];
    const entity = {read: async () => ({ledRuntimeR: 0, ledRuntimeG: 255, ledRuntimeB: 0,
        ledRuntimeIntensity: 10, ledRuntimeEffect: 0, ledOverrideActive: false}),
        command: async (...args) => calls.push(args)};
    await led.convertSet(entity, 'color', {hue: 240, saturation: 100},
        {message: {state: 'ON', brightness: 127, color: {hue: 240, saturation: 100}}});
    assert.deepEqual(calls, [['vimarDimmer', 'applyLedOverride',
        {r: 0, g: 0, b: 255, intensity: 50, effect: 0, durationMs: 0}, {disableDefaultResponse: false}]]);
    await led.convertSet(entity, 'effect', 'automatic', {message: {effect: 'automatic'}});
    assert.equal(calls.at(-1)[1], 'clearLedOverride');
    await assert.rejects(() => led.convertSet(entity, 'brightness', 255,
        {message: {brightness: 255}}), /brightness/);
});

test('reports LED state from firmware runtime attributes, independently of lamp state', () => {
    const {custom} = build();
    const decoder = custom.fromZigbee.find((c) => c.type.includes('attributeReport'));
    const result = decoder.convert(null, {data: {ledRuntimeR: 255, ledRuntimeG: 0,
        ledRuntimeB: 0, ledRuntimeIntensity: 50, ledRuntimeEffect: 1, ledOverrideActive: true}});
    assert.equal(result.state_led, 'ON');
    assert.equal(result.brightness_led, 127);
    assert.deepEqual(result.color_led, {hue: 0, saturation: 100, h: 0, s: 100});
    assert.equal(result.color_mode_led, 'hs');
    assert.equal(result.effect_led, 'slow_blink');
    assert.equal(result.state, undefined);
});

test('runtime buttons accept press and legacy true, ignore false, reject ambiguous values', async () => {
    const {custom} = build(); let count = 0;
    const entity = {command: async () => count++};
    for (const key of ['bypass_on', 'request_snapshot', 'clear_led_override', 'enter_recovery']) {
        const converter = custom.toZigbee.find((c) => c.key.includes(key));
        const before = count;
        await converter.convertSet(entity, key, false);
        assert.equal(count, before);
        for (const value of ['false', 'true', 'ON', 1, null]) {
            await assert.rejects(() => converter.convertSet(entity, key, value), /press|boolean/);
        }
        await converter.convertSet(entity, key, 'press');
        await converter.convertSet(entity, key, true);
        assert.equal(count, before + 2);
    }
});

test('technical actions are momentary configuration buttons with explicit names', () => {
    const {custom} = build();
    for (const key of ['bypass_on', 'request_snapshot', 'clear_led_override', 'enter_recovery']) {
        const item = custom.exposes.find((x) => x.name === key);
        assert.equal(item.type, 'enum');
        assert.equal(item.access, 'SET');
        assert.deepEqual(item.values, ['press']);
        assert.equal(item.category, 'config');
        assert.ok(item.label.length > 10);
        assert.ok(item.description.length > 40);
    }
});

test('documents Vimar factory defaults without replacing saved device values', () => {
    const settings = ATTRIBUTE_METADATA.filter((m) => m.category === 'config');
    for (const item of settings) {
        assert.notEqual(item.default, undefined, item.name);
        assert.ok(item.label?.length > 3, item.name);
        assert.ok(item.description.includes('Default:'), item.name);
    }
    assert.equal(settings.find((m) => m.name === 'long_press_ms').default, 500);
    assert.equal(settings.find((m) => m.name === 'level_step').default, 3);
});

test('limits physical Vimar exposes to supported modes while preserving DK wire enums', () => {
    const {definition, custom} = build();
    const dynamic = definition.extend[2].exposes.find((item) => typeof item === 'function');
    assert.ok(dynamic, 'model-specific expose selection required');
    const physical = dynamic({modelID: 'Vimar30805'});
    assert.deepEqual(physical.find((m) => m.name === 'output_mode').values, ['dimmable', 'fixed_level']);
    assert.deepEqual(physical.find((m) => m.name === 'reporting_mode').values, ['optimistic']);
    assert.equal(physical.find((m) => m.name === 'reporting_mode').access, 'STATE_GET');
    assert.equal(physical.find((m) => m.name === 'reporting_mode').category, 'diagnostic');
    assert.deepEqual(custom.exposes.find((m) => m.name === 'reporting_mode').values, ['optimistic', 'acknowledged', 'physical']);
    assert.equal(custom.exposes.find((m) => m.name === 'reporting_mode').access, 'STATE_SET_GET');
});

test('writes every supplied configuration property in a single MQTT request', async () => {
    const {custom} = build();
    const settings = custom.toZigbee.find((c) => c.key.includes('led_on_red'));
    const calls = [];
    const entity = {write: async (...args) => calls.push(args)};
    const message = {led_on_red: 10, led_on_green: 20, led_on_blue: 30};
    assert.deepEqual(await settings.convertSet(entity, 'led_on_red', 10, {message}), {state: message});
    assert.deepEqual(calls, [['vimarDimmer', {ledOnR: 10, ledOnG: 20, ledOnB: 30}, {}]]);
    await assert.rejects(() => settings.convertSet(entity, 'led_on_red', 10,
        {message: {...message, led_on_blue: 256}}), /led_on_blue/);
    assert.equal(calls.length, 1, 'validate complete request before transmitting');
});

test('reads saved settings at configure time without imposing converter defaults', async () => {
    const {definition} = build();
    const calls = [];
    const endpoint = {getClusterAttributeValue: () => 4, read: async (...args) => calls.push(args)};
    const device = {getEndpoint: (id) => { assert.equal(id, 1); return endpoint; }};
    const hooks = definition.extend[2].configure;
    assert.ok(hooks?.length);
    await hooks[0](device);
    const attrs = calls.flatMap((c) => c[1]);
    for (const m of ATTRIBUTE_METADATA.filter((m) => m.category === 'config')) assert.ok(attrs.includes(m.zclName), m.name);
    assert.ok(calls.every((c) => c[1].length <= 6));
});

test('uses local default timing for ordinary lamp commands and preserves explicit transitions', async () => {
    const {definition} = build();
    const converter = definition.toZigbee.find((c) => !c.endpoints && c.key.includes('brightness'));
    assert.ok(converter);
    const commands = [];
    const entity = {read: async (cluster) => cluster === 'genOnOff' ? {onOff: false} : {currentLevel: 64},
        command: async (...args) => commands.push(args)};
    await converter.convertSet(entity, 'brightness', 100, {message: {state: 'ON', brightness: 100}, state: {}});
    assert.deepEqual(commands[0], ['vimarDimmer', 'setOutput', {on: true, level: 100}, {disableDefaultResponse: false}]);
    assert.ok(build().cluster.commands.setOutput);
});

test('delegates explicit lamp transition to the native ZBOSS light command', async () => {
    const calls = [];
    const native = {key: ['state', 'brightness'], convertSet: async (...args) => (calls.push(args), {native: true})};
    const definition = buildDefinition({light: () => ({toZigbee: [native]}), addCustomCluster: () => ({}), expose: (d) => d});
    const converter = definition.toZigbee.find((c) => !c.endpoints && c.key.includes('brightness'));
    const entity = {command: async () => assert.fail('explicit transition bypassed native stack')};
    const meta = {message: {brightness: 180, transition: 2}};
    assert.deepEqual(await converter.convertSet(entity, 'brightness', 180, meta), {native: true});
    assert.deepEqual(calls, [[entity, 'brightness', 180, meta]]);
});

test('moves a complete min/max interval without transient invalid firmware writes', async () => {
    const {custom} = build();
    const converter = custom.toZigbee.find((c) => c.key.includes('min_level'));
    let min = 100, max = 200;
    const entity = {read: async () => ({minLevel: min, maxLevel: max}), write: async (_cluster, attributes) => {
        for (const [name, value] of Object.entries(attributes)) {
            if (name === 'minLevel') { assert.ok(value <= max); min = value; }
            if (name === 'maxLevel') { assert.ok(value >= min); max = value; }
        }
    }};
    await converter.convertSet(entity, 'max_level', 50, {message: {max_level: 50, min_level: 1}});
    assert.equal(min, 1); assert.equal(max, 50);
    await converter.convertSet(entity, 'min_level', 100, {message: {min_level: 100, max_level: 200}});
    assert.equal(min, 100); assert.equal(max, 200);
    await assert.rejects(() => converter.convertSet(entity, 'min_level', 200,
        {message: {min_level: 200, max_level: 100}}), /minimum/);
});

test('preserves lowercase ON/OFF compatibility on the ordinary lamp converter', async () => {
    const {definition} = build();
    const converter = definition.toZigbee.find((c) => !c.endpoints && c.key.includes('state'));
    const commands = [];
    const entity = {command: async (...args) => commands.push(args)};
    await converter.convertSet(entity, 'state', 'off', {message: {state: 'off'}, state: {brightness: 64}});
    assert.equal(commands[0][2].on, false);
    await converter.convertSet(entity, 'state', 'on', {message: {state: 'on'}, state: {brightness: 64}});
    assert.equal(commands[1][2].on, true);
});

test('adds automatic ON/OFF profile lights and keeps legacy MQTT endpoints', () => {
    const {definition, custom} = build();
    assert.deepEqual(definition.endpoint(), {default: 1, led: 1, led_off: 1, led_on: 1});
    for (const endpoint of ['led_off', 'led_on']) {
        const expose = custom.exposes.find((x) => x.endpoint === endpoint);
        assert.equal(expose.type, 'light');
        assert.equal(expose.homeassistant.entityCategory, 'config');
    }
    assert.equal(custom.exposes.find((x) => x.endpoint === 'led').homeassistant.enabledByDefault, false);
    assert.equal(custom.exposes.find((x) => x.name === 'led_on_red').homeassistant.enabledByDefault, false);
});

const profileFeedback = (mode = 0) => ({ledOnR: 0, ledOnG: 255, ledOnB: 0,
    ledOnIntensity: 15, ledOnMode: mode, ledOnMin: 20, ledOnMax: 80,
    ledOffR: 0, ledOffG: 0, ledOffB: 255, ledOffIntensity: 10});
const profileConverter = (definition, endpoint) => definition.toZigbee.find((x) => x.endpoints?.includes(endpoint));

test('profile edits write custom attributes only with combined native light messages', async () => {
    const {definition} = build(); const calls = [];
    const entity = {read: async () => profileFeedback(), write: async (...args) => calls.push(args),
        command: async () => assert.fail('profile edit must never send lamp or runtime commands')};
    const converter = profileConverter(definition, 'led_off');
    await converter.convertSet(entity, 'color', {hue: 0, saturation: 100},
        {endpoint_name: 'led_off', message: {state: 'ON', brightness: 127, color: {hue: 0, saturation: 100}}});
    assert.deepEqual(calls, [['vimarDimmer', {ledOffR: 255, ledOffG: 0, ledOffB: 0, ledOffIntensity: 50}, {}]]);
});

test('ON profile slider edits fixed intensity or dynamic ceiling and lowers minimum safely', async () => {
    const {definition} = build(); const converter = profileConverter(definition, 'led_on');
    for (const mode of [0, 1, 2]) {
        const calls = []; const entity = {read: async () => profileFeedback(mode), write: async (...args) => calls.push(args)};
        await converter.convertSet(entity, 'brightness', 25, {endpoint_name: 'led_on', message: {brightness: 25}});
        assert.deepEqual(calls, mode === 0 ? [['vimarDimmer', {ledOnIntensity: 10}, {}]] :
            [['vimarDimmer', {ledOnMin: 10}, {}], ['vimarDimmer', {ledOnMax: 10}, {}]]);
    }
});

test('profile OFF/ON never controls lamp and ON restores a nonzero default', async () => {
    const {definition} = build(); const converter = profileConverter(definition, 'led_on'); const calls = [];
    const entity = {read: async () => ({...profileFeedback(1), ledOnMin: 0, ledOnMax: 0}), write: async (...args) => calls.push(args)};
    await converter.convertSet(entity, 'state', 'ON', {endpoint_name: 'led_on', message: {state: 'ON'}});
    assert.deepEqual(calls, [['vimarDimmer', {ledOnMax: 10}, {}]]);
    calls.length = 0;
    await converter.convertSet(entity, 'state', 'OFF', {endpoint_name: 'led_on', message: {state: 'OFF'}});
    assert.deepEqual(calls, [['vimarDimmer', {ledOnMax: 0}, {}]]);
});

test('profile feedback follows mode, accumulates partial reports, and stays separate from runtime', () => {
    const {custom} = build(); const converter = custom.fromZigbee.find((x) => x.type.includes('readResponse'));
    const device = {}; const state = converter.convert(null, {device, data: profileFeedback(1)}, null, null, {});
    assert.equal(state.brightness_led_on, 203);
    assert.equal(state.brightness_led_off, 25);
    assert.equal(state.color_led_on.hue, 120);
    const partial = converter.convert(null, {device, data: {ledOnMax: 40}}, null, null, {});
    assert.equal(partial.brightness_led_on, 102);
    const runtime = converter.convert(null, {device, data: {ledRuntimeR: 255, ledRuntimeG: 0, ledRuntimeB: 0,
        ledRuntimeIntensity: 100, ledRuntimeEffect: 0, ledOverrideActive: true}}, null, null, {});
    assert.equal(runtime.brightness_led, 254);
    assert.equal(runtime.brightness_led_on, 102);
    assert.equal(runtime.color_led_on.hue, 120);
});

test('profile converters reject malformed input before writes and guard endpoint fallback', async () => {
    const {definition} = build(); const converter = profileConverter(definition, 'led_off');
    const entity = {read: async () => profileFeedback(), write: async () => assert.fail('invalid write')};
    for (const message of [{brightness: 255}, {state: 'bad'}, {color: {h: NaN, s: 100}}, {effect: 'steady'}, {transition: 1}]) {
        await assert.rejects(() => converter.convertSet(entity, Object.keys(message)[0], Object.values(message)[0],
            {endpoint_name: 'led_off', message}));
    }
    const lamp = definition.toZigbee.find((x) => !x.endpoints && x.key.includes('brightness'));
    await assert.rejects(() => lamp.convertSet(entity, 'brightness', 10, {endpoint_name: 'led_off', message: {brightness: 10}}));
});

test('native installed exposes and HA metadata prepare four distinct lights without changing runtime ID', async (t) => {
    const {createRequire} = await import('node:module'); const require = createRequire(import.meta.url);
    const {pathToFileURL} = await import('node:url');
    const base = new URL('../../../experiments/led-rgb-20261020/runtime/node_modules/', import.meta.url);
    let zhc;
    try {zhc = require(new URL('zigbee-herdsman-converters/dist/index.js', base).pathname);}
    catch (error) {if (error.code === 'MODULE_NOT_FOUND') return t.skip('Pinned native converter dependencies absent'); throw error;}
    let source = await readFile(new URL('../dist/vimar_30805.js', import.meta.url), 'utf8');
    for (const [name, target] of [['zigbee-herdsman', 'zigbee-herdsman/dist/index.js'],
        ['zigbee-herdsman-converters/lib/exposes', 'zigbee-herdsman-converters/dist/lib/exposes.js'],
        ['zigbee-herdsman-converters/lib/modernExtend', 'zigbee-herdsman-converters/dist/lib/modernExtend.js']]) {
        source = source.replaceAll(`from '${name}'`, `from '${pathToFileURL(new URL(target, base).pathname).href}'`);
    }
    const {default: definition} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
    const prepared = zhc.prepareDefinition({...definition, externalConverterName: 'vimar-profile-test.js'});
    const exposed = prepared.exposes({modelID: 'Vimar30805'}, {});
    const lights = exposed.filter((x) => x.type === 'light');
    assert.equal(lights.length, 4); // lamp + two automatic profiles + preserved advanced runtime endpoint
    for (const light of lights) {
        const brightness = light.features.find((x) => x.name === 'brightness');
        assert.equal(brightness.property, light.endpoint ? `brightness_percent_${light.endpoint}` : 'brightness_percent');
        assert.equal(brightness.value_max, 100);
        assert.equal(brightness.unit, '%');
        assert.equal(light.features.filter((x) => x.name === 'brightness').length, 1);
    }
    const metadataSource = await readFile(new URL('../../../experiments/led-rgb-20261020/source/homeassistant.ts', import.meta.url), 'utf8');
    const fn = metadataSource.slice(metadataSource.indexOf('const applyHomeAssistantExposeMetadata = '), metadataSource.indexOf('\n};', metadataSource.indexOf('const applyHomeAssistantExposeMetadata = ')) + 3);
    const apply = new Function(`${fn.replace('(payload: DiscoveryEntry, homeAssistant: zhc.Expose["homeassistant"]): void', '(payload, homeAssistant)')}; return applyHomeAssistantExposeMetadata;`)();
    for (const endpoint of ['led_off', 'led_on', 'led']) {
        const light = lights.find((x) => x.endpoint === endpoint);
        assert.ok(light.features.find((x) => x.property === `color_${endpoint}`));
        const entry = {discovery_payload: {}}; apply(entry, light.homeassistant);
        assert.equal(entry.discovery_payload.entity_category, 'config');
        assert.equal(entry.discovery_payload.enabled_by_default, endpoint !== 'led');
    }
    assert.ok(prepared.toZigbee.find((x) => x.endpoints?.includes('led_off')));
    assert.equal(ATTRIBUTE_METADATA.filter((x) => x.category === 'config').length, 40);
});

test('partial profile reports remain isolated between devices and mode changes update the slider', () => {
    const {custom} = build(); const converter = custom.fromZigbee.find((x) => x.type.includes('readResponse'));
    const first = {}, second = {};
    converter.convert(null, {device: first, data: profileFeedback(0)});
    assert.equal(converter.convert(null, {device: second, data: {ledOnMax: 40}}).brightness_led_on, undefined);
    const changed = converter.convert(null, {device: first, data: {ledOnMode: 2}});
    assert.equal(changed.brightness_led_on, 203);
    assert.equal(changed.led_on_mode, 'inverse_level');
});

test('profile ON restores a black legacy profile visibly and failed writes never return optimistic state', async () => {
    const {definition} = build(); const converter = profileConverter(definition, 'led_off'); const calls = [];
    const entity = {read: async () => ({...profileFeedback(), ledOffR: 0, ledOffG: 0, ledOffB: 0}),
        write: async (...args) => calls.push(args)};
    await converter.convertSet(entity, 'state', 'ON', {message: {state: 'ON'}});
    assert.deepEqual(calls, [['vimarDimmer', {ledOffR: 255, ledOffG: 255, ledOffB: 255, ledOffIntensity: 10}, {}]]);
    await assert.rejects(() => converter.convertSet({...entity, write: async () => {throw new Error('write failed');}},
        'brightness', 100, {message: {brightness: 100}}), /write failed/);
});

test('profile percentage commands preserve legacy raw brightness and dynamic bounds', async () => {
    const {definition, custom} = build();
    for (const mode of [0, 1]) {
        const calls = []; const converter = profileConverter(definition, 'led_on');
        const entity = {read: async () => profileFeedback(mode), write: async (...args) => calls.push(args)};
        await converter.convertSet(entity, 'brightness_percent', 50, {message: {brightness_percent: 50}});
        assert.deepEqual(calls, [['vimarDimmer', {[mode === 0 ? 'ledOnIntensity' : 'ledOnMax']: 50}, {}]]);
        await assert.rejects(() => converter.convertSet(entity, 'brightness_percent', 101, {message: {brightness_percent: 101}}));
        await assert.rejects(() => converter.convertSet(entity, 'brightness_percent', 50, {message: {brightness_percent: 50, brightness: 127}}));
    }
    const decoder = custom.fromZigbee.find((x) => x.type.includes('readResponse'));
    const state = decoder.convert(null, {data: profileFeedback(1)});
    assert.equal(state.brightness_percent_led_on, 80);
    assert.equal(state.brightness_led_on, 203);
    assert.equal(state.brightness_percent_led_off, 10);
});

test('lamp percentage readback is additive to raw levels including the smallest nonzero level', () => {
    const definition = buildDefinition({light: () => ({fromZigbee: [{cluster: 'genLevelCtrl',
        convert: (_model, msg) => ({brightness: msg.data.currentLevel})}]}), addCustomCluster: () => ({}), expose: (x) => x});
    const converter = definition.extend[1].fromZigbee[0];
    for (const [raw, percent] of [[0, 0], [1, 0.4], [127, 50], [254, 100]]) {
        assert.deepEqual(converter.convert(null, {data: {currentLevel: raw}}), {brightness: raw, brightness_percent: percent});
    }
});

test('runtime override percentage commands remain independent from automatic profiles', async () => {
    const {definition, custom} = build(); const converter = profileConverter(definition, 'led'); const calls = [];
    const data = {ledRuntimeR: 0, ledRuntimeG: 255, ledRuntimeB: 0, ledRuntimeIntensity: 10, ledRuntimeEffect: 0, ledOverrideActive: true};
    const entity = {read: async () => data, command: async (...args) => calls.push(args)};
    await converter.convertSet(entity, 'brightness_percent', 50, {message: {brightness_percent: 50}});
    assert.equal(calls[0][2].intensity, 50);
    const state = custom.fromZigbee.find((x) => x.type.includes('readResponse')).convert(null, {data});
    assert.equal(state.brightness_percent_led, 10);
    assert.equal(state.brightness_led, 25);
});

test('native HA JSON light keeps raw254 brightness while endpoint payload also carries percent aliases', async (t) => {
    let source;
    try {
        source = await readFile(new URL('../../../experiments/led-rgb-20261020/source/homeassistant.ts', import.meta.url), 'utf8');
    } catch (error) {
        if (error.code === 'ENOENT') return t.skip('Optional archived Home Assistant discovery source absent');
        throw error;
    }
    const start = source.indexOf('const discoveryEntry: DiscoveryEntry = {', source.indexOf('case "light":'));
    const snippet = source.slice(start, source.indexOf('\n                const colorModes', start));
    const discovery = new Function('endpointName', 'state', 'hasBrightness', 'utils',
        `${snippet.replace(': DiscoveryEntry', '')};return discoveryEntry;`);
    for (const endpoint of [undefined, 'led_off', 'led_on']) {
        const entry = discovery(endpoint, {property: endpoint ? `state_${endpoint}` : 'state'}, true, {capitalize: (x) => x});
        assert.equal(entry.discovery_payload.brightness_scale, 254);
        assert.equal(entry.discovery_payload.schema, 'json');
    }
    const loopStart = source.indexOf('            for (const topic in this.getDiscovered(entity).messages)', source.indexOf('@bind async onPublishEntityState'));
    const loopEnd = source.indexOf('\n        }\n', loopStart);
    const loop = source.slice(loopStart, loopEnd).replace('const payload: KeyValue', 'const payload');
    const republish = new Function('entity', 'data', 'stringify', `return (async () => {${loop}})();`);
    const published = [];
    const context = {getDiscovered: () => ({messages: {'homeassistant/light/test/light_led_on/config': {}}}),
        discoveryRegexWoTopic: /^homeassistant\/(light)\/(test)\/(light_led_on)\/config$/,
        mqtt: {publish: async (...args) => published.push(args)}};
    await republish.call(context, {}, {entity: {name: 'test'}, message: {brightness_led_on: 203, brightness_percent_led_on: 80}}, JSON.stringify);
    assert.deepEqual(JSON.parse(published[0][1]), {brightness: 203, brightness_percent: 80});
});

test('lamp percent0 switches off and percent100 reaches254 while keeping legacy raw commands', async () => {
    const {definition} = build(); const converter = definition.toZigbee.find((x) => !x.endpoints && x.key.includes('brightness_percent'));
    const calls = []; const entity = {command: async (...args) => calls.push(args), read: async () => ({currentLevel: 127})};
    for (const value of [0, 100, 50]) await converter.convertSet(entity, 'brightness_percent', value, {message: {brightness_percent: value}});
    assert.deepEqual(calls.map((x) => x[2]), [{on: false, level: 127}, {on: true, level: 254}, {on: true, level: 127}]);
    await assert.rejects(() => converter.convertSet(entity, 'brightness_percent', NaN, {message: {brightness_percent: NaN}}));
});

test('percent lamp commands with explicit transition pass raw units to the standard fallback', async () => {
    let request;
    const definition = buildDefinition({light: () => ({toZigbee: [{key: ['brightness'],
        convertSet: async (_entity, key, value, meta) => {request = {key, value, message: meta.message};}}]}),
        addCustomCluster: () => ({}), expose: (x) => x});
    const converter = definition.toZigbee.find((x) => !x.endpoints && x.key.includes('brightness_percent'));
    await converter.convertSet({}, 'brightness_percent', 50, {message: {brightness_percent: 50, transition: 2}});
    assert.deepEqual(request, {key: 'brightness', value: 127, message: {brightness: 127, transition: 2}});
});

test('schema four exposes reusable timers and percent configuration without legacy raw controls', async () => {
    const {definition, custom, cluster} = build();
    const device = {modelID: 'Vimar30805', getEndpoint: () => ({getClusterAttributeValue: () => 4})};
    const descriptors = definition.extend[2].exposes[0](device);
    const named = Object.fromEntries(descriptors.map((item) => [item.name, item]));
    assert.ok(named.timer_1_duration_s);
    assert.equal(named.timer_4_duration_s.default, 600);
    assert.equal(named.min_level, undefined);
    assert.equal(named.ramp_start_level_percent.min, 0);
    assert.equal(named.level_step_percent.max, 19.7);
    assert.ok(named.single_up_action.values.includes('timed_toggle_4'));
    assert.equal(cluster.attributes.timer4DurationS.ID, 0x0209);
    assert.equal(cluster.attributes.rampStartLevel.ID, 0x0108);
    const converter = custom.toZigbee.find((item) => item.key.includes('min_level_percent'));
    const writes = [];
    const entity = {write: async (_cluster, data) => writes.push(data)};
    await converter.convertSet(entity, 'ramp_start_level_percent', 50, {device, message: {ramp_start_level_percent: 50}});
    await converter.convertSet(entity, 'single_up_action', 'timed_toggle_4', {device, message: {single_up_action: 'timed_toggle_4'}});
    await converter.convertSet(entity, 'timer_1_duration_s', 42, {device, message: {timer_1_duration_s: 42}});
    assert.deepEqual(writes, [{rampStartLevel: 127}, {singleUpAction: 14}, {timerDurationS: 42}]);
});

test('old schema retains timed_on and rejects new timer actions before writing', async () => {
    const {custom} = build();
    const converter = custom.toZigbee.find((item) => item.key.includes('single_up_action'));
    let writes = 0;
    await assert.rejects(converter.convertSet({write: async () => writes++}, 'single_up_action', 'timed_on_1'), /schema/i);
    assert.equal(writes, 0);
});


test('percent settings validate bounds, preserve raw MQTT and decode aliases', async () => {
    const {custom} = build();
    const converter = custom.toZigbee.find((item) => item.key.includes('level_step_percent'));
    const writes = [];
    const entity = {write: async (_cluster, values) => writes.push(values)};
    await converter.convertSet(entity, 'level_step_percent', 19.7);
    await converter.convertSet(entity, 'min_level', 1);
    await assert.rejects(converter.convertSet(entity, 'level_step_percent', 20), /range/);
    await assert.rejects(converter.convertSet(entity, 'min_level_percent', 0), /range/);
    await assert.rejects(converter.convertSet(entity, 'min_level_percent', 50,
        {message: {min_level: 1, min_level_percent: 50}}), /raw or alias/);
    assert.deepEqual(writes, [{levelStep: 50}, {minLevel: 1}]);
    const receiver = custom.fromZigbee.find((item) => item.type.includes('readResponse'));
    const state = receiver.convert(null, {data: {minLevel: 1, timerDurationS: 600, rampStartLevel: 127}});
    assert.equal(state.min_level_percent, 0.4);
    assert.equal(state.timer_1_duration_s, 600);
    assert.equal(state.ramp_start_level_percent, 50);
});

test('legacy configuration reads avoid schema four attributes', async () => {
    const {definition} = build();
    const reads = [];
    const endpoint = {getClusterAttributeValue: () => 3, read: async (_cluster, attributes) => reads.push(...attributes)};
    await definition.extend[2].configure[0]({getEndpoint: () => endpoint});
    assert.ok(reads.includes('timerDurationS'));
    assert.ok(!reads.includes('rampStartLevel'));
    assert.ok(!reads.includes('timer2DurationS'));
});


test('schema four exposes every persisted action including the legacy timed_on selection', () => {
    const {definition, custom} = build();
    const device = {modelID: 'Vimar30805', getEndpoint: () => ({getClusterAttributeValue: () => 4})};
    const exposed = definition.extend[2].exposes[0](device);
    const receiver = custom.fromZigbee.find((item) => item.type.includes('readResponse'));
    for (const [name, attribute] of [['single_up_action', 'singleUpAction'], ['single_down_action', 'singleDownAction'],
        ['double_up_action', 'doubleUpAction'], ['double_down_action', 'doubleDownAction']]) {
        const descriptor = exposed.find((item) => item.name === name);
        for (let encoded = 0; encoded <= 14; encoded++) {
            const decoded = receiver.convert(null, {data: {[attribute]: encoded}})[name];
            assert.ok(descriptor.values.includes(decoded), `${name}: persisted ${encoded} (${decoded}) must remain selectable`);
        }
        assert.match(descriptor.description, /timed_on.*legacy.*1/i);
    }
});

test('schema five protection diagnostics are read-only and hidden from older firmware', async () => {
    const {definition, custom} = build();
    const dynamic=definition.extend[2].exposes[0];
    const device=(schema)=>({modelID:'Vimar30805',getEndpoint:()=>({getClusterAttributeValue:()=>schema})});
    for(const name of ['p031_enabled','p031_raw_level','p031_sample_valid','p031_low_qualified',
        'p031_signal_inhibit','p031_output_blocked','p031_notification','p031_trip_count',
        'p031_max_sample_gap_ms','p031_monitor_uptime_s','last_boot_reason','last_reset_flags','boot_sequence']){
        assert.equal(dynamic(device(4)).find(x=>x.name===name),undefined);
        const item=dynamic(device(5)).find(x=>x.name===name);
        assert.ok(item,name);assert.equal(item.access,'STATE_GET');assert.equal(item.category,'diagnostic');
        assert.ok(!custom.toZigbee.find(x=>x.key.includes('auto_off_mode')).key.includes(name));
    }
    const decode=custom.fromZigbee.find(x=>x.type.includes('readResponse'));
    assert.deepEqual(decode.convert(null,{data:{p031Enabled:true,p031RawLevel:1,p031SampleValid:true,
        p031SignalInhibit:true,p031TripCount:2,lastBootReason:2}}),{
        p031_enabled:true,p031_raw_level:1,p031_sample_valid:true,p031_signal_inhibit:true,
        p031_trip_count:2,last_boot_reason:'zigbee_recovery_request'});
});

test('schema six OTA contract is an atomic read-only text getter and stays hidden on legacy schemas', async () => {
    const {definition, custom, cluster} = build();
    const dynamic=definition.extend[2].exposes[0];
    const device=(schema)=>({modelID:'Vimar30805',getEndpoint:()=>({getClusterAttributeValue:()=>schema})});
    assert.equal(dynamic(device(5)).find(x=>x.name==='ota_contract'),undefined);
    const descriptor=dynamic(device(6)).find(x=>x.name==='ota_contract');
    assert.equal(descriptor.type,'text');assert.equal(descriptor.access,'STATE_GET');
    assert.equal(cluster.attributes.otaContract.ID,0x070d);assert.equal(cluster.attributes.otaContract.type,'OCTET_STR');assert.equal(cluster.attributes.otaContract.write,false);
    const getter=custom.toZigbee.find(x=>x.key.includes('ota_contract'));
    assert.equal(getter.convertSet,undefined);
    const reads=[];await getter.convertGet({read:async(...args)=>reads.push(args)},'ota_contract');
    assert.deepEqual(reads, [['vimarDimmer',[0x070d],{}]]);
    const receiver=custom.fromZigbee.find(x=>x.type.includes('readResponse'));
    const binary=Buffer.alloc(43);binary[0]=1;binary[1]=2;binary[2]=1;binary.writeUInt32LE(3,3);binary.writeUInt32LE(4,7);binary.fill(0xa5,11);
    const opaque='v1:'+binary.toString('base64url');
    assert.equal(receiver.convert(null,{data:{otaContract:binary}}).ota_contract,opaque);
    for(const invalid of [opaque,43,[...binary],null,{},Buffer.alloc(42),Buffer.alloc(44),Buffer.from(binary).fill(9,0,1),Buffer.from(binary).fill(3,1,2),Buffer.from(binary).fill(2,2,3),Buffer.from(binary).fill(0,2,3)]) {
        assert.equal(Object.hasOwn(receiver.convert(null,{data:{otaContract:invalid}}),'ota_contract'),false);
    }
});

test('reads new diagnostic IDs even when a device keeps an older custom-cluster registry', async () => {
    const {custom} = build();
    const get = custom.toZigbee.find((item) => item.key.includes('fault_diagnostic_status'));
    const calls = [];
    await get.convertGet({read: async (cluster, attributes) => calls.push([cluster, attributes])}, 'fault_diagnostic_status');
    assert.deepEqual(calls[0][1], [0x0800]);
    const convert = custom.fromZigbee.find((item) => item.type.includes('readResponse')).convert;
    const result = convert({}, {data: {2048: 1, 2049: Buffer.alloc(32), 2050: Buffer.alloc(31)}}, () => {}, {}, {state: {}});
    assert.equal(result.fault_diagnostic_status, 1);
    assert.equal(result.fault_diagnostic_0, '00'.repeat(32));
    assert.equal(result.fault_diagnostic_1, undefined);
});
