import {Zcl} from 'zigbee-herdsman';
import * as exposes from 'zigbee-herdsman-converters/lib/exposes';
import * as m from 'zigbee-herdsman-converters/lib/modernExtend';

import {buildDefinition} from './vimar_30805_core.js';

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
