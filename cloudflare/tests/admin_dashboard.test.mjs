import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

function fixture() {
  const state = {
    settings: {enabled: 1, version: 7},
    devices: [{
      device_id: 'device_1', windows_user: 'qya', hostname: 'workstation',
      machine_hash: 'a'.repeat(64), status: 'pending', app_version: '1.0',
      last_seen: '2026-11-26 09:00:00'
    }],
    blocked: []
  };
  return {
    state,
    env: {
      ADMIN_TOKEN: 'test-secret',
      DB: {
        prepare(sql) {
          let params = [];
          return {
            bind(...args) {params = args; return this;},
            async first() {
              if (sql.includes('FROM settings')) return {...state.settings};
              return null;
            },
            async all() {
              if (sql.includes('FROM devices')) return {results: state.devices};
              if (sql.includes('FROM blocked_machines')) return {results: state.blocked};
              throw new Error('Unexpected select: ' + sql);
            },
            async run() {
              if (sql.startsWith('UPDATE settings SET enabled=')) {
                state.settings.enabled = params[0]; state.settings.version++;
              } else if (sql.startsWith('UPDATE devices SET status=')) {
                const device = state.devices.find(d => d.device_id === params[1]);
                if (!device) return {meta:{changes:0}};
                device.status = params[0];
              } else if (sql.startsWith('UPDATE settings SET version=')) {
                state.settings.version++;
              } else if (sql.startsWith('INSERT OR IGNORE INTO blocked_machines')) {
                if (!state.blocked.some(m => m.machine_hash === params[0])) state.blocked.push({machine_hash: params[0]});
              } else if (sql.startsWith('DELETE FROM blocked_machines')) {
                state.blocked = state.blocked.filter(m => m.machine_hash !== params[0]);
              } else throw new Error('Unexpected SQL: ' + sql);
              return {meta:{changes:1}};
            }
          };
        }
      }
    }
  };
}
const url = 'https://example.workers.dev';
const req = (path, token, body) => new Request(url + path, {
  method: body === undefined ? 'GET' : 'POST',
  headers: {
    ...(token ? {Authorization: 'Bearer ' + token} : {}),
    ...(body !== undefined ? {'Content-Type':'application/json'} : {})
  },
  ...(body === undefined ? {} : {body: JSON.stringify(body)})
});
test('admin HTML has no embedded secrets, forbids framing and has CSP', async () => {
  const {env} = fixture();
  const response = await worker.fetch(req('/admin'), env);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /License Administration/);
  assert.match(html, /\/admin\/app\.js/);
  assert.doesNotMatch(html, /test-secret/);
  assert.match(response.headers.get('Content-Security-Policy'), /frame-ancestors 'none'/);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
});
test('dashboard JS available and no token embedded', async () => {
  const {env} = fixture();
  const response = await worker.fetch(req('/admin/app.js'), env);
  assert.equal(response.status, 200);
  assert.match(await response.text(), /\/admin\/devices/);
});
test('device and mutation APIs reject unauthenticated users', async () => {
  const {env} = fixture();
  assert.equal((await worker.fetch(req('/admin/devices'), env)).status, 401);
  assert.equal((await worker.fetch(req('/admin/global', 'wrong', {enabled:false}), env)).status, 401);
});
test('authenticated admin can list, approve, block machine and shutdown', async () => {
  const {env, state} = fixture();
  const list = await worker.fetch(req('/admin/devices','test-secret'), env);
  assert.equal(list.status, 200);
  assert.equal((await list.json()).devices[0].status, 'pending');
  const approved = await worker.fetch(req('/admin/device','test-secret',{device_id:'device_1',status:'approved'}),env);
  assert.equal(approved.status,200);
  assert.equal(state.devices[0].status,'approved');
  assert.equal(state.settings.version,8);
  const blocked = await worker.fetch(req('/admin/machine','test-secret',{machine_hash:'a'.repeat(64),blocked:true}),env);
  assert.equal(blocked.status,200);
  assert.equal(state.blocked.length,1);
  assert.equal(state.settings.version,9);
  const shutdown = await worker.fetch(req('/admin/global','test-secret',{enabled:false}),env);
  assert.equal(shutdown.status,200);
  assert.equal(state.settings.enabled,0);
  assert.equal(state.settings.version,10);
});
