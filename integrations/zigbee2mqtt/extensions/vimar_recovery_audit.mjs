import fs from 'node:fs';

/* Observer only. Frontend WebSocket and broker MQTT enter Z2M through the same
 * event: these records cannot identify the publisher or an HA automation. */
export default class VimarRecoveryAudit {
    constructor(zigbee, mqtt, state, publish, eventBus, enable, restart, add, settings, logger) {
        Object.assign(this, {zigbee, eventBus, logger});
        this.auditPath = '/app/data/vimar-recovery-audit.jsonl';
        this.targets = [...new Set((process.env.VIMAR_RECOVERY_AUDIT_TARGETS ?? '')
            .split(',').map((value) => value.trim().toLowerCase())
            .filter((value) => /^0x[0-9a-f]{16}$/.test(value)))];
        this.wrappers = [];
    }
    record(data) {
        const record = {at: new Date().toISOString(), ...data};
        let descriptor;
        try {
            // Check and write the opened file, never a separately checked path.
            // Refuse links and special files; audit failure cannot fail a command.
            const open = () => {
                if (!Number.isInteger(fs.constants.O_NOFOLLOW)) throw new Error('Safe file open unavailable');
                const fd = fs.openSync(this.auditPath, fs.constants.O_WRONLY | fs.constants.O_APPEND |
                    fs.constants.O_CREAT | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, 0o600);
                try {
                    const info = fs.fstatSync(fd);
                    if (!info.isFile() || info.nlink !== 1) throw new Error('Audit requires a private regular file');
                    fs.fchmodSync(fd, 0o600);
                    return {fd, size: info.size};
                } catch (error) {fs.closeSync(fd); throw error;}
            };
            let opened = open(); descriptor = opened.fd;
            if (opened.size >= 1024 * 1024) {
                fs.closeSync(descriptor); descriptor = undefined;
                fs.renameSync(this.auditPath, `${this.auditPath}.1`);
                opened = open(); descriptor = opened.fd;
            }
            fs.appendFileSync(descriptor, `${JSON.stringify(record)}\n`);
        } catch {
            if (!this.fileWarning) {
                this.fileWarning = true;
                try {this.logger.warning('VIMAR_RECOVERY_AUDIT file unavailable; console trace only');} catch {}
            }
        } finally {
            if (descriptor !== undefined) {try {fs.closeSync(descriptor);} catch {}}
        }
        try {this.logger.info(`VIMAR_RECOVERY_AUDIT ${JSON.stringify(record)}`);} catch {}
    }
    async start() {
        const targets = this.targets.flatMap((ieee) => {
            const device = this.zigbee.resolveEntity(ieee);
            return device?.zh ? [{ieee, device}] : [];
        });
        this.eventBus.onMQTTMessage(this, ({topic, message}) => {
            for (const {ieee} of targets) {
                const device = this.zigbee.resolveEntity(ieee);
                for (const alias of new Set([ieee, device?.name].filter(Boolean))) {
                    const full = String(topic);
                    const isSet = full === `${alias}/set` || full.endsWith(`/${alias}/set`);
                    const isProperty = full === `${alias}/set/enter_recovery` || full.endsWith(`/${alias}/set/enter_recovery`);
                    if (!isSet && !isProperty) continue;
                    let payload;
                    try {payload = JSON.parse(String(message));} catch {payload = String(message);}
                    if (isSet && (!payload || typeof payload !== 'object' || !Object.hasOwn(payload, 'enter_recovery'))) break;
                    const value = isProperty ? payload : payload.enter_recovery;
                    this.record({kind: 'request', ieee, accepted_value: value === true || value === 'press',
                        value: value === true || value === false || value === 'press' ? value : 'invalid'});
                    break;
                }
            }
        });
        for (const {ieee, device} of targets) {
            const endpoint = device.zh.getEndpoint(1);
            if (!endpoint || typeof endpoint.command !== 'function') continue;
            const original = endpoint.command;
            const observer = this;
            const wrapped = async function (cluster, command, ...args) {
                const match = (cluster === 'vimarDimmer' || cluster === 0xfc00) && (command === 'enterRecovery' || command === 4);
                if (match) observer.record({kind: 'command_start', ieee});
                try {
                    const result = await original.call(this, cluster, command, ...args);
                    if (match) observer.record({kind: 'command_ack', ieee});
                    return result;
                } catch (error) {
                    if (match) observer.record({kind: 'command_error', ieee});
                    throw error;
                }
            };
            endpoint.command = wrapped;
            this.wrappers.push({endpoint, original, wrapped});
        }
        this.record({kind: 'ready', targets: targets.map((x) => x.ieee), wrapped: this.wrappers.length});
    }
    async stop() {
        this.eventBus.removeListeners(this);
        for (const {endpoint, original, wrapped} of this.wrappers) {
            if (endpoint.command === wrapped) endpoint.command = original;
        }
        this.wrappers = [];
    }
    adjustMessageBeforePublish() {}
}
