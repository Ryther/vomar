import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import RecoveryAudit from '../extensions/vimar_recovery_audit.mjs';

const ieee = '0x0011223344556677';
function fixture(t, directory, targets = ieee) {
    const dir = directory ?? mkdtempSync(path.join(tmpdir(), 'vimar-audit-'));
    if (!directory) t.after(() => rmSync(dir, {recursive: true, force: true}));
    const calls = []; const endpoint = {command: async (...args) => {calls.push(args); return 'ack';}};
    const device = {ieeeAddr: ieee, getEndpoint: () => endpoint};
    const events = {}; const logs = [];
    const previousTargets = process.env.VIMAR_RECOVERY_AUDIT_TARGETS;
    if (targets === null) delete process.env.VIMAR_RECOVERY_AUDIT_TARGETS;
    else process.env.VIMAR_RECOVERY_AUDIT_TARGETS = targets;
    let audit;
    try {
        audit = new RecoveryAudit({resolveEntity: () => ({name: 'Test dimmer', zh: device})},
        {}, {}, {}, {onMQTTMessage: (_owner, cb) => {events.mqtt = cb;}, removeListeners: () => {delete events.mqtt;}},
        null, null, null, {}, {info: (msg) => logs.push(msg), warning: (msg) => logs.push(msg)});
    } finally {
        if (previousTargets === undefined) delete process.env.VIMAR_RECOVERY_AUDIT_TARGETS;
        else process.env.VIMAR_RECOVERY_AUDIT_TARGETS = previousTargets;
    }
    audit.auditPath = path.join(dir, 'audit.jsonl');
    const records = () => readFileSync(audit.auditPath, 'utf8').trim().split('\n').map(JSON.parse);
    return {audit, endpoint, events, logs, calls, records};
}
test('records only exact recovery requests, excluding secrets, state reports and other devices', async (t) => {
    const f = fixture(t); await f.audit.start();
    for (const topic of [`z2m/l1/${ieee}/set`, 'z2m/l1/Test dimmer/set']) {
        f.events.mqtt({topic, message: JSON.stringify({enter_recovery: true, password: 'secret'})});
    }
    f.events.mqtt({topic: `z2m/l1/${ieee}/set/enter_recovery`, message: 'press'});
    f.events.mqtt({topic: `z2m/l1/${ieee}/set`, message: '{"state":"ON"}'});
    f.events.mqtt({topic: `z2m/l1/${ieee}`, message: '{"enter_recovery":true}'});
    f.events.mqtt({topic: 'z2m/l1/other Test dimmer/set', message: '{"enter_recovery":true}'});
    const records = f.records().filter((r) => r.kind === 'request');
    assert.equal(records.length, 3);
    assert.ok(records.every((r) => r.ieee === ieee && r.accepted_value));
    assert.ok(!JSON.stringify(f.records()).includes('secret'));
    assert.equal(f.calls.length, 0);
    await f.audit.stop();
});
test('observes outgoing recovery commands without changing return values or errors', async (t) => {
    const f = fixture(t); const original = f.endpoint.command;
    await f.audit.start();
    assert.equal(await f.endpoint.command('vimarDimmer', 'enterRecovery', {}, {}), 'ack');
    await f.endpoint.command('genOnOff', 'on', {}, {});
    assert.equal(f.calls.length, 2);
    assert.deepEqual(f.records().filter((r) => r.kind.startsWith('command')).map((r) => r.kind), ['command_start', 'command_ack']);
    await f.audit.stop(); assert.equal(f.endpoint.command, original);
});
test('logging failure cannot suppress or fail a normal command', async (t) => {
    const f = fixture(t, '/nonexistent/vimar-audit-tests');
    await f.audit.start();
    assert.equal(await f.endpoint.command(0xfc00, 4, {}, {}), 'ack');
    assert.equal(f.calls.length, 1);
    assert.ok(f.logs.some((x) => x.includes('file unavailable')));
    await f.audit.stop();
});
test('records command failure and rethrows the original error', async (t) => {
    const f = fixture(t); const failure = new Error('delivery');
    f.endpoint.command = async () => {throw failure;};
    await f.audit.start();
    await assert.rejects(() => f.endpoint.command('vimarDimmer', 'enterRecovery', {}, {}), (e) => e === failure);
    assert.equal(f.records().at(-1).kind, 'command_error');
    await f.audit.stop();
});

test('observes no devices when target configuration is absent', async (t) => {
    const f = fixture(t, undefined, null); const original = f.endpoint.command;
    await f.audit.start();
    f.events.mqtt({topic: `z2m/${ieee}/set`, message: '{"enter_recovery":true}'});
    await f.endpoint.command('vimarDimmer', 'enterRecovery', {}, {});
    assert.equal(f.endpoint.command, original);
    assert.deepEqual(f.records().map(({kind, targets, wrapped}) => ({kind, targets, wrapped})),
        [{kind: 'ready', targets: [], wrapped: 0}]);
    await f.audit.stop();
});
test('invalid target configuration cannot select a device', async (t) => {
    const f = fixture(t, undefined, `Test dimmer,${ieee}/set`);
    const original = f.endpoint.command;
    await f.audit.start();
    f.events.mqtt({topic: `z2m/${ieee}/set`, message: '{"enter_recovery":true}'});
    assert.equal(f.endpoint.command, original);
    assert.deepEqual(f.records().at(-1).targets, []);
    await f.audit.stop();
});
test('normalizes and deduplicates explicitly configured IEEE targets', async (t) => {
    const f = fixture(t, undefined, ` ${ieee.toUpperCase()} , ${ieee} `);
    await f.audit.start();
    assert.deepEqual(f.records().at(-1).targets, [ieee]);
    assert.equal(f.records().at(-1).wrapped, 1);
    await f.endpoint.command('vimarDimmer', 'enterRecovery', {}, {});
    assert.deepEqual(f.records().filter((r) => r.kind.startsWith('command')).map((r) => r.kind),
        ['command_start', 'command_ack']);
    await f.audit.stop();
});
